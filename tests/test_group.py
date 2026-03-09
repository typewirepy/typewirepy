from __future__ import annotations

import pytest

from typewirepy import CreatorError, TypeWireContainer, type_wire_group_of, type_wire_of


async def test_group_apply() -> None:
    w1 = type_wire_of(token="A", creator=lambda: "a")
    w2 = type_wire_of(token="B", creator=lambda: "b")
    group = type_wire_group_of([w1, w2])

    async with TypeWireContainer() as container:
        await group.apply(container)
        assert await w1.get_instance(container) == "a"
        assert await w2.get_instance(container) == "b"


async def test_group_with_extra_wires_override() -> None:
    w1 = type_wire_of(token="A", creator=lambda: "original")
    group = type_wire_group_of([w1])
    overridden = group.with_extra_wires([w1.with_creator(lambda _ctx: "replaced")])

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        assert await w1.get_instance(container) == "replaced"


def test_group_apply_sync() -> None:
    w1 = type_wire_of(token="A", creator=lambda: "a")
    group = type_wire_group_of([w1])

    with TypeWireContainer.sync() as container:
        group.apply_sync(container)
        result = w1.get_instance_sync(container)
        assert result == "a"


def test_group_repr() -> None:
    w1 = type_wire_of(token="A", creator=lambda: 1)
    w2 = type_wire_of(token="B", creator=lambda: 2)
    group = type_wire_group_of([w1, w2])
    assert repr(group) == "TypeWireGroup(wires=['A', 'B'])"


async def test_group_apply_propagates_creator_error() -> None:
    def bad_creator() -> str:
        raise ValueError("boom")

    w_good = type_wire_of(token="Good", creator=lambda: "ok")
    w_bad = type_wire_of(token="Bad", creator=bad_creator)
    group = type_wire_group_of([w_good, w_bad])

    async with TypeWireContainer() as container:
        await group.apply(container)
        with pytest.raises(CreatorError, match="boom"):
            await w_bad.get_instance(container)
