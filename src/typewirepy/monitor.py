from __future__ import annotations

from typing import Protocol, runtime_checkable

from typewirepy.errors import CircularDependencyError
from typewirepy.token import WireToken


@runtime_checkable
class ResolutionMonitor(Protocol):
    """Monitors dependency resolution (e.g., circular dependency detection)."""

    def enter(self, token: WireToken[object]) -> None:
        """Called before resolving a token. Raise to abort."""
        ...

    def exit(self, token: WireToken[object]) -> None:
        """Called after resolving a token."""
        ...


class CircularDependencyMonitor:
    """Default monitor: detects circular dependencies via path tracking."""

    def __init__(self) -> None:
        self._path: list[WireToken[object]] = []
        self._seen: set[WireToken[object]] = set()

    def enter(self, token: WireToken[object]) -> None:
        self._path.append(token)
        if token in self._seen:
            labels = [t.label for t in self._path]
            raise CircularDependencyError(labels)
        self._seen.add(token)

    def exit(self, token: WireToken[object]) -> None:
        self._seen.discard(token)
        self._path.pop()
