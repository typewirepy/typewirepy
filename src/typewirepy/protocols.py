from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from typewirepy._token import _WireToken
    from typewirepy.scope import Scope


@runtime_checkable
class ContainerAdapter(Protocol):
    async def register(self, token: _WireToken, factory: Any, scope: Scope) -> None: ...

    async def resolve(self, token: _WireToken) -> Any: ...

    def has(self, token: _WireToken) -> bool: ...
