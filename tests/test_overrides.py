from __future__ import annotations

from typewirepy import TypeWireContainer, type_wire_group_of, type_wire_of
from typewirepy._introspect import detect_creator_arity


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


async def test_with_creator_2_arg_on_wire_with_imports_dict() -> None:
    dep_wire = type_wire_of(token="Dep", creator=lambda: 42)
    wire = type_wire_of(
        token="Svc",
        create_with=lambda deps: f"value={deps['dep']}",
        imports={"dep": dep_wire},
    )

    async def spy(ctx: object, original: object) -> str:
        val = await original()  # type: ignore[operator]
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

    async def spy(ctx: object, original: object) -> str:
        val = await original()  # type: ignore[operator]
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

    async def layer1(ctx: object, original: object) -> int:
        val = await original()  # type: ignore[operator]
        return val + 100  # type: ignore[operator]

    async def layer2(ctx: object, original: object) -> str:
        val = await original()  # type: ignore[operator]
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

    async def spy(ctx: object, original: object) -> str:
        val = await original()  # type: ignore[operator]
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
