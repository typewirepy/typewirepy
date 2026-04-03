from __future__ import annotations

from unittest.mock import patch

import pytest

from typewirepy import TypeWireContainer, type_wire_group_of, type_wire_of
from typewirepy.errors import CreatorError, NotResolvedError, WireNotRegisteredError
from typewirepy.scope import SINGLETON, TRANSIENT
from typewirepy.token import WireToken


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

    with pytest.raises(CreatorError):
        wire.get_instance_sync(container)

    await container.teardown()


# --- get_cached tests ---


async def test_get_cached_returns_cached_singleton() -> None:
    """get_cached returns the value for an already-resolved singleton."""
    wire = type_wire_of(token="S", creator=lambda: "cached_val", scope=SINGLETON)
    container = TypeWireContainer()
    await wire.apply(container)
    await wire.get_instance(container)  # populate cache

    assert container.get_cached(wire.token) == "cached_val"
    await container.teardown()


async def test_get_cached_raises_not_resolved_error() -> None:
    """get_cached raises NotResolvedError for a registered but unresolved token."""
    wire = type_wire_of(token="Unresolv", creator=lambda: 1, scope=SINGLETON)
    container = TypeWireContainer()
    await wire.apply(container)

    with pytest.raises(NotResolvedError):
        container.get_cached(wire.token)

    await container.teardown()


def test_get_cached_raises_wire_not_registered_error() -> None:
    """get_cached raises WireNotRegisteredError for an unregistered token."""
    container = TypeWireContainer()
    token: WireToken[str] = WireToken("Ghost")

    with pytest.raises(WireNotRegisteredError):
        container.get_cached(token)


# --- fast-path tests ---


async def test_cached_singleton_skips_thread_in_running_loop() -> None:
    """Second get_instance_sync call for a cached singleton should not spawn a thread."""
    wire = type_wire_of(token="Fast", creator=lambda: 99, scope=SINGLETON)
    container = TypeWireContainer()

    # First call: populates cache (will use thread since loop is running)
    wire.apply_sync(container)
    wire.get_instance_sync(container)

    # Second call: should hit get_cached fast path, no thread needed
    with patch("typewirepy.wire.threading.Thread") as mock_thread:
        result = wire.get_instance_sync(container)

    assert result == 99
    mock_thread.assert_not_called()

    await container.teardown()


async def test_transient_does_not_use_cache_fast_path() -> None:
    """Transient wires always go through _run_sync, even after prior resolution."""
    call_count = 0

    def counting_creator() -> str:
        nonlocal call_count
        call_count += 1
        return f"val_{call_count}"

    wire = type_wire_of(token="Trans", creator=counting_creator, scope=TRANSIENT)
    container = TypeWireContainer()
    wire.apply_sync(container)

    first = wire.get_instance_sync(container)
    second = wire.get_instance_sync(container)

    assert first == "val_1"
    assert second == "val_2"
    assert call_count == 2

    await container.teardown()


async def test_uncached_singleton_falls_through_to_run_sync() -> None:
    """First get_instance_sync for a singleton should work via _run_sync fallback."""
    wire = type_wire_of(token="FirstCall", creator=lambda: "fresh", scope=SINGLETON)
    container = TypeWireContainer()
    wire.apply_sync(container)

    # First resolution — not cached yet, should fall through to _run_sync
    result = wire.get_instance_sync(container)
    assert result == "fresh"

    await container.teardown()
