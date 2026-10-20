from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from typewirepy import (
    TRANSIENT,
    TypeWire,
    TypeWireContainer,
    WireNotRegisteredError,
    type_wire_group_of,
    type_wire_of,
)
from typewirepy._introspect import detect_creator_arity


async def test_with_creator_1_arg_override() -> None:
    wire = type_wire_of(token="Svc", creator=lambda: "original")
    overridden = wire.with_creator(lambda _ctx: "mock")

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        assert await wire.get_instance(container) == "mock"


async def test_with_creator_2_arg_spy() -> None:
    wire = type_wire_of(token="Svc", creator=lambda: "original")

    async def spy(ctx: object, original: Callable[[], Awaitable[object]]) -> str:
        val = await original()
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


async def test_with_creator_2_arg_on_wire_with_imports_dict() -> None:
    dep_wire = type_wire_of(token="Dep", creator=lambda: 42)
    wire = type_wire_of(
        token="Svc",
        create_with=lambda deps: f"value={deps['dep']}",
        imports={"dep": dep_wire},
    )

    async def spy(ctx: object, original: Callable[[], Awaitable[object]]) -> str:
        val = await original()
        return f"spy({val})"

    overridden = wire.with_creator(spy)

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        assert await wire.get_instance(container) == "spy(value=42)"


async def test_with_creator_2_arg_on_wire_with_imports_kwargs() -> None:
    dep_wire = type_wire_of(token="Dep", creator=lambda: 42)

    def make_svc(*, dep: object) -> str:
        return f"value={dep}"

    wire = type_wire_of(
        token="Svc",
        create_with=make_svc,
        imports={"dep": dep_wire},
    )

    async def spy(ctx: object, original: Callable[[], Awaitable[object]]) -> str:
        val = await original()
        return f"spy({val})"

    overridden = wire.with_creator(spy)

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        assert await wire.get_instance(container) == "spy(value=42)"


async def test_chained_with_creator_2_arg_on_wire_with_imports() -> None:
    dep_wire = type_wire_of(token="Dep", creator=lambda: 10)
    wire = type_wire_of(
        token="Svc",
        create_with=lambda deps: deps["dep"] * 2,
        imports={"dep": dep_wire},
    )

    async def layer1(ctx: object, original: Callable[[], Awaitable[object]]) -> int:
        val = await original()
        assert isinstance(val, int)
        return val + 100

    async def layer2(ctx: object, original: Callable[[], Awaitable[object]]) -> str:
        val = await original()
        return f"final={val}"

    overridden = wire.with_creator(layer1).with_creator(layer2)

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        assert await wire.get_instance(container) == "final=120"


async def test_chained_with_creator() -> None:
    wire = type_wire_of(token="Svc", creator=lambda: "v1")
    v2 = wire.with_creator(lambda _ctx: "v2")
    v3 = v2.with_creator(lambda _ctx: "v3")

    async with TypeWireContainer() as container:
        await v3.apply(container)
        assert await wire.get_instance(container) == "v3"


# --- Regression: lambda default args must not trigger spy pattern ---


async def test_with_creator_lambda_default_arg_not_misclassified() -> None:
    """lambda _ctx, val=captured: val must resolve to the captured value, not a function."""
    loader = "my_s3_loader"
    wire = type_wire_of(token="Svc", creator=lambda: "original")
    overridden = wire.with_creator(lambda _ctx, ldr=loader: ldr)

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        result = await wire.get_instance(container)
        assert result == "my_s3_loader"


async def test_with_creator_lambda_multiple_default_args() -> None:
    wire = type_wire_of(token="Svc", creator=lambda: "original")
    overridden = wire.with_creator(lambda _ctx, a="alpha", b="beta": f"{a}-{b}")

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        result = await wire.get_instance(container)
        assert result == "alpha-beta"


async def test_with_creator_2_arg_spy_still_works_after_default_fix() -> None:
    """Two required positional params still triggers the wrap/spy pattern."""
    wire = type_wire_of(token="Svc", creator=lambda: "original")

    async def spy(ctx: object, original: Callable[[], Awaitable[object]]) -> str:
        val = await original()
        return f"spy({val})"

    overridden = wire.with_creator(spy)

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        assert await wire.get_instance(container) == "spy(original)"


# --- Unit tests for detect_creator_arity ---


def test_detect_creator_arity_one_required_param() -> None:
    assert detect_creator_arity(lambda ctx: None) == 1


def test_detect_creator_arity_two_required_params() -> None:
    assert detect_creator_arity(lambda ctx, original: None) == 2


def test_detect_creator_arity_one_required_one_default() -> None:
    assert detect_creator_arity(lambda ctx, x=10: None) == 1


def test_detect_creator_arity_one_required_multiple_defaults() -> None:
    assert detect_creator_arity(lambda ctx, x=10, y=20: None) == 1


def test_detect_creator_arity_no_params() -> None:
    assert detect_creator_arity(lambda: None) == 1


def test_detect_creator_arity_uninspectable() -> None:
    assert detect_creator_arity(42) == 1


# ---------------------------------------------------------------------------
# keep_imports
# ---------------------------------------------------------------------------


def _dep_and_svc(calls: dict[str, int]) -> tuple[TypeWire[object], TypeWire[str]]:
    def make_dep() -> object:
        calls["dep"] += 1
        return "dep-value"

    def make_svc(*, dep: object) -> str:
        calls["svc"] += 1
        return f"real({dep})"

    dep = type_wire_of(token="t.Dep", creator=make_dep)
    svc = type_wire_of(token="t.Svc", imports={"dep": dep}, create_with=make_svc)
    return dep, svc


def test_one_arg_override_drops_imports() -> None:
    """Pinned: the one-argument form replaces the whole subgraph."""
    calls = {"dep": 0, "svc": 0, "override": 0}
    dep, svc = _dep_and_svc(calls)

    def fake(_ctx: object) -> str:
        calls["override"] += 1
        return "fake"

    container = TypeWireContainer()
    svc.with_creator(fake).apply_sync(container)

    assert svc.get_instance_sync(container) == "fake"
    with pytest.raises(WireNotRegisteredError, match=r"t\.Dep"):
        dep.get_instance_sync(container)
    assert calls == {"dep": 0, "svc": 0, "override": 1}


def test_keep_imports_one_arg_registers_but_does_not_resolve_imports() -> None:
    calls = {"dep": 0, "svc": 0, "override": 0}
    dep, svc = _dep_and_svc(calls)

    def fake(_ctx: object) -> str:
        calls["override"] += 1
        return "fake"

    override = svc.with_creator(fake, keep_imports=True)
    assert set(override.imports) == {"dep"}

    container = TypeWireContainer()
    override.apply_sync(container)

    assert svc.get_instance_sync(container) == "fake"
    assert calls == {"dep": 0, "svc": 0, "override": 1}
    # The import stays registered and resolves on demand.
    assert dep.get_instance_sync(container) == "dep-value"
    assert calls["dep"] == 1


async def test_keep_imports_resolves_imports_only_when_original_called() -> None:
    calls = {"dep": 0, "svc": 0, "override": 0}
    _dep, svc = _dep_and_svc(calls)

    async def skip_original(_ctx: object, original: Callable[[], Awaitable[str]]) -> str:
        calls["override"] += 1
        return "skipped"

    async with TypeWireContainer() as container:
        await svc.with_creator(skip_original, keep_imports=True).apply(container)
        assert await svc.get_instance(container) == "skipped"
    assert calls == {"dep": 0, "svc": 0, "override": 1}


async def test_keep_imports_resolves_imports_when_original_called() -> None:
    calls = {"dep": 0, "svc": 0, "override": 0}
    dep, svc = _dep_and_svc(calls)

    async def wrap_original(_ctx: object, original: Callable[[], Awaitable[str]]) -> str:
        calls["override"] += 1
        return f"wrapped({await original()})"

    async with TypeWireContainer() as container:
        await svc.with_creator(wrap_original, keep_imports=True).apply(container)
        assert await svc.get_instance(container) == "wrapped(real(dep-value))"
        assert calls == {"dep": 1, "svc": 1, "override": 1}
        # The import was resolved through the container, so it is the cached singleton.
        assert await dep.get_instance(container) == "dep-value"
        assert calls["dep"] == 1


async def test_keep_imports_dict_convention_and_simple_wire() -> None:
    dep = type_wire_of(token="Dep", creator=lambda: 42)
    svc = type_wire_of(
        token="Svc", create_with=lambda deps: f"real({deps['dep']})", imports={"dep": dep}
    )
    simple = type_wire_of(token="Simple", creator=lambda: "simple")

    async def spy(_ctx: object, original: Callable[[], Awaitable[object]]) -> str:
        return f"spy({await original()})"

    async with TypeWireContainer() as container:
        await svc.with_creator(spy, keep_imports=True).apply(container)
        await simple.with_creator(spy, keep_imports=True).apply(container)
        assert await svc.get_instance(container) == "spy(real(42))"
        assert await simple.get_instance(container) == "spy(simple)"


async def test_keep_imports_chained_with_two_arg_overrides() -> None:
    calls = {"dep": 0, "svc": 0, "override": 0}
    _dep, svc = _dep_and_svc(calls)

    async def inner(_ctx: object, original: Callable[[], Awaitable[str]]) -> str:
        return f"inner({await original()})"

    async def outer(_ctx: object, original: Callable[[], Awaitable[str]]) -> str:
        return f"outer({await original()})"

    lazy_then_eager = svc.with_creator(inner, keep_imports=True).with_creator(outer)
    eager_then_lazy = svc.with_creator(inner).with_creator(outer, keep_imports=True)

    async with TypeWireContainer() as container:
        await lazy_then_eager.apply(container)
        assert await svc.get_instance(container) == "outer(inner(real(dep-value)))"
    async with TypeWireContainer() as container:
        await eager_then_lazy.apply(container)
        assert await svc.get_instance(container) == "outer(inner(real(dep-value)))"


async def test_keep_imports_transient_scope_preserved() -> None:
    count = 0

    def make() -> int:
        nonlocal count
        count += 1
        return count

    wire = type_wire_of(token="T", creator=make, scope=TRANSIENT)
    override = wire.with_creator(lambda _ctx, original: original(), keep_imports=True)
    assert override.scope == TRANSIENT

    async with TypeWireContainer() as container:
        await override.apply(container)
        assert await wire.get_instance(container) == 1
        assert await wire.get_instance(container) == 2
