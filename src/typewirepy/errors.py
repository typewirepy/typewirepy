from __future__ import annotations


class TypeWireError(Exception):
    """Base exception for all TypeWire errors."""


class CircularDependencyError(TypeWireError):
    """Raised when a circular dependency is detected during apply()."""

    def __init__(self, path: list[str]) -> None:
        self.path = path
        cycle = " -> ".join(path)
        super().__init__(f"Circular dependency: {cycle}")


class WireNotRegisteredError(TypeWireError):
    """Raised when get_instance() is called for a wire not yet applied."""

    def __init__(self, label: str) -> None:
        self.label = label
        super().__init__(f"Wire not registered: {label!r}")


class DuplicateWireError(TypeWireError):
    """Raised when apply() encounters a duplicate token registration."""

    def __init__(self, label: str) -> None:
        self.label = label
        super().__init__(f"Duplicate wire: {label!r}")


class CreatorError(TypeWireError):
    """Raised when a creator function fails during resolution.

    Wraps the original exception as __cause__.
    """

    def __init__(self, label: str, cause: Exception) -> None:
        self.label = label
        super().__init__(f"Creator failed for wire {label!r}: {cause}")
        self.__cause__ = cause
