from __future__ import annotations


class _WireToken:
    """Internal unique identity. Equivalent to Symbol(label) in JavaScript."""

    __slots__ = ("label",)

    def __init__(self, label: str) -> None:
        self.label = label

    def __repr__(self) -> str:
        return f"WireToken({self.label!r})"
