from __future__ import annotations

import contextlib
import inspect
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from types import TracebackType
from typing import TypeVar, cast

from typewirepy.errors import WireNotRegisteredError
from typewirepy.wire import _run_sync
from typewirepy.monitor import CircularDependencyMonitor, ResolutionMonitor
from typewirepy.scope import SINGLETON, Scope
from typewirepy.token import WireToken

T = TypeVar("T")

logger = logging.getLogger(__name__)


class TypeWireContainer:
    """Default async container that stores factories, manages scopes, and handles teardown."""

    def __init__(
        self,
        *,
        monitor_factory: Callable[[], ResolutionMonitor] | None = None,
    ) -> None:
        self._factories: dict[WireToken[object], Callable[[], Awaitable[object]]] = {}
        self._scopes: dict[WireToken[object], Scope] = {}
        self._singletons: dict[WireToken[object], object] = {}
        self._generators: list[Generator[object, None, None] | AsyncGenerator[object, None]] = []
        self._monitor_factory = monitor_factory or CircularDependencyMonitor
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
                self._generators.append(agen)
            elif isinstance(result, Generator):
                sgen = cast("Generator[object, None, None]", result)
                result = next(sgen)
                self._generators.append(sgen)

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

    async def teardown(self) -> None:
        """Finalize all tracked generators in reverse order and clear state."""
        for gen in reversed(self._generators):
            try:
                if isinstance(gen, AsyncGenerator):
                    with contextlib.suppress(StopAsyncIteration):
                        await gen.__anext__()
                else:
                    with contextlib.suppress(StopIteration):
                        next(gen)
            except Exception:
                logger.exception("Error during teardown of generator %r", gen)

        self._generators.clear()
        self._singletons.clear()
        self._factories.clear()
        self._scopes.clear()

    async def __aenter__(self) -> TypeWireContainer:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.teardown()

    @classmethod
    def sync(cls) -> _SyncContextManager:
        """Return a synchronous context manager wrapping a new container."""
        return _SyncContextManager(cls())


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
        _run_sync(self._container.teardown())
