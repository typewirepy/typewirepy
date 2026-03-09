from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from typing import TYPE_CHECKING, Any

from typewirepy.scope import Scope

if TYPE_CHECKING:
    from collections.abc import Callable

    from typewirepy._token import _WireToken

from typewirepy.errors import WireNotRegisteredError

logger = logging.getLogger(__name__)


class TypeWireContainer:
    """Default async container that stores factories, manages scopes, and handles teardown."""

    def __init__(self) -> None:
        self._factories: dict[_WireToken, Callable[[], Any]] = {}
        self._scopes: dict[_WireToken, Scope] = {}
        self._singletons: dict[_WireToken, Any] = {}
        self._generators: list[Any] = []

    async def register(self, token: _WireToken, factory: Callable[[], Any], scope: Scope) -> None:
        """Store a factory and its scope for later resolution."""
        self._factories[token] = factory
        self._scopes[token] = scope

    async def resolve(self, token: _WireToken) -> Any:
        """Resolve a token to its value, caching singletons and tracking generators."""
        if token not in self._factories:
            raise WireNotRegisteredError(token.label)

        if token in self._singletons:
            return self._singletons[token]

        result = self._factories[token]()
        if inspect.isawaitable(result):
            result = await result

        if inspect.isasyncgen(result):
            value = await result.__anext__()
            self._generators.append(result)
            result = value
        elif inspect.isgenerator(result):
            value = next(result)
            self._generators.append(result)
            result = value

        if self._scopes[token] == Scope.SINGLETON:
            self._singletons[token] = result

        return result

    def has(self, token: _WireToken) -> bool:
        """Return True if a factory has been registered for *token*."""
        return token in self._factories

    async def teardown(self) -> None:
        """Finalize all tracked generators in reverse order and clear state."""
        for gen in reversed(self._generators):
            try:
                if inspect.isasyncgen(gen):
                    with contextlib.suppress(StopAsyncIteration):
                        await gen.__anext__()
                else:
                    with contextlib.suppress(StopIteration):
                        next(gen)
            except Exception:  # noqa: PERF203
                logger.exception("Error during teardown of generator %r", gen)

        self._generators.clear()
        self._singletons.clear()
        self._factories.clear()
        self._scopes.clear()

    async def __aenter__(self) -> TypeWireContainer:
        return self

    async def __aexit__(self, *exc: Any) -> None:
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

    def __exit__(self, *exc: Any) -> None:
        asyncio.run(self._container.teardown())
