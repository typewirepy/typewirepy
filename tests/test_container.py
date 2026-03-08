from __future__ import annotations

import pytest

from typewirepy import (
    CreatorError,
    Scope,
    TypeWireContainer,
    WireNotRegisteredError,
    type_wire_of,
)


async def test_async_context_manager() -> None:
    async with TypeWireContainer() as container:
        assert isinstance(container, TypeWireContainer)


async def test_register_resolve_has() -> None:
    wire = type_wire_of(token="Val", creator=lambda: 42)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        assert container.has(wire._token)
        assert await wire.get_instance(container) == 42


async def test_singleton_caching() -> None:
    call_count = 0

    def make() -> list[int]:
        nonlocal call_count
        call_count += 1
        return [call_count]

    wire = type_wire_of(token="Single", creator=make, scope=Scope.SINGLETON)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        a = await wire.get_instance(container)
        b = await wire.get_instance(container)
        assert a is b
        assert call_count == 1


async def test_transient_fresh_instances() -> None:
    call_count = 0

    def make() -> list[int]:
        nonlocal call_count
        call_count += 1
        return [call_count]

    wire = type_wire_of(token="Trans", creator=make, scope=Scope.TRANSIENT)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        a = await wire.get_instance(container)
        b = await wire.get_instance(container)
        assert a is not b
        assert call_count == 2


async def test_teardown_clears_state() -> None:
    wire = type_wire_of(token="Val", creator=lambda: 1)
    container = TypeWireContainer()
    await wire.apply(container)
    assert container.has(wire._token)
    await container.teardown()
    assert not container.has(wire._token)


async def test_unregistered_resolve_raises() -> None:
    wire = type_wire_of(token="Missing", creator=lambda: 1)
    async with TypeWireContainer() as container:
        with pytest.raises(WireNotRegisteredError, match="Missing"):
            await wire.get_instance(container)


async def test_creator_error_wrapping() -> None:
    def bad_creator() -> None:
        raise ValueError("boom")

    wire = type_wire_of(token="Bad", creator=bad_creator)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        with pytest.raises(CreatorError, match="boom") as exc_info:
            await wire.get_instance(container)
        assert isinstance(exc_info.value.__cause__, ValueError)
