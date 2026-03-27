from __future__ import annotations

import pytest

from typewirepy import (
    CircularDependencyError,
    CircularDependencyMonitor,
    TypeWireContainer,
    WireToken,
)
from typewirepy.scope import SINGLETON


async def test_a_b_cycle() -> None:
    container = TypeWireContainer()
    token_a: WireToken[str] = WireToken("A")
    token_b: WireToken[str] = WireToken("B")

    async def factory_a() -> str:
        return f"A({await container.resolve(token_b)})"

    async def factory_b() -> str:
        return f"B({await container.resolve(token_a)})"

    await container.register(token_a, factory_a, SINGLETON)
    await container.register(token_b, factory_b, SINGLETON)

    with pytest.raises(CircularDependencyError, match="A -> B -> A"):
        await container.resolve(token_a)


async def test_a_b_c_cycle() -> None:
    container = TypeWireContainer()
    token_a: WireToken[str] = WireToken("A")
    token_b: WireToken[str] = WireToken("B")
    token_c: WireToken[str] = WireToken("C")

    async def factory_a() -> str:
        return f"A({await container.resolve(token_b)})"

    async def factory_b() -> str:
        return f"B({await container.resolve(token_c)})"

    async def factory_c() -> str:
        return f"C({await container.resolve(token_a)})"

    await container.register(token_a, factory_a, SINGLETON)
    await container.register(token_b, factory_b, SINGLETON)
    await container.register(token_c, factory_c, SINGLETON)

    with pytest.raises(CircularDependencyError, match="A -> B -> C -> A"):
        await container.resolve(token_a)


async def test_self_reference() -> None:
    container = TypeWireContainer()
    token: WireToken[str] = WireToken("Self")

    async def factory() -> str:
        return f"Self({await container.resolve(token)})"

    await container.register(token, factory, SINGLETON)

    with pytest.raises(CircularDependencyError, match="Self -> Self"):
        await container.resolve(token)


async def test_error_message_contains_path() -> None:
    container = TypeWireContainer()
    token_a: WireToken[str] = WireToken("A")
    token_b: WireToken[str] = WireToken("B")

    async def factory_a() -> str:
        return f"A({await container.resolve(token_b)})"

    async def factory_b() -> str:
        return f"B({await container.resolve(token_a)})"

    await container.register(token_a, factory_a, SINGLETON)
    await container.register(token_b, factory_b, SINGLETON)

    with pytest.raises(CircularDependencyError) as exc_info:
        await container.resolve(token_a)
    assert "A" in str(exc_info.value)
    assert "B" in str(exc_info.value)
    assert exc_info.value.path == ["A", "B", "A"]


async def test_custom_monitor_factory() -> None:
    """Container accepts a custom monitor_factory."""
    calls: list[str] = []

    class TrackingMonitor:
        def enter(self, token: WireToken[object]) -> None:
            calls.append(f"enter:{token.label}")

        def exit(self, token: WireToken[object]) -> None:
            calls.append(f"exit:{token.label}")

    container = TypeWireContainer(monitor_factory=TrackingMonitor)
    token: WireToken[str] = WireToken("X")

    async def factory_x() -> str:
        return "x"

    await container.register(token, factory_x, SINGLETON)
    result = await container.resolve(token)

    assert result == "x"
    assert calls == ["enter:X", "exit:X"]


async def test_default_monitor_is_circular_dependency_monitor() -> None:
    container = TypeWireContainer()
    monitor = container.create_monitor()
    assert isinstance(monitor, CircularDependencyMonitor)
