# Best Practices

These are recommended conventions for structuring typewirepy projects. They are
not enforced by the library but reflect patterns that keep dependency graphs
readable, type-safe, and maintainable.

## 1. Keep Wires Public

Wire instances are **public type accessors** — other modules import them to
declare dependencies via `imports={"name": wire}`. Always use public
module-level names:

```python
# ✓ Public — other modules can import and depend on this wire
db_wire = type_wire_of(token="DB", creator=lambda: Database())

# ✗ Private — defeats the purpose of wires as shared dependency contracts
_db_wire = type_wire_of(token="DB", creator=lambda: Database())
```

If a dependency is truly internal to a single module, **don't create a wire at
all** — use a plain instance instead:

```python
# ✗ Unnecessary wire for an internal-only dependency
_retry_policy_wire = type_wire_of(
    token="RetryPolicy",
    creator=lambda: RetryPolicy(max_retries=3),
)
service_wire = type_wire_of(
    token="Service",
    imports={"retry": _retry_policy_wire},
    create_with=create_service,
)

# ✓ Internal dependency as a plain instance — no wire needed
_retry_policy = RetryPolicy(max_retries=3)
service_wire = type_wire_of(
    token="Service",
    creator=lambda: Service(retry=_retry_policy),
)
```

A wire earns its existence when something external needs to reference, override,
or manage its lifecycle. If none of those apply, it's unnecessary indirection.

## 2. Choosing a Creator Pattern

When deciding how to create instances, prefer the pattern that provides the most
decoupling. Listed from most to least recommended:

### Standalone factory function (preferred)

Maximum decoupling — the return type can be a Protocol, so the wire layer never
needs to know the concrete type. The factory lives in `service.py` alongside
the implementation.

```python
# service.py
from auth.types import AuthServiceProtocol

def create_auth_service(*, db: Database) -> AuthServiceProtocol:
    return AuthServiceImpl(db)

# wires.py
from auth.service import create_auth_service

auth_service_wire = type_wire_of(
    token="AuthService",
    imports={"db": db_wire},
    create_with=create_auth_service,
)
```

### Classmethod / staticmethod factory

Good when the concrete class is part of the public API but construction logic
should be encapsulated.

```python
# service.py
class Database:
    @classmethod
    def from_config(cls, *, config: Config) -> Database:
        return cls(config.db_url, pool_size=config.pool_size)

# wires.py
db_wire = type_wire_of(
    token="DB",
    imports={"config": config_wire},
    create_with=Database.from_config,
)
```

### Constructor directly

Acceptable for simple value types, but be aware that this couples the wire layer
to the concrete class and its `__init__` signature. Import keys must match
constructor parameter names exactly — renaming a parameter silently breaks the
wire.

```python
class AppConfig:
    def __init__(self, *, db_url: str, debug: bool) -> None:
        self.db_url = db_url
        self.debug = debug

config_wire = type_wire_of(
    token="Config",
    imports={"db_url": db_url_wire, "debug": debug_wire},
    create_with=AppConfig,
)
```

### Lambda for leaf wires

Only for trivial leaf wires with zero dependencies — config literals, simple
constructors, or constants.

```python
config_wire = type_wire_of(token="Config", creator=lambda: Config(env="prod"))
greeting_wire = type_wire_of(token="Greeting", creator=lambda: "hello")
```

## 3. Use Keyword-Only Parameters with Type Annotations

For `create_with` functions, use keyword-only parameters (after `*`) with type
annotations. This is idiomatic Python
([PEP 3102](https://peps.python.org/pep-3102/)) and enables typewirepy's
Convention B detection for clean dependency resolution.

```python
# ✓ Keyword-only, typed — enables Convention B, full IDE and type-checker support
def create_service(*, db: Database, config: Config) -> Service:
    return Service(db, config)

# ✗ **kwargs — falls back to Convention A, loses all type information
def create_service(**kwargs) -> Service:
    return Service(kwargs["db"], kwargs["config"])

# ✗ Dict parameter — loses individual key types
def create_service(deps: dict[str, Any]) -> Service:
    return Service(deps["db"], deps["config"])
```

Why keyword-only parameters are preferred:

- **Type safety** — each parameter carries its own type annotation
- **IDE support** — autocomplete and inline documentation work correctly
- **Convention B** — typewirepy detects keyword-only params and calls
  `create_with(**resolved)` directly, avoiding dict indirection
- **Refactoring** — renaming or removing a parameter is caught by type checkers

## 4. File Organization

### Recommended: Separate wires from implementations

```
auth/
  __init__.py
  service.py      # AuthService class, protocols, types, factory functions
  wires.py        # Wire declarations only
```

- **`service.py`** contains the implementation: classes, protocols, types, and
  factory functions. This follows Python community norms — types and protocols
  live alongside the code that implements them (as in FastAPI, Pydantic, and
  SQLAlchemy).
- **`wires.py`** is a thin file that imports from `service.py` and declares
  wires. It is the public surface of the module — other modules import wires
  from here to declare their own dependencies.

Example:

```python
# auth/service.py
from dataclasses import dataclass

class AuthServiceProtocol:
    def authenticate(self, token: str) -> bool: ...

@dataclass
class AuthServiceImpl:
    db: Database

    def authenticate(self, token: str) -> bool:
        return self.db.check_token(token)

def create_auth_service(*, db: Database) -> AuthServiceProtocol:
    return AuthServiceImpl(db)
```

```python
# auth/wires.py
from typewirepy import type_wire_of

from auth.service import create_auth_service
from infra.wires import db_wire

auth_service_wire = type_wire_of(
    token="AuthService",
    imports={"db": db_wire},
    create_with=create_auth_service,
)
```

### Alternative: Further type separation

For teams that prefer stricter separation (more common in TypeScript, Java, or
Go projects):

```
auth/
  __init__.py
  types.py        # Protocols, ABCs, type aliases
  service.py      # Implementation (imports types)
  wires.py        # Wire declarations (imports service + types)
```

The dependency flow is strictly one-directional:
`types.py` ← `service.py` ← `wires.py`. This can help in large codebases where
circular imports become a concern, but is less idiomatic Python for most
projects.

## Summary

| Topic | Recommended | Avoid |
|---|---|---|
| Wire naming | `db_wire = type_wire_of(...)` | `_db_wire = type_wire_of(...)` |
| Internal dependencies | `_policy = RetryPolicy(...)` | `_policy_wire = type_wire_of(...)` |
| `create_with` creator | Factory function with typed `*` args | Untyped lambda or `**kwargs` |
| Leaf creators | `creator=lambda: Config(...)` | Overkill named function |
| Creator preference | Factory fn → classmethod → constructor | Constructor as default |
| File layout | `service.py` + `wires.py` | Everything in one file |
