from __future__ import annotations

import enum


class Scope(enum.Enum):
    SINGLETON = "singleton"
    TRANSIENT = "transient"
