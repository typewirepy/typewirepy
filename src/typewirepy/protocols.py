from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar, runtime_checkable

from typewirepy._token import _WireToken
from typewirepy.scope import Scope

T = TypeVar("T")


@runtime_checkable
class ContainerAdapter(Protocol):
    """Protocol that any DI container must satisfy to work with TypeWire."""

    async def register(
        self, token: _WireToken[T], factory: Callable[[], Awaitable[T]], scope: Scope
    ) -> None:
        """Store a factory for *token* with the given *scope*."""
        ...

    async def resolve(self, token: _WireToken[T]) -> T:
        """Resolve *token* to its value."""
        ...

    def has(self, token: _WireToken[object]) -> bool:
        """Return True if *token* has been registered."""
        ...
