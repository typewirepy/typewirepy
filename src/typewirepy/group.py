from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from typewirepy.wire import TypeWire, _check_no_running_loop

if TYPE_CHECKING:
    from typewirepy.protocols import ContainerAdapter


class TypeWireGroup:
    """Immutable ordered collection of wires, applied as a unit."""

    __slots__ = ("_wires",)

    def __init__(self, wires: list[TypeWire[Any]]) -> None:
        object.__setattr__(self, "_wires", list(wires))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("TypeWireGroup instances are immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("TypeWireGroup instances are immutable")

    def __repr__(self) -> str:
        labels = [w._token.label for w in self._wires]
        return f"TypeWireGroup(wires={labels!r})"

    async def apply(self, container: ContainerAdapter) -> None:
        for wire in self._wires:
            await wire.apply(container)

    def with_extra_wires(self, wires: list[TypeWire[Any]]) -> TypeWireGroup:
        return TypeWireGroup(self._wires + wires)

    def apply_sync(self, container: ContainerAdapter) -> None:
        _check_no_running_loop()
        asyncio.run(self.apply(container))
