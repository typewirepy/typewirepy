from __future__ import annotations

import enum


class Scope(enum.Enum):
    """Lifecycle scope for a wire's resolved value."""

    SINGLETON = "singleton"
    TRANSIENT = "transient"
