from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import inspect
import logging
import threading
import warnings
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from contextvars import ContextVar
from types import TracebackType
from typing import NamedTuple, TypeVar, cast

from typewirepy.errors import (
    CircularDependencyError,
    NotResolvedError,
    TeardownError,
    WireNotRegisteredError,
)
from typewirepy.monitor import CircularDependencyMonitor, ResolutionMonitor
from typewirepy.scope import SINGLETON, Scope
from typewirepy.token import WireToken
from typewirepy.wire import _run_sync

T = TypeVar("T")

logger = logging.getLogger(__name__)

_Cleanup = Generator[object, None, None] | AsyncGenerator[object, None]

_SWALLOW_DEPRECATION = (
    "raise_teardown_errors=False is deprecated and will be removed in a future release; "
    "teardown raises TeardownError by default. Handle TeardownError instead."
)

# Set as a creation's result when it ends by cancellation: its waiters retry.
_RETRY = object()


class _Creation:
    """The in-progress creation of one singleton, shared by everyone resolving it."""

    __slots__ = ("future", "token", "waiting_on")

    def __init__(self, token: WireToken[object]) -> None:
        self.token = token
        # Thread-safe, and awaitable from any event loop via asyncio.wrap_future.
        # Marked running so a waiter's cancellation can't cancel it for everyone.
        self.future: concurrent.futures.Future[object] = concurrent.futures.Future()
        self.future.set_running_or_notify_cancel()
        # What work inside this creation is waiting on: (other creation, the tokens on
        # the way there from this one), so a cycle error can name every hop.
        self.waiting_on: list[tuple[_Creation, tuple[str, ...]]] = []


class _Frame(NamedTuple):
    container: TypeWireContainer
    token: WireToken[object]
    creation: _Creation | None  # None for transients
    monitor: ResolutionMonitor
    task: asyncio.Task[object] | None


# The chain of resolves the current code is running inside, innermost last. A
# ContextVar keeps it per logical call: concurrent tasks and threads each extend their
# own copy, while a task spawned inside a creator inherits its ancestry.
_RESOLVING: ContextVar[tuple[_Frame, ...]] = ContextVar("typewire_resolving", default=())


class TypeWireContainer:
    """Default async container that stores factories, manages scopes, and handles teardown.

    :meth:`teardown` (and the context-manager exits) raise a
    :class:`~typewirepy.TeardownError` carrying every cleanup failure. The deprecated
    ``raise_teardown_errors=False`` logs the failures instead.
    """

    def __init__(
        self,
        *,
        monitor_factory: Callable[[], ResolutionMonitor] | None = None,
        raise_teardown_errors: bool = True,
    ) -> None:
        if not raise_teardown_errors:
            warnings.warn(_SWALLOW_DEPRECATION, DeprecationWarning, stacklevel=2)
        self._factories: dict[WireToken[object], Callable[[], Awaitable[object]]] = {}
        self._scopes: dict[WireToken[object], Scope] = {}
        self._singletons: dict[WireToken[object], object] = {}
        self._generators: list[tuple[str, _Cleanup]] = []
        self._monitor_factory = monitor_factory or CircularDependencyMonitor
        self._raise_teardown_errors = raise_teardown_errors
        self._creations: dict[WireToken[object], _Creation] = {}
        self._lock = threading.Lock()  # guards _singletons/_creations check-and-set

    def create_monitor(self) -> ResolutionMonitor:
        """Create a new resolution monitor instance."""
        return self._monitor_factory()

    async def register(
        self, token: WireToken[T], factory: Callable[[], Awaitable[T]], scope: Scope
    ) -> None:
        """Store a factory and its scope for later resolution."""
        self._factories[token] = factory
        self._scopes[token] = scope

    async def resolve(self, token: WireToken[T]) -> T:
        """Resolve a token to its value, caching singletons and tracking generators.

        Safe to call concurrently from tasks and threads. Each resolve keeps its own
        chain, so only a token already on that chain is a cycle. Concurrent first
        resolves of a singleton share one creation and its value or error; a failed
        creation caches nothing, and one that ends by cancellation lets its waiters
        retry. A resolve that would wait on a creation that is itself waiting on this
        resolve's chain raises :class:`~typewirepy.CircularDependencyError` instead of
        deadlocking.
        """
        if token not in self._factories:
            raise WireNotRegisteredError(token.label)

        if token in self._singletons:
            return cast("T", self._singletons[token])

        key = cast("WireToken[object]", token)
        chain = [f for f in _RESOLVING.get() if f.container is self]
        if any(f.token == key for f in chain):
            raise CircularDependencyError([*(f.token.label for f in chain), token.label])

        # One monitor per task: each sees a strictly nested enter/exit sequence.
        task = asyncio.current_task()
        reuse = chain and chain[-1].task is task
        monitor = chain[-1].monitor if reuse else self.create_monitor()

        monitor.enter(key)
        try:
            if self._scopes[key] != SINGLETON:
                return cast("T", await self._create(key, None, monitor, task))
            while True:
                with self._lock:
                    if key in self._singletons:
                        return cast("T", self._singletons[key])
                    creation = self._creations.get(key)
                    owner = creation is None
                    if creation is None:
                        creation = self._creations[key] = _Creation(key)
                if owner:
                    return cast("T", await self._create_singleton(creation, monitor, task))
                result = await self._wait(creation, chain)
                if result is not _RETRY:
                    return cast("T", result)
        finally:
            monitor.exit(key)

    async def _create(
        self,
        token: WireToken[object],
        creation: _Creation | None,
        monitor: ResolutionMonitor,
        task: asyncio.Task[object] | None,
    ) -> object:
        frame = _Frame(self, token, creation, monitor, task)
        reset = _RESOLVING.set((*_RESOLVING.get(), frame))
        try:
            raw = self._factories[token]()
            result: object = await raw if inspect.isawaitable(raw) else raw

            if isinstance(result, AsyncGenerator):
                agen = cast("AsyncGenerator[object, None]", result)
                result = await agen.__anext__()
                self._generators.append((token.label, agen))
            elif isinstance(result, Generator):
                sgen = cast("Generator[object, None, None]", result)
                result = next(sgen)
                self._generators.append((token.label, sgen))

            return result
        finally:
            _RESOLVING.reset(reset)

    async def _create_singleton(
        self,
        creation: _Creation,
        monitor: ResolutionMonitor,
        task: asyncio.Task[object] | None,
    ) -> object:
        token = creation.token
        try:
            result = await self._create(token, creation, monitor, task)
        except Exception as e:
            self._end_creation(creation)
            creation.future.set_exception(e)
            raise
        except BaseException:
            self._end_creation(creation)
            creation.future.set_result(_RETRY)
            raise
        self._end_creation(creation, result)
        creation.future.set_result(result)
        return result

    def _end_creation(self, creation: _Creation, *result: object) -> None:
        """Drop the creation and, given a result, cache it in the same critical section."""
        with self._lock:
            if result:
                self._singletons[creation.token] = result[0]
            if self._creations.get(creation.token) is creation:
                del self._creations[creation.token]

    async def _wait(self, creation: _Creation, chain: list[_Frame]) -> object:
        """Wait for another resolve's creation, refusing to wait in a cycle."""
        # Every creation this chain holds is blocked by this wait, not just the
        # innermost one, so each records it.
        records = [
            (f.creation, (creation, tuple(g.token.label for g in chain[i + 1 :])))
            for i, f in enumerate(chain)
            if f.creation is not None
        ]
        with self._lock:
            cycle = self._wait_cycle(creation, chain)
            if cycle is not None:
                raise CircularDependencyError(cycle)
            for held, entry in records:
                held.waiting_on.append(entry)
        try:
            return await asyncio.wrap_future(creation.future)
        finally:
            with self._lock:
                for held, entry in records:
                    held.waiting_on.remove(entry)

    @staticmethod
    def _wait_cycle(target: _Creation, chain: list[_Frame]) -> list[str] | None:
        """Path of the cycle if waiting on *target* would wait on our own chain."""
        on_chain = {f.token for f in chain}
        prefix = [f.token.label for f in chain]
        stack: list[tuple[_Creation, list[str]]] = [(target, [target.token.label])]
        seen: set[int] = set()
        while stack:
            creation, path = stack.pop()
            if creation.token in on_chain:
                return [*prefix, *path]
            if id(creation) in seen:
                continue
            seen.add(id(creation))
            stack.extend((w, [*path, *via, w.token.label]) for w, via in creation.waiting_on)
        return None

    def has(self, token: WireToken[object]) -> bool:
        """Return True if a factory has been registered for *token*."""
        return token in self._factories

    def get_cached(self, token: WireToken[T]) -> T:
        """Return cached value for token.

        Raises WireNotRegisteredError if token was never registered.
        Raises NotResolvedError if token is registered but not yet resolved.
        """
        if token not in self._factories:
            raise WireNotRegisteredError(token.label)
        if token not in self._singletons:
            raise NotResolvedError(token.label)
        return cast("T", self._singletons[token])

    async def teardown(self) -> None:
        """Finalize all tracked generators in reverse creation order and clear state.

        Each generator-based creator that was resolved is finalized exactly once;
        wires that were never resolved have nothing to clean. Every cleanup runs even
        when an earlier one raises.

        The failures are raised at the end as one :class:`~typewirepy.TeardownError`
        (an :class:`ExceptionGroup`) holding every cleanup exception in the order the
        cleanups ran, each with a note naming its wire; the message names the first
        failing wire and its exception type (the exception messages are in
        ``exceptions``). With the deprecated ``raise_teardown_errors=False``, each
        failure is logged and none is raised. A teardown with no failures raises nothing.

        From a context-manager exit whose body is already raising:

        - an :class:`Exception` in flight: the ``TeardownError`` is raised, with the
          body's exception as its ``__context__``;
        - any other :class:`BaseException` in flight (``asyncio.CancelledError``,
          ``KeyboardInterrupt``, ``SystemExit``, ...): that exception keeps propagating
          and the ``TeardownError`` is logged, so cancellation, ``asyncio.timeout`` and
          ``TaskGroup`` keep working.

        After teardown the container is empty: resolving a wire raises
        :class:`~typewirepy.WireNotRegisteredError` until it is applied again.
        """
        errors: list[Exception] = []
        first_label = ""
        while self._generators:
            label, gen = self._generators.pop()
            try:
                if isinstance(gen, AsyncGenerator):
                    with contextlib.suppress(StopAsyncIteration):
                        await gen.__anext__()
                else:
                    with contextlib.suppress(StopIteration):
                        next(gen)
            except Exception as e:
                if not self._raise_teardown_errors:
                    logger.exception("Error during teardown of wire %r", label)
                    continue
                e.add_note(f"raised by the cleanup of wire {label!r}")
                if not errors:
                    first_label = label
                errors.append(e)

        self._singletons.clear()
        self._factories.clear()
        self._scopes.clear()

        if errors:
            first = errors[0]
            raise TeardownError(
                f"{len(errors)} cleanup(s) failed during teardown; first failure in wire "
                f"{first_label!r} ({type(first).__name__})",
                errors,
            )

    async def _exit(self, in_flight: BaseException | None) -> None:
        """Teardown for a context-manager exit; see :meth:`teardown` for the rules."""
        try:
            await self.teardown()
        except TeardownError:
            if in_flight is None or isinstance(in_flight, Exception):
                raise
            logger.exception(
                "Cleanup failed during teardown while %s was propagating; it is not replaced",
                type(in_flight).__name__,
            )

    async def __aenter__(self) -> TypeWireContainer:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._exit(exc_val)

    @classmethod
    def sync(cls, *, raise_teardown_errors: bool = True) -> _SyncContextManager:
        """Return a synchronous context manager wrapping a new container.

        *raise_teardown_errors* (deprecated when ``False``) is passed to the container;
        see :meth:`teardown`.
        """
        container = cls()
        if not raise_teardown_errors:
            warnings.warn(_SWALLOW_DEPRECATION, DeprecationWarning, stacklevel=2)
            container._raise_teardown_errors = False
        return _SyncContextManager(container)


class _SyncContextManager:
    def __init__(self, container: TypeWireContainer) -> None:
        self._container = container

    def __enter__(self) -> TypeWireContainer:
        return self._container

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        _run_sync(self._container._exit(exc_val))
