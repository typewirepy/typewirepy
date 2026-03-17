from __future__ import annotations

import pytest

from typewirepy import SINGLETON, TRANSIENT, Scope, TypeWire, TypeWireContainer, type_wire_of


async def test_wire_creation_with_creator() -> None:
    wire: TypeWire[str] = type_wire_of(token="Greeting", creator=lambda: "hello")
    assert wire.token.label == "Greeting"
    assert wire._scope == SINGLETON
    assert wire._imports == {}


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (SINGLETON, SINGLETON),
        (TRANSIENT, TRANSIENT),
    ],
)
async def test_wire_scope(scope: Scope, expected: Scope) -> None:
    wire = type_wire_of(token="T", creator=lambda: 1, scope=scope)
    assert wire._scope == expected


async def test_wire_apply_and_get_instance() -> None:
    wire: TypeWire[str] = type_wire_of(token="Msg", creator=lambda: "hello")
    async with TypeWireContainer() as container:
        await wire.apply(container)
        result = await wire.get_instance(container)
        assert result == "hello"


@pytest.mark.parametrize(
    "convention",
    ["dict", "kwargs"],
    ids=["convention_a_dict", "convention_b_kwargs"],
)
async def test_wire_conventions(convention: str) -> None:
    logger_wire = type_wire_of(token="Logger", creator=lambda: "logger_instance")

    if convention == "kwargs":

        def create_service(*, logger: str) -> str:
            return f"service({logger})"

        service_wire = type_wire_of(
            token="Service",
            imports={"logger": logger_wire},
            create_with=create_service,
        )
    else:
        service_wire = type_wire_of(
            token="Service",
            imports={"logger": logger_wire},
            create_with=lambda deps: f"service({deps['logger']})",
        )

    async with TypeWireContainer() as container:
        await service_wire.apply(container)
        result = await service_wire.get_instance(container)
        assert result == "service(logger_instance)"


async def test_wire_async_creator() -> None:
    async def make_value() -> int:
        return 42

    wire = type_wire_of(token="Async", creator=make_value)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        assert await wire.get_instance(container) == 42


async def test_with_creator_1_arg() -> None:
    wire = type_wire_of(token="Original", creator=lambda: "original")
    overridden = wire.with_creator(lambda _ctx: "replaced")

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        assert await overridden.get_instance(container) == "replaced"


async def test_with_creator_2_arg() -> None:
    wire = type_wire_of(token="Original", creator=lambda: "original")

    async def spy(ctx: object, original: object) -> str:
        result = await original()  # type: ignore[operator]
        return f"spied({result})"

    overridden = wire.with_creator(spy)

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        assert await overridden.get_instance(container) == "spied(original)"


async def test_with_creator_preserves_token_identity() -> None:
    wire = type_wire_of(token="Svc", creator=lambda: "a")
    overridden = wire.with_creator(lambda _ctx: "b")
    assert wire.token is overridden.token


async def test_token_label() -> None:
    wire = type_wire_of(token="MyService", creator=lambda: "svc")
    assert wire.token_label == "MyService"


async def test_imports_property() -> None:
    dep = type_wire_of(token="Dep", creator=lambda: 1)
    wire = type_wire_of(
        token="Main",
        imports={"dep": dep},
        create_with=lambda deps: deps["dep"],
    )
    imports = wire.imports
    assert imports == {"dep": dep}
    # Mutating the returned dict must not affect the wire
    imports["extra"] = dep
    assert "extra" not in wire.imports


async def test_scope_property() -> None:
    wire_s = type_wire_of(token="S", creator=lambda: 1, scope=SINGLETON)
    wire_t = type_wire_of(token="T", creator=lambda: 1, scope=TRANSIENT)
    assert wire_s.scope == SINGLETON
    assert wire_t.scope == TRANSIENT


async def test_wire_repr_with_imports() -> None:
    dep = type_wire_of(token="Dep", creator=lambda: 1)
    wire = type_wire_of(
        token="Main",
        imports={"dep": dep},
        create_with=lambda deps: deps["dep"],
    )
    assert wire.token.label == "Main"
    assert set(wire._imports.keys()) == {"dep"}
