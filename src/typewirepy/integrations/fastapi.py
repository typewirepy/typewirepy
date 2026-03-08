from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

    from typewirepy.container import TypeWireContainer
    from typewirepy.wire import TypeWire

T = TypeVar("T")


def wire_depends(
    wire: TypeWire[T],
    get_container: Callable[[], TypeWireContainer],
) -> Any:
    async def _resolver() -> T:
        return await wire.get_instance(get_container())

    return _resolver
