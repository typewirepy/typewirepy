from __future__ import annotations

import asyncio
from typing import Any

from typewirepy.protocols import ContainerAdapter
from typewirepy.wire import TypeWire, _run_sync


class TypeWireGroup:
    """Immutable ordered collection of wires, applied as a unit."""

    __slots__ = ("_frozen", "_wires")

    def __init__(self, wires: list[TypeWire[Any]]) -> None:
        self._wires = list(wires)
        self._frozen = True

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("TypeWireGroup instances are immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("TypeWireGroup instances are immutable")

    def __repr__(self) -> str:
        labels = [w._token.label for w in self._wires]
        return f"TypeWireGroup(wires={labels!r})"

    @property
    def wires(self) -> list[TypeWire[Any]]:
        """Read-only copy of this group's wires."""
        return list(self._wires)

    async def apply(self, container: ContainerAdapter) -> None:
        for wire in self._wires:
            await wire.apply(container)

    def with_extra_wires(self, wires: list[TypeWire[Any]]) -> TypeWireGroup:
        return TypeWireGroup(self._wires + wires)

    async def get_all_instances(self, container: ContainerAdapter) -> list[Any]:
        """Resolve all wires in this group concurrently."""
        return list(await asyncio.gather(*(wire.get_instance(container) for wire in self._wires)))

    def apply_sync(self, container: ContainerAdapter) -> None:
        _run_sync(self.apply(container))

    def get_all_instances_sync(self, container: ContainerAdapter) -> list[Any]:
        """Resolve all wires in this group synchronously."""
        return _run_sync(self.get_all_instances(container))
