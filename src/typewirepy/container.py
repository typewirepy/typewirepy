from __future__ import annotations

import contextlib
import inspect
import logging
import warnings
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from types import TracebackType
from typing import TypeVar, cast

from typewirepy.errors import NotResolvedError, TeardownError, WireNotRegisteredError
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
        self._active_monitor: ResolutionMonitor | None = None

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
        """Resolve a token to its value, caching singletons and tracking generators."""
        if token not in self._factories:
            raise WireNotRegisteredError(token.label)

        if token in self._singletons:
            return cast("T", self._singletons[token])

        is_root = self._active_monitor is None
        if is_root:
            self._active_monitor = self.create_monitor()

        monitor = self._active_monitor
        assert monitor is not None
        monitor.enter(token)
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

            if self._scopes[token] == SINGLETON:
                self._singletons[token] = result

            return cast("T", result)
        finally:
            monitor.exit(token)
            if is_root:
                self._active_monitor = None

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
