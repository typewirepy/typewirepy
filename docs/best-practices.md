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

### Lambda for simple wires

Only for trivial simple wires with zero dependencies — config literals,
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

## 5. Named Dependencies

Sometimes you need multiple instances of the same type distinguished by a string
name — database connections for "primary", "analytics", and "readonly", cache
clients per region, or API clients per upstream service. Spring-style DI solves
this with `@Named("name")`. In Typewire, there are several user-space patterns
to achieve the same result.

The approaches below are ordered by complexity, not preference — each fits a
different situation. See the comparison table in
[Choosing an Approach](#choosing-an-approach) to pick the right one for your use
case.

### Approach A: Separate Wires per Name

The most explicit approach — declare a distinct wire for each named variant.

```python
# db/service.py
from dataclasses import dataclass


@dataclass
class DbConfig:
    urls: dict[str, str]


@dataclass
class Database:
    url: str


def create_primary_db(*, config: DbConfig) -> Database:
    return Database(url=config.urls["primary"])


def create_analytics_db(*, config: DbConfig) -> Database:
    return Database(url=config.urls["analytics"])
```

```python
# db/wires.py
from typewirepy import type_wire_of

from db.service import DbConfig, create_analytics_db, create_primary_db

config_wire = type_wire_of(
    token="DbConfig",
    creator=lambda: DbConfig(urls={
        "primary": "postgres://primary:5432/app",
        "analytics": "postgres://analytics:5432/warehouse",
    }),
)

primary_db_wire = type_wire_of(
    token="PrimaryDB",
    imports={"config": config_wire},
    create_with=create_primary_db,
)

analytics_db_wire = type_wire_of(
    token="AnalyticsDB",
    imports={"config": config_wire},
    create_with=create_analytics_db,
)
```

**Pros:**

- Full type safety — each wire has its own token and type
- IDE discoverability — autocomplete shows all available variants
- Follows Typewire's declarative model exactly
- Each wire participates in the dependency graph (circular dependency detection,
  teardown)

**Cons:**

- Doesn't scale when the set of names is large or dynamic (config-driven)
- Repetitive boilerplate for many variants
- Adding a new name requires a code change (new wire declaration)

**Best for:** Fixed, small set of variants known at declaration time.

### Approach B: Pre-populated Dictionary Wire

A single wire whose factory builds a `dict[str, T]` from configuration upfront.

```python
# db/service.py
from dataclasses import dataclass


@dataclass
class DbConfig:
    urls: dict[str, str]


@dataclass
class Database:
    url: str


def create_db_map(*, config: DbConfig) -> dict[str, Database]:
    return {name: Database(url=url) for name, url in config.urls.items()}
```

```python
# db/wires.py
from typewirepy import type_wire_of

from db.service import DbConfig, create_db_map

config_wire = type_wire_of(
    token="DbConfig",
    creator=lambda: DbConfig(urls={
        "primary": "postgres://primary:5432/app",
        "analytics": "postgres://analytics:5432/warehouse",
        "readonly": "postgres://readonly:5432/app",
    }),
)

db_map_wire = type_wire_of(
    token="DbMap",
    imports={"config": config_wire},
    create_with=create_db_map,
)
```

Consumer usage:

```python
def create_report_service(*, db_map: dict[str, Database]) -> ReportService:
    analytics_db = db_map["analytics"]
    return ReportService(analytics_db)
```

**Pros:**

- Simple — just a dict, no extra classes
- All instances created eagerly, so errors surface early at startup
- Easy to inspect and debug (it's just a dict)

**Cons:**

- Eager creation — all named instances are created even if unused
- No async support in the dict lookup itself (creation happens in the factory)
- No lazy or on-demand creation of new names after initialization

**Best for:** Config-driven set of names where eager creation is acceptable.

### Approach C: NamedProvider with Lazy Cache

A user-space class that wraps a factory callable and caches instances by name on
first access. This is a class you copy into your project and adapt — it is not a
library export.

```python
# shared/named_provider.py
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Generic, TypeVar, cast

T = TypeVar("T")


class NamedProvider(Generic[T]):
    """Caches named instances created by a factory function."""

    def __init__(
        self,
        factory: Callable[[str], T | Awaitable[T]],
        known_names: Sequence[str] | None = None,
    ) -> None:
        self._factory = factory
        self._cache: dict[str, T] = {}
        self._known_names = set(known_names) if known_names is not None else None

    async def get_or_create(self, name: str) -> T:
        """Return the cached instance for *name*, creating it on first access."""
        if self._known_names is not None and name not in self._known_names:
            raise KeyError(
                f"Unknown name {name!r}. Available: {sorted(self._known_names)}"
            )
        if name not in self._cache:
            result = self._factory(name)
            instance = await result if inspect.isawaitable(result) else result
            self._cache[name] = cast("T", instance)
        return self._cache[name]

    async def warm_up(self, names: Sequence[str]) -> None:
        """Pre-create instances for known names. Fails fast on errors."""
        for name in names:
            await self.get_or_create(name)

    async def close_all(self) -> None:
        """Close all cached instances (requires instances to have a close method)."""
        for instance in self._cache.values():
            close = getattr(instance, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
        self._cache.clear()
```

Wiring:

```python
# db/service.py
from dataclasses import dataclass


@dataclass
class DbConfig:
    urls: dict[str, str]
    required: list[str]  # names to validate at startup


@dataclass
class Database:
    name: str
    url: str

    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def ping(self) -> None: ...


async def connect_database(name: str, url: str) -> Database:
    db = Database(name=name, url=url)
    await db.connect()
    return db
```

```python
# db/wires.py
from typewirepy import type_wire_of

from db.service import DbConfig, connect_database
from shared.named_provider import NamedProvider


async def create_db_provider(*, config: DbConfig):
    async def db_factory(name: str) -> Database:
        return await connect_database(name, config.urls[name])

    provider = NamedProvider(
        db_factory,
        known_names=list(config.urls.keys()),
    )
    await provider.warm_up(config.required)
    yield provider
    await provider.close_all()


config_wire = type_wire_of(
    token="DbConfig",
    creator=lambda: DbConfig(
        urls={
            "primary": "postgres://primary:5432/app",
            "analytics": "postgres://analytics:5432/warehouse",
            "readonly": "postgres://readonly:5432/app",
        },
        required=["primary"],
    ),
)

db_provider_wire = type_wire_of(
    token="DbProvider",
    imports={"config": config_wire},
    create_with=create_db_provider,
)
```

Consumer usage:

```python
# reporting/service.py
from shared.named_provider import NamedProvider
from db.service import Database


async def generate_report(
    *, db_provider: NamedProvider[Database],
) -> str:
    analytics_db = await db_provider.get_or_create("analytics")
    # use analytics_db ...
    return "report"
```

**Pros:**

- Lazy creation — instances created only when first requested
- Singleton-per-name semantics (internal dict cache)
- Handles async factories (`get_or_create` is async)
- Scales to dynamic or large sets of names
- The provider is wired as a Typewire singleton, so all consumers share the same
  cache

**Cons:**

- More ceremony (a class to copy into the project)
- Without `warm_up`, errors surface at first use rather than at startup
- Consumer must `await` even for sync factories (async-uniform API)

**Best for:** Dynamic or large set of names, lazy creation needed, async factory
logic.

### Lifecycle: Eager Validation, Health Checks, and Teardown

The NamedProvider (Approach C) is lazy by default, which means errors only
surface when a name is first requested. The full `NamedProvider` class above
includes lifecycle methods for production readiness:

**Eager validation at startup** — `warm_up(names)` pre-creates critical named
instances so the app fails fast if something is misconfigured. In the wiring
example above, `config.required` (e.g. `["primary"]`) is warmed up before the
provider is yielded. If "primary" can't connect, the app fails at startup — not
on the first request.

**Health checks** — For readiness probes (e.g. Kubernetes `/healthz`), expose a
method that verifies specific named instances are reachable:

```python
async def check_health(
    provider: NamedProvider[Database], names: Sequence[str],
) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for name in names:
        try:
            instance = await provider.get_or_create(name)
            await instance.ping()
            results[name] = True
        except Exception:
            results[name] = False
    return results
```

A health check endpoint might only verify the "primary" database — not all named
instances. The consumer decides which names matter.

**Teardown** — `close_all()` cleans up cached instances when the container shuts
down. The generator-based `create_with` pattern (`yield provider` /
`await provider.close_all()`) integrates with Typewire's existing teardown
lifecycle — no extra wiring needed.

**Unknown name handling** — The optional `known_names` parameter validates names
before calling the factory, so a typo like `"primry"` raises a clear error
(`Unknown name 'primry'. Available: ['analytics', 'primary', 'readonly']`)
instead of a confusing `KeyError` deep in the config dict. Omit `known_names`
for truly open-ended name sets.

### Testing and Overrides

Replace the entire provider in tests using `with_creator()`. One override swaps
all named instances at once — no need to mock each name individually:

```python
# tests/test_reporting.py
from db.wires import db_provider_wire
from shared.named_provider import NamedProvider


def make_fake_db(name: str) -> FakeDatabase:
    return FakeDatabase(name=name)


test_db_provider_wire = db_provider_wire.with_creator(
    lambda _ctx: NamedProvider(make_fake_db)
)

test_group = app_group.with_extra_wires([test_db_provider_wire])
```

### Composing Multiple NamedProviders

A real app might have named database connections, named cache clients, and named
API clients. Each gets its own provider wire — consumers import the specific one
they need:

```python
# wires.py
db_provider_wire = type_wire_of(
    token="DbProvider",
    imports={"config": config_wire},
    create_with=create_db_provider,
)

cache_provider_wire = type_wire_of(
    token="CacheProvider",
    imports={"config": config_wire},
    create_with=create_cache_provider,
)


# Consumer imports both
def create_report_service(
    *,
    db_provider: NamedProvider[Database],
    cache_provider: NamedProvider[Cache],
) -> ReportService:
    return ReportService(db_provider, cache_provider)
```

Each provider is independent — its own cache, its own factory, its own lifecycle.
No collision between names across providers (a "primary" DB and a "primary" cache
are separate concerns).

### Choosing an Approach

| | Separate Wires | Dict Wire | NamedProvider |
|---|---|---|---|
| Names known at declaration time | Required | Not required | Not required |
| Creation | Per-wire (lazy via container) | Eager (all at startup) | Lazy (on first access) |
| Type safety | Full (per-wire token) | `dict[str, T]` | `NamedProvider[T]` |
| Scales to many names | No | Yes | Yes |
| Async factory support | Yes (via wire) | Yes (in `create_with`) | Yes (in `get_or_create`) |
| Extra code needed | None | None | `NamedProvider` class |

## Summary

| Topic | Recommended | Avoid |
|---|---|---|
| Wire naming | `db_wire = type_wire_of(...)` | `_db_wire = type_wire_of(...)` |
| Internal dependencies | `_policy = RetryPolicy(...)` | `_policy_wire = type_wire_of(...)` |
| `create_with` creator | Factory function with typed `*` args | Untyped lambda or `**kwargs` |
| Simple wire creators | `creator=lambda: Config(...)` | Overkill named function |
| Creator preference | Factory fn → classmethod → constructor | Constructor as default |
| File layout | `service.py` + `wires.py` | Everything in one file |
| Named instances | Separate wires, dict wire, or `NamedProvider` | See §5 for trade-offs |
