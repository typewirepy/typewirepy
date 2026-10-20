from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar, cast, overload

_E = TypeVar("_E", bound=Exception)
_BE = TypeVar("_BE", bound=BaseException)


class TypeWireError(Exception):
    """Base exception for all TypeWire errors."""


class CircularDependencyError(TypeWireError):
    """Raised when a circular dependency is detected during resolution."""

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


class NotResolvedError(TypeWireError):
    """Raised when get_cached() is called for a wire not yet resolved."""

    def __init__(self, label: str) -> None:
        self.label = label
        super().__init__(f"Wire not resolved yet: {label!r}")


class CreatorError(TypeWireError):
    """Raised when a creator function fails during resolution.

    Wraps the original exception as __cause__.
    """

    def __init__(self, label: str, cause: Exception) -> None:
        self.label = label
        super().__init__(f"Creator failed for wire {label!r}: {cause}")
        self.__cause__ = cause


class TeardownError(ExceptionGroup[Exception], TypeWireError):
    """Raised by teardown when one or more cleanups failed.

    An :class:`ExceptionGroup` carrying every cleanup exception, in the order the
    cleanups ran (reverse creation order). Each carries a note naming the wire whose
    cleanup raised it. The message names the first failing wire and its exception
    type; the exception messages themselves are only in ``exceptions``. Being a
    :class:`TypeWireError` too, it is caught by ``except TypeWireError``; being an
    exception group, it works with ``except*``. :meth:`split`, :meth:`subgroup` and
    ``except*`` produce ``TeardownError`` instances, not plain ``ExceptionGroup``.
    """

    @overload
    def derive(self, excs: Sequence[_E], /) -> ExceptionGroup[_E]: ...

    @overload
    def derive(self, excs: Sequence[_BE], /) -> BaseExceptionGroup[_BE]: ...

    def derive(self, excs: Sequence[BaseException], /) -> BaseExceptionGroup[BaseException]:
        # Same overloads as the stdlib, but the derived group is a TeardownError.
        # split()/subgroup() only pass subsets of self.exceptions, which are Exceptions.
        return TeardownError(self.message, cast("Sequence[Exception]", excs))
