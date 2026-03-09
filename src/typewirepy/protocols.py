from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from typewirepy._token import _WireToken
    from typewirepy.scope import Scope


@runtime_checkable
class ContainerAdapter(Protocol):
    """Protocol that any DI container must satisfy to work with TypeWire."""

    async def register(self, token: _WireToken, factory: Any, scope: Scope) -> None:
        """Store a factory for *token* with the given *scope*."""
        ...

    async def resolve(self, token: _WireToken) -> Any:
        """Resolve *token* to its value."""
        ...

    def has(self, token: _WireToken) -> bool:
        """Return True if *token* has been registered."""
        ...
