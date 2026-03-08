from __future__ import annotations

from typewirepy import TypeWireContainer, type_wire_group_of, type_wire_of

# Simulate module-level wire definitions (like wires.py)
logger_wire = type_wire_of(token="Logger", creator=lambda: ["logger"])
service_wire = type_wire_of(
    token="Service",
    imports={"logger": logger_wire},
    create_with=lambda deps: f"service({deps['logger']})",
)
app_wires = type_wire_group_of([logger_wire, service_wire])


async def test_import_wires_from_module() -> None:
    """Wires defined at module level can be imported and used."""
    async with TypeWireContainer() as container:
        await app_wires.apply(container)
        result = await service_wire.get_instance(container)
        assert result == "service(['logger'])"


async def test_separate_containers_resolve_independently() -> None:
    """Two containers resolve independently from the same wire definitions."""
    async with TypeWireContainer() as c1, TypeWireContainer() as c2:
        await app_wires.apply(c1)
        await app_wires.apply(c2)

        r1 = await logger_wire.get_instance(c1)
        r2 = await logger_wire.get_instance(c2)

        assert r1 == r2 == ["logger"]
        assert r1 is not r2


def test_sync_api_works() -> None:
    """Sync API works for distributed contexts (Spark executors, etc.)."""
    with TypeWireContainer.sync() as container:
        app_wires.apply_sync(container)
        result = service_wire.get_instance_sync(container)
        assert result == "service(['logger'])"
