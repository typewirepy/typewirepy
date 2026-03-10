from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from typewirepy import TypeWireContainer, type_wire_group_of, type_wire_of
from typewirepy.errors import WireNotRegisteredError
from typewirepy.integrations.fastapi import WireDepends

logger_wire = type_wire_of(token="Logger", creator=lambda: "test_logger")
service_wire = type_wire_of(
    token="Service",
    imports={"logger": logger_wire},
    create_with=lambda deps: f"service({deps['logger']})",
)
app_wires = type_wire_group_of([logger_wire, service_wire])


async def test_basic_endpoint_with_wire_depends() -> None:
    """WireDepends resolves a wire via app.state.typewire_container."""
    app = FastAPI()

    @app.get("/service")
    async def get_service(svc: str = WireDepends(service_wire)) -> dict[str, str]:
        return {"service": svc}

    container = TypeWireContainer()
    await app_wires.apply(container)
    app.state.typewire_container = container

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/service")
        assert response.status_code == 200
        assert response.json() == {"service": "service(test_logger)"}

    await container.teardown()


async def test_container_swap_for_testing() -> None:
    """Override app.state.typewire_container with a test container."""
    app = FastAPI()

    @app.get("/service")
    async def get_service(svc: str = WireDepends(service_wire)) -> dict[str, str]:
        return {"service": svc}

    # Set up prod container
    prod_container = TypeWireContainer()
    await app_wires.apply(prod_container)
    app.state.typewire_container = prod_container

    # Override with test container
    test_container = TypeWireContainer()
    test_wires = app_wires.with_extra_wires(
        [service_wire.with_creator(lambda _ctx: "mock_service")]
    )
    await test_wires.apply(test_container)
    app.state.typewire_container = test_container

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/service")
        assert response.status_code == 200
        assert response.json() == {"service": "mock_service"}

    await prod_container.teardown()
    await test_container.teardown()


async def test_multiple_wires_in_one_endpoint() -> None:
    """Multiple WireDepends parameters in a single endpoint signature."""
    app = FastAPI()

    @app.get("/multi")
    async def get_multi(
        logger: str = WireDepends(logger_wire),
        svc: str = WireDepends(service_wire),
    ) -> dict[str, str]:
        return {"logger": logger, "service": svc}

    container = TypeWireContainer()
    await app_wires.apply(container)
    app.state.typewire_container = container

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/multi")
        assert response.status_code == 200
        data = response.json()
        assert data["logger"] == "test_logger"
        assert data["service"] == "service(test_logger)"

    await container.teardown()


async def test_container_not_set_raises_error() -> None:
    """When no container is on app.state, WireDepends raises RuntimeError."""
    app = FastAPI()

    @app.get("/service")
    async def get_service(svc: str = WireDepends(service_wire)) -> dict[str, str]:
        return {"service": svc}

    with pytest.raises(RuntimeError, match="No TypeWireContainer"):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            await client.get("/service")


async def test_wire_not_applied_propagates_error() -> None:
    """When the container exists but wire was never applied, WireNotRegisteredError propagates."""
    app = FastAPI()

    @app.get("/service")
    async def get_service(svc: str = WireDepends(service_wire)) -> dict[str, str]:
        return {"service": svc}

    # Container exists but no wires applied
    app.state.typewire_container = TypeWireContainer()

    with pytest.raises(WireNotRegisteredError):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            await client.get("/service")
