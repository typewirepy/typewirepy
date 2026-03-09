from __future__ import annotations

from typing import Generic, TypeVar

T_co = TypeVar("T_co", covariant=True)


class _WireToken(Generic[T_co]):
    """Internal unique identity. Equivalent to Symbol(label) in JavaScript."""

    __slots__ = ("label",)

    def __init__(self, label: str) -> None:
        self.label = label

    def __repr__(self) -> str:
        return f"WireToken({self.label!r})"
