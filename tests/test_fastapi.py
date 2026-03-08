from __future__ import annotations

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from typewirepy import TypeWireContainer, type_wire_group_of, type_wire_of
from typewirepy.integrations.fastapi import wire_depends

logger_wire = type_wire_of(token="Logger", creator=lambda: "test_logger")
service_wire = type_wire_of(
    token="Service",
    imports={"logger": logger_wire},
    create_with=lambda deps: f"service({deps['logger']})",
)
app_wires = type_wire_group_of([logger_wire, service_wire])


async def test_wire_depends_resolves() -> None:
    container = TypeWireContainer()
    await app_wires.apply(container)

    resolver = wire_depends(service_wire, lambda: container)
    result = await resolver()
    assert result == "service(test_logger)"

    await container.teardown()


async def test_full_app_with_lifespan() -> None:
    container = TypeWireContainer()
    await app_wires.apply(container)

    def get_container() -> TypeWireContainer:
        return container

    app = FastAPI()

    @app.get("/service")
    async def get_service(
        svc: str = Depends(wire_depends(service_wire, get_container)),
    ) -> dict[str, str]:
        return {"service": svc}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/service")
        assert response.status_code == 200
        assert response.json() == {"service": "service(test_logger)"}

    await container.teardown()


async def test_container_swap_for_testing() -> None:
    prod_container = TypeWireContainer()
    await app_wires.apply(prod_container)

    test_container = TypeWireContainer()
    test_wires = app_wires.with_extra_wires(
        [
            service_wire.with_creator(lambda _ctx: "mock_service"),
        ]
    )
    await test_wires.apply(test_container)

    current_container = prod_container

    def get_container() -> TypeWireContainer:
        return current_container

    app = FastAPI()

    @app.get("/service")
    async def get_service(
        svc: str = Depends(wire_depends(service_wire, get_container)),
    ) -> dict[str, str]:
        return {"service": svc}

    # Swap to test container
    current_container = test_container

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/service")
        assert response.status_code == 200
        assert response.json() == {"service": "mock_service"}

    await prod_container.teardown()
    await test_container.teardown()
