from __future__ import annotations

import pytest

from typewirepy import CircularDependencyError, TypeWireContainer
from typewirepy._token import _WireToken
from typewirepy.scope import Scope
from typewirepy.wire import TypeWire


def _make_circular_pair() -> tuple[TypeWire[str], TypeWire[str]]:
    """Create A <-> B circular dependency."""
    token_a = _WireToken("A")
    token_b = _WireToken("B")

    wire_b: TypeWire[str] = TypeWire(
        token=token_b,
        creator=None,
        create_with=lambda deps: f"B({deps['a']})",
        imports={},
        scope=Scope.SINGLETON,
        convention="dict",
    )

    wire_a: TypeWire[str] = TypeWire(
        token=token_a,
        creator=None,
        create_with=lambda deps: f"A({deps['b']})",
        imports={"b": wire_b},
        scope=Scope.SINGLETON,
        convention="dict",
    )

    # Patch wire_b imports to point to wire_a (circular)
    object.__setattr__(wire_b, "_imports", {"a": wire_a})

    return wire_a, wire_b


async def test_a_b_cycle() -> None:
    wire_a, _wire_b = _make_circular_pair()

    async with TypeWireContainer() as container:
        with pytest.raises(CircularDependencyError, match="A -> B -> A"):
            await wire_a.apply(container)


async def test_a_b_c_cycle() -> None:
    token_a = _WireToken("A")
    token_b = _WireToken("B")
    token_c = _WireToken("C")

    wire_c: TypeWire[str] = TypeWire(
        token=token_c,
        creator=None,
        create_with=lambda deps: deps["a"],
        imports={},
        scope=Scope.SINGLETON,
        convention="dict",
    )
    wire_b: TypeWire[str] = TypeWire(
        token=token_b,
        creator=None,
        create_with=lambda deps: deps["c"],
        imports={"c": wire_c},
        scope=Scope.SINGLETON,
        convention="dict",
    )
    wire_a: TypeWire[str] = TypeWire(
        token=token_a,
        creator=None,
        create_with=lambda deps: deps["b"],
        imports={"b": wire_b},
        scope=Scope.SINGLETON,
        convention="dict",
    )
    object.__setattr__(wire_c, "_imports", {"a": wire_a})

    async with TypeWireContainer() as container:
        with pytest.raises(CircularDependencyError, match="A -> B -> C -> A"):
            await wire_a.apply(container)


async def test_self_reference() -> None:
    token = _WireToken("Self")
    wire: TypeWire[str] = TypeWire(
        token=token,
        creator=None,
        create_with=lambda deps: deps["me"],
        imports={},
        scope=Scope.SINGLETON,
        convention="dict",
    )
    object.__setattr__(wire, "_imports", {"me": wire})

    async with TypeWireContainer() as container:
        with pytest.raises(CircularDependencyError, match="Self -> Self"):
            await wire.apply(container)


async def test_error_message_contains_path() -> None:
    wire_a, _wire_b = _make_circular_pair()

    async with TypeWireContainer() as container:
        with pytest.raises(CircularDependencyError) as exc_info:
            await wire_a.apply(container)
        assert "A" in str(exc_info.value)
        assert "B" in str(exc_info.value)
        assert exc_info.value.path == ["A", "B", "A"]
