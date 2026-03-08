from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, TypeVar, overload

if TYPE_CHECKING:
    from collections.abc import Callable

from typewirepy._introspect import detect_convention
from typewirepy._token import _WireToken
from typewirepy.errors import TypeWireError
from typewirepy.group import TypeWireGroup
from typewirepy.scope import Scope
from typewirepy.wire import TypeWire

T = TypeVar("T")


@overload
def type_wire_of(
    *,
    token: str,
    creator: Callable[[], T],
    scope: Scope = ...,
) -> TypeWire[T]: ...


@overload
def type_wire_of(
    *,
    token: str,
    create_with: Callable[..., T],
    imports: dict[str, TypeWire[Any]],
    scope: Scope = ...,
) -> TypeWire[T]: ...


def type_wire_of(
    *,
    token: str,
    creator: Callable[..., Any] | None = None,
    create_with: Callable[..., Any] | None = None,
    imports: dict[str, TypeWire[Any]] | None = None,
    scope: Scope = Scope.SINGLETON,
) -> TypeWire[Any]:
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
        import_keys = set(resolved_imports.keys())

        # Check for Convention B misalignment: if create_with has keyword-only
        # params, they must match import keys exactly
        try:
            sig = inspect.signature(create_with)
        except (ValueError, TypeError):
            sig = None

        if sig is not None:
            kw_only = {
                name
                for name, p in sig.parameters.items()
                if p.kind == inspect.Parameter.KEYWORD_ONLY
            }
            if kw_only and kw_only != import_keys:
                raise TypeWireError(
                    f"Convention B mismatch: create_with params {kw_only} "
                    f"!= import keys {import_keys}"
                )

        convention = detect_convention(create_with, import_keys)

    wire_token = _WireToken(token)

    return TypeWire(
        token=wire_token,
        creator=creator,
        create_with=create_with,
        imports=resolved_imports,
        scope=scope,
        convention=convention,
    )


def type_wire_group_of(wires: list[TypeWire[Any]]) -> TypeWireGroup:
    return TypeWireGroup(wires)
