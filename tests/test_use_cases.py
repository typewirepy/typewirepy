"""Scenario-driven tests that mirror real-world usage patterns."""

from __future__ import annotations

from typing import Any

from typewirepy import TRANSIENT, TypeWireContainer, type_wire_group_of, type_wire_of


async def test_app_bootstrap_multi_layer() -> None:
    """Config -> Database -> UserService, applied and resolved via container."""
    config_wire = type_wire_of(token="Config", creator=lambda: {"db_url": "sqlite://"})

    db_wire = type_wire_of(
        token="Database",
        imports={"config": config_wire},
        create_with=lambda deps: f"db({deps['config']['db_url']})",
    )

    user_service_wire = type_wire_of(
        token="UserService",
        imports={"db": db_wire},
        create_with=lambda deps: f"user_svc({deps['db']})",
    )

    group = type_wire_group_of([config_wire, db_wire, user_service_wire])

    async with TypeWireContainer() as container:
        await group.apply(container)

        config = await config_wire.get_instance(container)
        assert config == {"db_url": "sqlite://"}

        db = await db_wire.get_instance(container)
        assert db == "db(sqlite://)"

        user_svc = await user_service_wire.get_instance(container)
        assert user_svc == "user_svc(db(sqlite://))"


async def test_diamond_dependency() -> None:
    """A imports B and C; both B and C import D. D should be resolved once (singleton)."""
    call_count = 0

    def make_d() -> str:
        nonlocal call_count
        call_count += 1
        return "D"

    d_wire = type_wire_of(token="D", creator=make_d)
    b_wire = type_wire_of(
        token="B",
        imports={"d": d_wire},
        create_with=lambda deps: f"B({deps['d']})",
    )
    c_wire = type_wire_of(
        token="C",
        imports={"d": d_wire},
        create_with=lambda deps: f"C({deps['d']})",
    )
    a_wire = type_wire_of(
        token="A",
        imports={"b": b_wire, "c": c_wire},
        create_with=lambda deps: f"A({deps['b']}, {deps['c']})",
    )

    async with TypeWireContainer() as container:
        await a_wire.apply(container)

        result = await a_wire.get_instance(container)
        assert result == "A(B(D), C(D))"
        # D is singleton — factory called only once
        assert call_count == 1


async def test_override_for_testing() -> None:
    """Wire with with_creator() swaps a real service with a mock."""
    real_wire = type_wire_of(token="Service", creator=lambda: "real_service")
    mock_wire = real_wire.with_creator(lambda _ctx: "mock_service")

    async with TypeWireContainer() as container:
        await mock_wire.apply(container)
        assert await mock_wire.get_instance(container) == "mock_service"


async def test_override_wire_with_imports() -> None:
    """with_creator() on a wire that originally had imports."""
    dep = type_wire_of(token="Dep", creator=lambda: "dep_value")
    service = type_wire_of(
        token="Service",
        imports={"dep": dep},
        create_with=lambda deps: f"real({deps['dep']})",
    )

    overridden = service.with_creator(lambda _ctx: "stubbed")

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        assert await overridden.get_instance(container) == "stubbed"


async def test_transient_singleton_interaction() -> None:
    """Transient wire depending on a singleton; singleton shared, transient fresh."""
    singleton_wire = type_wire_of(token="Shared", creator=lambda: {"id": 1})

    call_count = 0

    def make_transient(deps: dict[str, Any]) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return {"shared": deps["shared"], "call": call_count}

    transient_wire = type_wire_of(
        token="Transient",
        imports={"shared": singleton_wire},
        create_with=make_transient,
        scope=TRANSIENT,
    )

    async with TypeWireContainer() as container:
        await transient_wire.apply(container)

        t1 = await transient_wire.get_instance(container)
        t2 = await transient_wire.get_instance(container)

        # Shared singleton is the same object
        assert t1["shared"] is t2["shared"]
        # Transient yields distinct instances
        assert t1["call"] == 1
        assert t2["call"] == 2
        assert t1 is not t2


async def test_cleanup_on_shutdown_reverse_order() -> None:
    """Generator-based resources are cleaned up in reverse registration order."""
    order: list[str] = []

    def make_db() -> Any:
        yield "db_conn"
        order.append("db_closed")

    def make_cache() -> Any:
        yield "cache_conn"
        order.append("cache_closed")

    db_wire = type_wire_of(token="DB", creator=make_db)
    cache_wire = type_wire_of(token="Cache", creator=make_cache)

    async with TypeWireContainer() as container:
        await db_wire.apply(container)
        await cache_wire.apply(container)
        await db_wire.get_instance(container)
        await cache_wire.get_instance(container)

    # Cache was resolved after DB, so it should be cleaned up first
    assert order == ["cache_closed", "db_closed"]


async def test_teardown_idempotent() -> None:
    """Calling teardown() twice should not raise."""
    cleanup_count = 0

    def make_resource() -> Any:
        nonlocal cleanup_count
        yield "resource"
        cleanup_count += 1

    wire = type_wire_of(token="Res", creator=make_resource)
    container = TypeWireContainer()
    await wire.apply(container)
    await wire.get_instance(container)

    await container.teardown()
    await container.teardown()  # Should not raise

    assert cleanup_count == 1
