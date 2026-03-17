from __future__ import annotations

import pytest

from typewirepy import TypeWireContainer, type_wire_group_of, type_wire_of


def test_apply_sync_and_get_instance_sync() -> None:
    wire = type_wire_of(token="Val", creator=lambda: 42)
    with TypeWireContainer.sync() as container:
        wire.apply_sync(container)
        assert wire.get_instance_sync(container) == 42


def test_sync_container_context_manager() -> None:
    wire = type_wire_of(token="Val", creator=lambda: "hello")
    with TypeWireContainer.sync() as container:
        wire.apply_sync(container)
        result = wire.get_instance_sync(container)
        assert result == "hello"
    # After exiting, state is cleared
    assert not container.has(wire.token)


def test_group_apply_sync() -> None:
    w1 = type_wire_of(token="A", creator=lambda: "a")
    w2 = type_wire_of(token="B", creator=lambda: "b")
    group = type_wire_group_of([w1, w2])

    with TypeWireContainer.sync() as container:
        group.apply_sync(container)
        assert w1.get_instance_sync(container) == "a"
        assert w2.get_instance_sync(container) == "b"


async def test_sync_api_raises_when_loop_running() -> None:
    wire = type_wire_of(token="Val", creator=lambda: 1)
    container = TypeWireContainer()

    with pytest.raises(RuntimeError, match="running event loop"):
        wire.apply_sync(container)

    with pytest.raises(RuntimeError, match="running event loop"):
        wire.get_instance_sync(container)
