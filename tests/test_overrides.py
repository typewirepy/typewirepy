from __future__ import annotations

from typewirepy import TypeWireContainer, type_wire_group_of, type_wire_of


async def test_with_creator_1_arg_override() -> None:
    wire = type_wire_of(token="Svc", creator=lambda: "original")
    overridden = wire.with_creator(lambda _ctx: "mock")

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        assert await wire.get_instance(container) == "mock"


async def test_with_creator_2_arg_spy() -> None:
    wire = type_wire_of(token="Svc", creator=lambda: "original")

    async def spy(ctx: object, original: object) -> str:
        val = await original()  # type: ignore[operator]
        return f"spy({val})"

    overridden = wire.with_creator(spy)

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        assert await wire.get_instance(container) == "spy(original)"


async def test_override_via_with_extra_wires() -> None:
    wire = type_wire_of(token="Svc", creator=lambda: "original")
    group = type_wire_group_of([wire])
    test_group = group.with_extra_wires([wire.with_creator(lambda _ctx: "mock")])

    async with TypeWireContainer() as container:
        await test_group.apply(container)
        assert await wire.get_instance(container) == "mock"


async def test_chained_with_creator() -> None:
    wire = type_wire_of(token="Svc", creator=lambda: "v1")
    v2 = wire.with_creator(lambda _ctx: "v2")
    v3 = v2.with_creator(lambda _ctx: "v3")

    async with TypeWireContainer() as container:
        await v3.apply(container)
        assert await wire.get_instance(container) == "v3"
