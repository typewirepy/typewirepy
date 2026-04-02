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


async def test_sync_api_works_when_loop_running() -> None:
    """Sync API should work even when called from within a running event loop."""
    wire = type_wire_of(token="Val", creator=lambda: 42)
    container = TypeWireContainer()
    wire.apply_sync(container)
    assert wire.get_instance_sync(container) == 42
    await container.teardown()


async def test_sync_context_manager_exit_with_running_loop() -> None:
    """_SyncContextManager.__exit__ should work even inside a running loop."""
    wire = type_wire_of(token="CM", creator=lambda: "ctx_val")
    with TypeWireContainer.sync() as container:
        wire.apply_sync(container)
        assert wire.get_instance_sync(container) == "ctx_val"


async def test_sync_api_propagates_exceptions() -> None:
    """Exceptions from creators should propagate through the thread boundary."""
    def bad_creator() -> str:
        raise ValueError("boom")

    wire = type_wire_of(token="Bad", creator=bad_creator)
    container = TypeWireContainer()
    wire.apply_sync(container)

    from typewirepy.errors import CreatorError

    with pytest.raises(CreatorError):
        wire.get_instance_sync(container)

    await container.teardown()
