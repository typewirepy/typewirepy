from __future__ import annotations

import inspect
from typing import Any, Literal


def detect_convention(create_with: Any, import_keys: set[str]) -> Literal["dict", "kwargs"]:
    """Detect whether create_with expects a dict (Convention A) or kwargs (Convention B).

    Convention B: function has keyword-only params (after *) matching import keys.
    Convention A: everything else (lambdas, *args, **kwargs, single dict param).
    """
    try:
        sig = inspect.signature(create_with)
    except (ValueError, TypeError):
        return "dict"

    kw_only = {
        name for name, p in sig.parameters.items() if p.kind == inspect.Parameter.KEYWORD_ONLY
    }

    if kw_only and kw_only == import_keys:
        return "kwargs"

    return "dict"


def detect_creator_arity(fn: Any) -> Literal[1, 2]:
    """Detect whether a with_creator callback takes 1 arg (ctx) or 2 args (ctx, original).

    Returns 1 or 2. Falls back to 1 for uninspectable callables.
    """
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return 1

    params = [
        p
        for p in sig.parameters.values()
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]

    if len(params) >= 2:
        return 2
    return 1
