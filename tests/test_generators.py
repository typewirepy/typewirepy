from __future__ import annotations

from typing import Any

from typewirepy import TypeWireContainer, type_wire_of


async def test_sync_generator_creator() -> None:
    cleanup_called = False

    def make_resource() -> Any:
        nonlocal cleanup_called
        yield "resource"
        cleanup_called = True

    wire = type_wire_of(token="Res", creator=make_resource)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        result = await wire.get_instance(container)
        assert result == "resource"
        assert not cleanup_called
    assert cleanup_called


async def test_async_generator_creator() -> None:
    cleanup_called = False

    async def make_resource() -> Any:
        nonlocal cleanup_called
        yield "async_resource"
        cleanup_called = True

    wire = type_wire_of(token="AsyncRes", creator=make_resource)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        result = await wire.get_instance(container)
        assert result == "async_resource"
        assert not cleanup_called
    assert cleanup_called


async def test_teardown_reverse_order() -> None:
    order: list[str] = []

    def make_first() -> Any:
        yield "first"
        order.append("first_cleanup")

    def make_second() -> Any:
        yield "second"
        order.append("second_cleanup")

    w1 = type_wire_of(token="First", creator=make_first)
    w2 = type_wire_of(token="Second", creator=make_second)

    async with TypeWireContainer() as container:
        await w1.apply(container)
        await w2.apply(container)
        await w1.get_instance(container)
        await w2.get_instance(container)

    assert order == ["second_cleanup", "first_cleanup"]


async def test_error_during_cleanup_handled(caplog: Any) -> None:
    def make_bad() -> Any:
        yield "value"
        raise RuntimeError("cleanup boom")

    def make_good() -> Any:
        yield "good"

    w1 = type_wire_of(token="Bad", creator=make_bad)
    w2 = type_wire_of(token="Good", creator=make_good)

    container = TypeWireContainer()
    await w1.apply(container)
    await w2.apply(container)
    await w1.get_instance(container)
    await w2.get_instance(container)

    # Teardown should not raise even though w1's cleanup fails
    await container.teardown()
