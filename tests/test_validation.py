from __future__ import annotations

import pytest

from typewirepy import TypeWireError, type_wire_of


def test_both_creator_and_create_with_raises() -> None:
    with pytest.raises(TypeWireError, match="Cannot specify both"):
        type_wire_of(
            token="Bad",
            creator=lambda: 1,
            create_with=lambda deps: 1,  # type: ignore[call-overload]
            imports={"x": type_wire_of(token="X", creator=lambda: 1)},
        )


def test_neither_creator_nor_create_with_raises() -> None:
    with pytest.raises(TypeWireError, match="Must specify either"):
        type_wire_of(token="Bad")  # type: ignore[call-overload]


def test_imports_without_create_with_raises() -> None:
    with pytest.raises(TypeWireError, match="'imports' requires 'create_with'"):
        type_wire_of(
            token="Bad",
            imports={"x": type_wire_of(token="X", creator=lambda: 1)},  # type: ignore[call-overload]
        )


def test_create_with_without_imports_raises() -> None:
    with pytest.raises(TypeWireError, match="'create_with' requires 'imports'"):
        type_wire_of(
            token="Bad",
            create_with=lambda deps: 1,  # type: ignore[call-overload]
        )


def test_convention_b_misalignment_raises() -> None:
    dep = type_wire_of(token="Logger", creator=lambda: "logger")

    def create_service(*, db: str) -> str:
        return db

    with pytest.raises(TypeWireError, match="Convention B mismatch"):
        type_wire_of(
            token="Service",
            imports={"logger": dep},
            create_with=create_service,
        )
