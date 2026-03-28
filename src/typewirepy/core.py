from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, overload

from typewirepy._introspect import detect_convention
from typewirepy.errors import TypeWireError
from typewirepy.group import TypeWireGroup
from typewirepy.scope import SINGLETON, Scope
from typewirepy.token import WireToken
from typewirepy.wire import TypeWire

T = TypeVar("T")


@overload
def type_wire_of(
    *,
    token: str,
    creator: Callable[[], T | Awaitable[T]],
    scope: Scope = ...,
) -> TypeWire[T]: ...


@overload
def type_wire_of(
    *,
    token: str,
    create_with: Callable[..., T | Awaitable[T]],
    imports: dict[str, TypeWire[Any]],
    scope: Scope = ...,
) -> TypeWire[T]: ...


def type_wire_of(
    *,
    token: str,
    creator: Callable[..., Any] | None = None,
    create_with: Callable[..., Any] | None = None,
    imports: dict[str, TypeWire[Any]] | None = None,
    scope: Scope = SINGLETON,
) -> TypeWire[Any]:
    """Create a new wire.

    Use *creator* for simple (zero-dependency) wires or *create_with* + *imports*
    for composed ones.

    Examples::

        # Simple wire — no dependencies
        config_wire = type_wire_of(token="Config", creator=lambda: Config())

        # Composed wire — depends on other wires
        svc_wire = type_wire_of(
            token="Service",
            imports={"config": config_wire},
            create_with=lambda *, config: Service(config),
        )
    """
    if creator is not None and create_with is not None:
        raise TypeWireError("Cannot specify both 'creator' and 'create_with'")

    if imports is not None and create_with is None:
        raise TypeWireError("'imports' requires 'create_with'")

    if create_with is not None and imports is None:
        raise TypeWireError("'create_with' requires 'imports'")

    if creator is None and create_with is None:
        raise TypeWireError("Must specify either 'creator' or 'create_with'")

    resolved_imports: dict[str, TypeWire[Any]] = imports or {}

    convention = "dict"
    if create_with is not None:
        convention = detect_convention(create_with, set(resolved_imports.keys()), strict=True)

    wire_token: WireToken[Any] = WireToken(token)

    return TypeWire(
        token=wire_token,
        creator=creator,
        create_with=create_with,
        imports=resolved_imports,
        scope=scope,
        convention=convention,
    )


def type_wire_group_of(wires: list[TypeWire[Any]]) -> TypeWireGroup:
    """Create an immutable group from a list of wires."""
    return TypeWireGroup(wires)


def combine_wire_groups(groups: list[TypeWireGroup]) -> TypeWireGroup:
    """Flatten multiple groups into a single group."""
    wires: list[TypeWire[Any]] = []
    for group in groups:
        wires.extend(group.wires)
    return TypeWireGroup(wires)
