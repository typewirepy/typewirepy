from __future__ import annotations

from typewirepy import Scope, TypeWire, TypeWireContainer, type_wire_of


async def test_wire_creation_with_creator() -> None:
    wire: TypeWire[str] = type_wire_of(token="Greeting", creator=lambda: "hello")
    assert repr(wire) == "TypeWire(token='Greeting', scope=Scope.SINGLETON, imports=set())"


async def test_wire_scope_transient() -> None:
    wire = type_wire_of(token="T", creator=lambda: 1, scope=Scope.TRANSIENT)
    assert "Scope.TRANSIENT" in repr(wire)


async def test_wire_apply_and_get_instance() -> None:
    wire: TypeWire[str] = type_wire_of(token="Msg", creator=lambda: "hello")
    async with TypeWireContainer() as container:
        await wire.apply(container)
        result = await wire.get_instance(container)
        assert result == "hello"


async def test_wire_convention_a_dict() -> None:
    logger_wire = type_wire_of(token="Logger", creator=lambda: "logger_instance")
    service_wire = type_wire_of(
        token="Service",
        imports={"logger": logger_wire},
        create_with=lambda deps: f"service({deps['logger']})",
    )

    async with TypeWireContainer() as container:
        await service_wire.apply(container)
        result = await service_wire.get_instance(container)
        assert result == "service(logger_instance)"


async def test_wire_convention_b_kwargs() -> None:
    logger_wire = type_wire_of(token="Logger", creator=lambda: "logger_instance")

    def create_service(*, logger: str) -> str:
        return f"service({logger})"

    service_wire = type_wire_of(
        token="Service",
        imports={"logger": logger_wire},
        create_with=create_service,
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
    assert wire._token is overridden._token


async def test_wire_repr_with_imports() -> None:
    dep = type_wire_of(token="Dep", creator=lambda: 1)
    wire = type_wire_of(
        token="Main",
        imports={"dep": dep},
        create_with=lambda deps: deps["dep"],
    )
    assert "imports={'dep'}" in repr(wire)
