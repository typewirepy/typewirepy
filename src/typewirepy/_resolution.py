"""Concurrency-safe resolution: per-chain cycle detection and once-only singletons.

Private. :class:`ResolveCoordinator` gives one container these guarantees, whatever
``monitor_factory`` is installed:

- Each resolve keeps its own chain, so only a token already on that chain is a cycle.
- Concurrent first resolves of a singleton share one creation and its value or error.
  A failed creation caches nothing; one abandoned by cancellation lets its waiters
  retry.
- A resolve that could never stop waiting raises instead of hanging: when the
  creation it would wait on is waiting, possibly transitively, on this resolve's own
  chain, or is running on an event loop that this resolve's ``*_sync`` call blocks.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import threading
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import NamedTuple

from typewirepy.errors import CircularDependencyError, TypeWireError
from typewirepy.monitor import ResolutionMonitor
from typewirepy.token import WireToken


class _Creation:
    """The in-progress creation of one singleton, shared by everyone resolving it."""

    __slots__ = ("abandoned", "future", "loop", "token", "waiting_on")

    def __init__(self, token: WireToken[object]) -> None:
        self.token = token
        self.loop = asyncio.get_running_loop()
        # Thread-safe, and awaitable from any event loop via asyncio.wrap_future.
        # Marked running so a waiter's cancellation can't cancel it for everyone.
        self.future: concurrent.futures.Future[object] = concurrent.futures.Future()
        self.future.set_running_or_notify_cancel()
        # Set when the creation ended by cancellation: waiters retry instead.
        self.abandoned = False
        # What work inside this creation is waiting on: (other creation, the tokens on
        # the way there from this one), so a cycle error can name every hop.
        self.waiting_on: list[tuple[_Creation, tuple[str, ...]]] = []


class _Frame(NamedTuple):
    coordinator: ResolveCoordinator
    token: WireToken[object]
    creation: _Creation | None  # None for transients
    monitor: ResolutionMonitor
    task: asyncio.Task[object] | None


# The chain of resolves the current code is running inside, innermost last. A
# ContextVar keeps it per logical call: concurrent tasks and threads each extend their
# own copy, while a task spawned inside a creator inherits its ancestry.
_RESOLVING: ContextVar[tuple[_Frame, ...]] = ContextVar("typewire_resolving", default=())

# Event loops that a ``*_sync`` call in the current context is blocking until it
# returns. Set by :func:`mark_blocking` for the worker thread's context.
_BLOCKED_LOOPS: ContextVar[tuple[asyncio.AbstractEventLoop, ...]] = ContextVar(
    "typewire_blocked_loops", default=()
)


def mark_blocking(ctx: contextvars.Context, loop: asyncio.AbstractEventLoop) -> None:
    """Record in *ctx* that the code running in it blocks *loop* until it returns."""
    ctx.run(_BLOCKED_LOOPS.set, (*ctx.run(_BLOCKED_LOOPS.get), loop))


class ResolveCoordinator:
    """Runs one container's creations under the guarantees in the module docstring."""

    def __init__(
        self,
        cache: dict[WireToken[object], object],
        create_monitor: Callable[[], ResolutionMonitor],
    ) -> None:
        self._cache = cache  # the container's singleton cache, filled under _lock
        self._create_monitor = create_monitor
        self._creations: dict[WireToken[object], _Creation] = {}
        self._lock = threading.Lock()

    async def resolve(
        self,
        token: WireToken[object],
        build: Callable[[], Awaitable[object]],
        *,
        singleton: bool,
    ) -> object:
        """Build *token* on the caller's chain, once per container if *singleton*."""
        chain = [f for f in _RESOLVING.get() if f.coordinator is self]
        if any(f.token == token for f in chain):
            raise CircularDependencyError([*(f.token.label for f in chain), token.label])

        # One monitor per task: each sees a strictly nested enter/exit sequence.
        task = asyncio.current_task()
        reuse = chain and chain[-1].task is task
        monitor = chain[-1].monitor if reuse else self._create_monitor()

        monitor.enter(token)
        try:
            if not singleton:
                return await self._run(build, _Frame(self, token, None, monitor, task))
            while True:
                with self._lock:
                    if token in self._cache:
                        return self._cache[token]
                    creation = self._creations.get(token)
                    owner = creation is None
                    if creation is None:
                        creation = self._creations[token] = _Creation(token)
                if owner:
                    frame = _Frame(self, token, creation, monitor, task)
                    return await self._create_once(build, frame, creation)
                result = await self._wait(creation, chain)
                if not creation.abandoned:
                    return result
        finally:
            monitor.exit(token)

    @staticmethod
    async def _run(build: Callable[[], Awaitable[object]], frame: _Frame) -> object:
        reset = _RESOLVING.set((*_RESOLVING.get(), frame))
        try:
            return await build()
        finally:
            _RESOLVING.reset(reset)

    async def _create_once(
        self, build: Callable[[], Awaitable[object]], frame: _Frame, creation: _Creation
    ) -> object:
        try:
            result = await self._run(build, frame)
        except Exception as e:
            self._finish(creation)
            creation.future.set_exception(e)
            raise
        except BaseException:
            self._finish(creation)
            creation.abandoned = True
            creation.future.set_result(None)
            raise
        self._finish(creation, result)
        creation.future.set_result(result)
        return result

    def _finish(self, creation: _Creation, *result: object) -> None:
        """Drop the creation and, given a result, cache it in the same critical section."""
        with self._lock:
            if result:
                self._cache[creation.token] = result[0]
            if self._creations.get(creation.token) is creation:
                del self._creations[creation.token]

    async def _wait(self, creation: _Creation, chain: list[_Frame]) -> object:
        """Wait for another resolve's creation, refusing to wait forever."""
        # Every creation this chain holds is blocked by this wait, so each records it.
        records = [
            (f.creation, (creation, tuple(g.token.label for g in chain[i + 1 :])))
            for i, f in enumerate(chain)
            if f.creation is not None
        ]
        with self._lock:
            self._check_wait(creation, chain)
            for held, entry in records:
                held.waiting_on.append(entry)
        try:
            return await asyncio.wrap_future(creation.future)
        finally:
            with self._lock:
                for held, entry in records:
                    held.waiting_on.remove(entry)

    @staticmethod
    def _check_wait(target: _Creation, chain: list[_Frame]) -> None:
        """Raise if waiting on *target* could never end. Call with the lock held."""
        on_chain = {f.token for f in chain}
        prefix = [f.token.label for f in chain]
        blocked = _BLOCKED_LOOPS.get()
        stack: list[tuple[_Creation, list[str]]] = [(target, [target.token.label])]
        seen: set[int] = set()
        while stack:
            creation, path = stack.pop()
            if creation.token in on_chain:
                raise CircularDependencyError([*prefix, *path])
            if creation.loop in blocked:
                raise TypeWireError(
                    f"Resolving would wait on {creation.token.label!r}, whose creation is "
                    f"running on an event loop that this *_sync call is blocking, so it "
                    f"could never finish (via {' -> '.join(path)}). Inside a running event "
                    f"loop, use the async API (await wire.get_instance(container))."
                )
            if id(creation) in seen:
                continue
            seen.add(id(creation))
            stack.extend((w, [*path, *via, w.token.label]) for w, via in creation.waiting_on)
