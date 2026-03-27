from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from typewirepy import TypeWire, TypeWireContainer, type_wire_of


@pytest.fixture
async def container() -> AsyncGenerator[TypeWireContainer, None]:
    async with TypeWireContainer() as c:
        yield c


@pytest.fixture
def simple_wire() -> TypeWire[str]:
    return type_wire_of(token="Simple", creator=lambda: "simple_value")


@pytest.fixture
def wire_with_deps() -> tuple[TypeWire[str], TypeWire[str]]:
    dep = type_wire_of(token="Dep", creator=lambda: "dep_value")
    main: TypeWire[str] = type_wire_of(
        token="Main",
        imports={"dep": dep},
        create_with=lambda deps: f"main({deps['dep']})",
    )
    return dep, main
