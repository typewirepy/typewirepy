# TypeWire for Python — Design Specification v2

## 1. Goal

Port TypeWire's TypeScript API to Python 3.10+, keeping the same signatures and
semantics wherever possible. Deviate only where Python's type system, runtime
behavior, or community conventions require a different approach.

**Design principles carried from TypeWire TS:**

1. Wire is immutable — `with_creator()` returns a new wire, never mutates.
2. Wire is self-describing — carries its own token, factory, and imports.
3. Wire is container-agnostic — works through `apply` / `get_instance` abstraction.
4. Imports are explicit — declared as a dict of `name → wire`.
5. `create_with` receives resolved imports — as a dict matching the imports keys.
6. Singletons by default — scope supports SINGLETON (default) and TRANSIENT.
7. Async-first — creators can be sync or async.

**Additional principles for Python:**

8. Zero runtime dependencies — stdlib only.
9. Type-checker friendly — mypy and pyright should understand the full API.
10. Pythonic conventions — snake_case, context managers, Protocols, etc.

---

## 2. TypeScript API Surface (Source of Truth)

Extracted from the `@typewirets/core` package:

### Core Factory Functions

```typescript
typeWireOf<T>({
  token: string,
  creator?: () => T | Promise<T>,
  imports?: Record<string, TypeWire<any>>,
  createWith?: (imports: ResolvedImports) => T | Promise<T>,
}) => TypeWire<T>

typeWireGroupOf(wires: TypeWire<any>[]) => TypeWireGroup
```

### TypeWire<T>

```typescript
interface TypeWire<T> {
  apply(container: Applicable): Promise<void>
  getInstance(container): Promise<T>
  withCreator(fn): TypeWire<T>
}
```

### TypeWireGroup

```typescript
interface TypeWireGroup {
  apply(container: Applicable): Promise<void>
  withExtraWires(wires: TypeWire<any>[]): TypeWireGroup
}
```

### TypeWireContainer

```typescript
class TypeWireContainer {
  // Default built-in container
}
```

---

## 3. Python Translation

### 3.1 `type_wire_of` — Direct mapping

**TypeScript:**
```typescript
const LoggerWire = typeWireOf({
  token: 'Logger',
  creator: () => new Logger()
});

const UserServiceWire = typeWireOf({
  token: 'UserService',
  imports: { logger: LoggerWire },
  createWith({ logger }) { return new UserService(logger); },
});
```

**Python:**
```python
logger_wire: TypeWire[Logger] = type_wire_of(
    token="Logger",
    creator=lambda: Logger(),
)

# scope= controls instance lifetime (default: Scope.SINGLETON)
transient_wire: TypeWire[Logger] = type_wire_of(
    token="TransientLogger",
    creator=lambda: Logger(),
    scope=Scope.TRANSIENT,
)

user_service_wire: TypeWire[UserService] = type_wire_of(
    token="UserService",
    imports={"logger": logger_wire},
    create_with=lambda *, logger: UserService(logger),
)
```

### 3.2 `create_with` Signature Handling

**Gap:** TypeScript supports destructuring in parameters (`createWith({ logger })`).
Python does not.

**Resolution:** Support two calling conventions, detected via `inspect.signature`:

```python
# Convention B — Keyword-expanded (preferred, works with lambdas too)
create_with=lambda *, logger: UserService(logger)

# Convention A — Single dict parameter (legacy)
create_with=lambda deps: UserService(deps["logger"])

# Named function with keyword params
def create_user_service(*, logger: Logger) -> UserService:
    return UserService(logger)

# The library detects keyword params and calls as:
#   create_user_service(logger=resolved_logger)
```

Detection logic: if `create_with` has keyword-only parameters (after `*`) whose
names match keys in `imports`, expand as kwargs. Otherwise, pass as a single dict.
This is implemented in `_introspect.py`.

### 3.3 Type Safety with `Generic[T]`

```python
T = TypeVar("T")

class TypeWire(Generic[T]):
    # Properties (read-only)
    token_label: str                        # the wire's string label
    imports: dict[str, TypeWire[Any]]       # shallow copy of import dependencies
    scope: Scope                            # SINGLETON or TRANSIENT

    # Methods
    async def apply(self, container: "ContainerAdapter") -> None: ...
    async def get_instance(self, container: "ContainerAdapter") -> T: ...
    def with_creator(self, creator: Callable[..., T | Awaitable[T]]) -> "TypeWire[T]": ...
```

**Gap:** TypeScript infers `TypeWire<T>` from the creator return type. Python type
checkers need help.

**Resolution:** Provide `@overload` signatures on `type_wire_of` for inference, but
recommend explicit annotation as the primary style:

```python
# Recommended — explicit, readable
logger_wire: TypeWire[Logger] = type_wire_of(
    token="Logger",
    creator=lambda: Logger(),
)

# Also works — inferred via @overload
logger_wire = type_wire_of(token="Logger", creator=lambda: Logger())
```

### 3.4 `type_wire_group_of` — Direct mapping

```python
wire_group = type_wire_group_of([
    user_controller_wire,
    user_service_wire.with_creator(lambda: mock_service),
])
await wire_group.apply(container)
```

No gaps. Maps 1:1.

### 3.5 `TypeWireGroup.with_extra_wires` — Direct mapping

```python
test_wires = type_wire_group_of([logger_wire, user_service_wire])
mocked_wires = test_wires.with_extra_wires([
    user_service_wire.with_creator(lambda: mock_user_service)
])
```

No gaps. Maps 1:1.

### 3.6 `with_creator` with access to original creator

```python
async def spy_logger(ctx, original_creator):
    original = await original_creator()  # zero-arg closure
    original.log = MagicMock(wraps=original.log)
    return original

logger_wire.with_creator(spy_logger)
```

The `with_creator` callback supports both 1-arg `(ctx)` and 2-arg
`(ctx, original_creator)` forms — detected via arity inspection.

- `ctx` is always `None` (Python has no TS-style context object).
- `original_creator` is a zero-arg async callable — a closure that captures
  resolved deps internally, so callers simply `await original_creator()`.
- Works on wires using either `creator` or `create_with` (including imports).

### 3.7 `TypeWireContainer` — Direct mapping

```python
container = TypeWireContainer()
await user_service_wire.apply(container)
service = await user_service_wire.get_instance(container)
```

No gaps. Maps 1:1.

### 3.8 Container Adapter Protocol

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class ContainerAdapter(Protocol):
    async def register(self, token: _WireToken, factory: Callable, scope: Scope) -> None: ...
    async def resolve(self, token: _WireToken) -> Any: ...
    def has(self, token: _WireToken) -> bool: ...
```

Note: `ContainerAdapter` receives `_WireToken` (not string) so identity-based
lookup works correctly. The string label is only for error messages.

---

## 4. Internal Token Identity (Symbol Equivalent)

In TypeWire TS, the user passes a string `token`, but internally it becomes a
`Symbol(token)` — unique by identity. The user never interacts with the Symbol.

### Python implementation

```python
class _WireToken:
    """Internal unique identity. Equivalent to Symbol(label) in JavaScript."""
    __slots__ = ("label",)

    def __init__(self, label: str):
        self.label = label

    def __repr__(self) -> str:
        return f"WireToken({self.label!r})"

    # No __eq__ / __hash__ override
    # → uses object identity (id(self)) by default
    # → two _WireToken("Logger") are never equal, like Symbol("Logger")
```

### Identity flow

| Scenario | Internal token | Behavior |
|----------|---------------|----------|
| `type_wire_of(token="Logger")` called twice | Two distinct `_WireToken` | Two separate wires, no collision |
| `wire.with_creator(...)` | Same `_WireToken` as original | Container treats it as override |
| `wire.with_creator(...).with_creator(...)` | Same `_WireToken` | Chained overrides, same identity |

### User visibility

None. `_WireToken` is a private implementation detail. The string label appears
only in error messages:

```
CircularDependencyError: Circular dependency detected: Logger → UserService → Logger
```

---

## 5. Async / Sync API Strategy

### Gap

Python separates sync and async strictly. TypeScript's `Promise<T>` is transparent.

### Decision: Async-primary, sync convenience

**Primary API is async** — this is the honest translation of TypeWire TS and matches
the dominant Python ecosystem (FastAPI, async LLM clients, aiohttp, etc.).

```python
# Primary API (async)
container = TypeWireContainer()
await wire.apply(container)
instance = await wire.get_instance(container)
```

**Sync convenience methods** are provided for contexts where async is impractical
(Spark executors, scripts, REPL, Django views):

```python
# Sync convenience — wraps asyncio.run() internally
container = TypeWireContainer()
wire.apply_sync(container)
instance = wire.get_instance_sync(container)
```

Implementation note: sync methods detect whether an event loop is already running.
If so, they raise a clear error directing the user to use the async API. This avoids
the nested `asyncio.run()` trap.

### Creator functions

Creators can be either sync or async. The library normalizes internally:

```python
# Both are valid
type_wire_of(token="A", creator=lambda: SyncThing())
type_wire_of(token="B", creator=async_factory)
```

---

## 6. Lifecycle and Resource Cleanup

### The Python expectation

Python developers expect deterministic cleanup via context managers. Database
connections, file handles, HTTP clients — all use `with` / `async with`. This is
a strong community convention absent from the TypeWire TS API.

### Decision: Generator-based creators for lifecycle

If a creator is a generator (or async generator), the yielded value is the
dependency, and cleanup runs on container teardown:

```python
async def create_db_connection():
    conn = await asyncpg.connect(...)
    yield conn               # ← dependency
    await conn.close()       # ← cleanup on container teardown

db_wire: TypeWire[Connection] = type_wire_of(
    token="Database",
    creator=create_db_connection,
)
```

This pattern is borrowed from FastAPI's `Depends()` with generators and dishka's
`Iterable[T]` provider pattern. It's idiomatic Python that TypeWire TS doesn't
need because JavaScript has less emphasis on deterministic cleanup.

### Container as context manager

```python
async with TypeWireContainer() as container:
    await db_wire.apply(container)
    conn = await db_wire.get_instance(container)
    # use conn...
# ← container.__aexit__ triggers cleanup of all generator-based creators

# Sync equivalent
with TypeWireContainer.sync() as container:
    db_wire.apply_sync(container)
    conn = db_wire.get_instance_sync(container)
```

The container tracks which dependencies were created via generators and calls
cleanup in reverse-registration order on exit.

**Non-context-manager usage** is still supported — cleanup can be triggered
explicitly via `await container.teardown()`.

---

## 7. Distributed Environments (Spark, Ray, Dask)

### Core principle: Wires are module-level constants. Containers are local singletons.

Wire definitions are just Python objects declared at module level — they're imported
normally via standard `import` statements, like any other code. There is nothing to
broadcast, serialize, or send across boundaries. Each process (driver, executor,
worker) imports the same wire modules and creates its own application-level singleton
container.

### Recommended pattern

```python
# wires.py — standard Python module, imported everywhere
from typewirepy import type_wire_of, type_wire_group_of, TypeWire

logger_wire: TypeWire[Logger] = type_wire_of(token="Logger", creator=lambda: Logger())
service_wire: TypeWire[Service] = type_wire_of(
    token="Service",
    imports={"logger": logger_wire},
    create_with=lambda *, logger: Service(logger),
)
app_wires = type_wire_group_of([logger_wire, service_wire])
```

```python
# app.py — each process (driver or executor) does this
from wires import app_wires, service_wire
from typewirepy import TypeWireContainer

# Application-level singleton container — one per process
container = TypeWireContainer()
app_wires.apply_sync(container)

# Now any code in this process can resolve from the container
service = service_wire.get_instance_sync(container)
```

In Spark specifically, this means:
- The **driver** imports wires and creates its own container.
- Each **executor** imports the same wires and creates its own container.
- No broadcasting. No serialization of wires or containers.
- The container is the application-wide singleton on each side, hidden behind
  whatever module or class manages your application lifecycle.

### Anti-pattern

```python
# ❌ WRONG — never serialize containers or broadcast wire groups
sc.broadcast(container)      # container holds live instances
sc.broadcast(wire_group)     # unnecessary; just import the module

# ✅ CORRECT — just import and build locally
from wires import app_wires  # normal Python import
container = TypeWireContainer()
app_wires.apply_sync(container)
```

### Why sync convenience matters here

Spark executors run synchronous code. The `apply_sync()` / `get_instance_sync()`
methods (§5) exist specifically so executor code doesn't need `asyncio.run()`
wrappers.

---

## 8. Testing Patterns

### pytest integration

TypeWire's override mechanism maps naturally to pytest fixtures:

```python
import pytest
from typewirepy import type_wire_group_of, TypeWireContainer

@pytest.fixture
async def container():
    """Base container with production wires."""
    c = TypeWireContainer()
    await production_wire_group.apply(c)
    yield c
    await c.teardown()

@pytest.fixture
async def test_container():
    """Container with mocked dependencies."""
    c = TypeWireContainer()
    mocked = production_wire_group.with_extra_wires([
        user_service_wire.with_creator(lambda: MockUserService()),
    ])
    await mocked.apply(c)
    yield c
    await c.teardown()

async def test_user_lookup(test_container):
    service = await user_service_wire.get_instance(test_container)
    user = await service.get_by_id("known")
    assert user is not None
```

### unittest integration

```python
class TestUserService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.container = TypeWireContainer()
        mocked = production_wires.with_extra_wires([
            user_service_wire.with_creator(lambda: MockUserService()),
        ])
        await mocked.apply(self.container)

    async def asyncTearDown(self):
        await self.container.teardown()

    async def test_get_user(self):
        service = await user_service_wire.get_instance(self.container)
        assert await service.get_by_id("known") is not None
```

### Key testing advantage (carried from TypeWire TS)

No `unittest.mock.patch`, no `monkeypatch`, no import-time magic. Overrides are
explicit, typed, and scoped to the test's container. This is TypeWire's killer
feature and it translates directly.

---

## 9. Compatibility with Python Conventions

### 9.1 Dataclasses

Python developers use `@dataclass` heavily. Wires should work seamlessly:

```python
from dataclasses import dataclass

@dataclass
class AppConfig:
    db_url: str
    api_key: str

@dataclass
class UserRepository:
    config: AppConfig

config_wire: TypeWire[AppConfig] = type_wire_of(
    token="AppConfig",
    creator=lambda: AppConfig(
        db_url=os.environ["DB_URL"],
        api_key=os.environ["API_KEY"],
    ),
)

repo_wire: TypeWire[UserRepository] = type_wire_of(
    token="UserRepository",
    imports={"config": config_wire},
    create_with=lambda *, config: UserRepository(config=config),
)
```

No special handling needed — dataclasses are just classes with constructors.

### 9.2 Protocols and ABCs

TypeWire works with both `typing.Protocol` (structural typing) and `abc.ABC`
(nominal typing). The wire's type parameter `T` can be either:

```python
from typing import Protocol
from abc import ABC, abstractmethod

# Protocol (structural) — no inheritance required
class Cache(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...

# ABC (nominal) — requires inheritance
class BaseCache(ABC):
    @abstractmethod
    def get(self, key: str) -> str | None: ...

# Both work as TypeWire[T]
cache_wire: TypeWire[Cache] = type_wire_of(
    token="Cache",
    creator=lambda: RedisCache(),
)
```

### 9.3 Logging

The library uses `logging.getLogger(__name__)` internally. No custom logging
framework. Users control verbosity via standard Python logging configuration.

```python
import logging
logging.getLogger("typewirepy").setLevel(logging.DEBUG)
# → logs wire registration, resolution, circular dependency detection
```

### 9.4 Thread Safety

`TypeWireContainer` is **not thread-safe by default** — this matches the Python
convention where most stdlib objects are not thread-safe and the user applies
locking as needed.

For concurrent usage, a `ThreadSafeTypeWireContainer` may be provided in future
versions, or users can wrap with their own locks. This is explicitly documented.

Async safety (multiple coroutines sharing a container within a single event loop)
is supported — resolution is atomic per `await` call.

### 9.5 Exception Hierarchy

```python
class TypeWireError(Exception):
    """Base exception for all TypeWire errors."""

class CircularDependencyError(TypeWireError):
    """Raised when a circular dependency is detected during apply()."""

class WireNotRegisteredError(TypeWireError):
    """Raised when get_instance() is called for a wire not yet applied."""

class DuplicateWireError(TypeWireError):
    """Raised when apply() encounters a duplicate token registration
    and the container is configured to reject duplicates."""

class CreatorError(TypeWireError):
    """Raised when a creator function fails during resolution.
    Wraps the original exception as __cause__."""
```

All exceptions inherit from a single base class so users can catch broadly
(`except TypeWireError`) or narrowly.

---

## 10. Framework Integration: FastAPI

FastAPI's DI system is built on `Depends()` — a callable that FastAPI invokes
per request to provide dependencies. The bridge to TypeWire is natural: a wire +
a container can produce exactly the callable that `Depends()` expects.

### 10.1 The Bridge: `WireDepends`

```python
# typewirepy/integrations/fastapi.py (optional submodule)

from typing import Any, TypeVar
from fastapi import Depends, Request
from typewirepy.wire import TypeWire

T = TypeVar("T")

CONTAINER_ATTR = "typewire_container"

def WireDepends(wire: TypeWire[T]) -> Any:
    """FastAPI dependency that resolves a wire from the request's container.

    The container must be stored on ``app.state.typewire_container``
    (e.g. during the FastAPI lifespan).

    Usage:
        @app.get("/users/{user_id}")
        async def get_user(
            user_id: str,
            service: UserService = WireDepends(user_service_wire),
        ):
            return await service.get_by_id(user_id)
    """
    async def _resolver(request: Request) -> T:
        container = getattr(request.app.state, CONTAINER_ATTR, None)
        if container is None:
            raise RuntimeError(
                f"No TypeWireContainer on app.state.{CONTAINER_ATTR}. "
                "Set it during your FastAPI lifespan."
            )
        return await wire.get_instance(container)
    return Depends(_resolver)
```

This is intentionally minimal — a single function, no magic.

### 10.2 Full Usage Pattern

```python
from fastapi import FastAPI
from contextlib import asynccontextmanager

from typewirepy import TypeWireContainer
from typewirepy.integrations.fastapi import WireDepends

from .wires import app_wires, user_service_wire, logger_wire
from .types import UserService, Logger

# ── Container lifecycle tied to FastAPI lifespan ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with TypeWireContainer() as container:
        await app_wires.apply(container)
        app.state.typewire_container = container
        yield

app = FastAPI(lifespan=lifespan)


# ── Routes ──

@app.get("/users/{user_id}")
async def get_user(user_id: str, service: UserService = WireDepends(user_service_wire)):
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404)
    return user

@app.get("/health")
async def health(logger: Logger = WireDepends(logger_wire)):
    logger.log("Health check")
    return {"status": "ok"}
```

### 10.3 Testing with FastAPI

TypeWire's override system works alongside FastAPI's test client. You have
two options:

**Option A — Use TypeWire overrides (recommended):**

Override `app.state.typewire_container` with a test container before making
requests. Because `WireDepends` reads from `request.app.state` at request
time, swapping the container is sufficient.

```python
import pytest
from httpx import AsyncClient, ASGITransport

@pytest.fixture
async def test_app():
    """App with mocked dependencies."""
    from myapp.main import app

    test_container = TypeWireContainer()
    mocked = app_wires.with_extra_wires([
        user_service_wire.with_creator(lambda: MockUserService())
    ])
    await mocked.apply(test_container)

    # Override the container on app.state
    app.state.typewire_container = test_container

    yield app

    await test_container.teardown()

async def test_get_user(test_app):
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.get("/users/known")
        assert response.status_code == 200
```

### 10.4 Why This Works Well

The key insight is that `WireDepends` is just a thin adapter — it doesn't
take over FastAPI's DI system, it plugs into it. This means:

- FastAPI's own dependency caching and `yield`-based cleanup still work normally for non-TypeWire dependencies. TypeWire dependencies are resolved from the app-level container and are not request-scoped.
- OpenAPI schema generation still works (type hints are preserved).
- You can mix TypeWire-backed dependencies with plain FastAPI `Depends()` freely.
- No middleware, no monkey-patching, no framework coupling in the core library.

### 10.5 Other Frameworks (Future, Non-Blocking)

The same adapter pattern applies to other frameworks:

```python
# Django — middleware creates container per request (or app-wide singleton)
# Flask — app context holds the container
# Litestar — similar to FastAPI, has its own Depends equivalent
```

These are not part of v1 but the architecture already supports them. The
core library has no dependency on any framework. Integrations would be
separate optional submodules under `typewirepy.integrations.*`.

---

## 11. Complete Public API

```python
# typewirepy/__init__.py

from typewirepy.core import type_wire_of, type_wire_group_of
from typewirepy.wire import TypeWire
from typewirepy.group import TypeWireGroup
from typewirepy.container import TypeWireContainer
from typewirepy.protocols import ContainerAdapter
from typewirepy.scope import Scope
from typewirepy.errors import (
    TypeWireError,
    CircularDependencyError,
    WireNotRegisteredError,
    DuplicateWireError,
    CreatorError,
)

__all__ = [
    "type_wire_of",
    "type_wire_group_of",
    "TypeWire",
    "TypeWireGroup",
    "TypeWireContainer",
    "ContainerAdapter",
    "Scope",
    "TypeWireError",
    "CircularDependencyError",
    "WireNotRegisteredError",
    "DuplicateWireError",
    "CreatorError",
]
```

---

## 12. Full Example

```python
from typing import Protocol
from typewirepy import type_wire_of, type_wire_group_of, TypeWireContainer, TypeWire


# ──────────────────────────────────────────
# 1. Domain types (no framework coupling)
# ──────────────────────────────────────────

class Logger:
    def log(self, message: str) -> None:
        print(f"[LOG] {message}")


class UserService(Protocol):
    async def get_by_id(self, user_id: str) -> dict | None: ...


# ──────────────────────────────────────────
# 2. Wire definitions
# ──────────────────────────────────────────

logger_wire: TypeWire[Logger] = type_wire_of(
    token="Logger",
    creator=lambda: Logger(),
)

def create_user_service(*, logger: Logger) -> UserService:
    """Factory with typed, named dependencies."""
    class _Impl:
        async def get_by_id(self, user_id: str) -> dict | None:
            logger.log(f"Getting user {user_id}")
            if user_id == "123":
                return {"id": "123", "name": "John"}
            return None
    return _Impl()

user_service_wire: TypeWire[UserService] = type_wire_of(
    token="UserService",
    imports={"logger": logger_wire},
    create_with=create_user_service,
)


# ──────────────────────────────────────────
# 3. Application usage
# ──────────────────────────────────────────

async def main():
    async with TypeWireContainer() as container:
        await user_service_wire.apply(container)
        service = await user_service_wire.get_instance(container)
        user = await service.get_by_id("123")
        print(user)


# ──────────────────────────────────────────
# 4. Testing with overrides
# ──────────────────────────────────────────

async def test_user_service():
    mock_users = {"known": {"id": "known", "name": "Test User"}}

    class MockService:
        async def get_by_id(self, user_id: str) -> dict | None:
            return mock_users.get(user_id)

    test_wires = type_wire_group_of([user_service_wire]).with_extra_wires([
        user_service_wire.with_creator(lambda: MockService())
    ])

    async with TypeWireContainer() as container:
        await test_wires.apply(container)
        service = await user_service_wire.get_instance(container)
        assert await service.get_by_id("known") == mock_users["known"]
```

---

## 13. Summary of Gaps

| # | Gap | TypeScript | Python Approach |
|---|-----|-----------|-----------------|
| 1 | No parameter destructuring | `createWith({ logger })` | Detect signature: expand as `**kwargs` for named params, pass dict for lambdas |
| 2 | Type inference on returns | Automatic via TS | `@overload` + recommended explicit `TypeWire[T]` annotation |
| 3 | Sync/async separation | `Promise<T>` everywhere | Async-primary + `apply_sync()` / `get_instance_sync()` convenience |
| 4 | No `Symbol` in Python | `Symbol(token)` | Private `_WireToken` class using object identity |
| 5 | No lifecycle/cleanup in TS | Not needed in JS | Generator-based creators + container-as-context-manager (§6) |

Gap #5 is an **addition**, not a compromise — it makes TypeWire more Pythonic by
supporting deterministic cleanup, a pattern the Python community expects.

---

## 14. Project Structure

```
typewirepy/
├── pyproject.toml           # PEP 621 metadata, requires-python >= "3.10"
├── src/
│   └── typewirepy/
│       ├── __init__.py      # public API exports + __all__
│       ├── py.typed         # PEP 561 marker for type checker support
│       ├── core.py          # type_wire_of, type_wire_group_of factory functions
│       ├── wire.py          # TypeWire[T] class
│       ├── group.py         # TypeWireGroup class
│       ├── container.py     # TypeWireContainer (default container, context manager)
│       ├── protocols.py     # ContainerAdapter protocol
│       ├── scope.py         # Scope enum (SINGLETON, TRANSIENT)
│       ├── errors.py        # Exception hierarchy
│       ├── _token.py        # _WireToken (private, Symbol equivalent)
│       ├── _introspect.py   # inspect-based creator signature detection
│       └── integrations/    # optional framework adapters (no extra deps)
│           ├── __init__.py
│           └── fastapi.py   # WireDepends() adapter
├── tests/
│   ├── test_wire.py         # TypeWire creation, apply, get_instance
│   ├── test_group.py        # TypeWireGroup, with_extra_wires
│   ├── test_container.py    # Container lifecycle, context manager, teardown
│   ├── test_overrides.py    # with_creator, override behavior
│   ├── test_circular.py     # Circular dependency detection
│   ├── test_sync.py         # Sync convenience methods
│   ├── test_generators.py   # Generator-based creators (lifecycle)
│   ├── test_distributed.py  # distributed pattern: import wires, create local container
│   ├── test_validation.py   # Eager validation (mutual exclusivity, import alignment)
│   └── test_fastapi.py      # FastAPI integration (requires fastapi as test dep)
└── README.md
```

### Package metadata

- **Name on PyPI:** `typewirepy` (`typewire` is taken by an unrelated package).
- **GitHub org:** `typewirepy` (mirrors `typewirets` pattern from the TS project)
- **Import name:** `import typewirepy`
- **Python:** `>= 3.10` (for `X | Y` union syntax, `match` statements if needed)
- **Runtime dependencies:** None (stdlib only)
- **Optional dependencies:** `typewirepy[fastapi]` installs `fastapi` for the
  integration module. The integration submodule imports FastAPI unconditionally,
  so importing it without FastAPI installed raises `ImportError` — expected
  behavior for an optional integration.
- **Dev dependencies:** `pytest`, `pytest-asyncio`, `mypy`, `pyright`, `ruff`,
  `fastapi`, `httpx` (for integration tests)

---

## 15. Implementation Order

1. **`errors.py`** — exception hierarchy (needed by everything)
2. **`scope.py`** — `Scope` enum
3. **`_token.py`** — `_WireToken`
4. **`protocols.py`** — `ContainerAdapter` protocol
5. **`_introspect.py`** — creator signature detection (dict vs kwargs)
6. **`wire.py`** — `TypeWire[T]` class
7. **`core.py`** — `type_wire_of` factory function
8. **`container.py`** — `TypeWireContainer` with context manager + teardown
9. **`group.py`** — `TypeWireGroup` + `type_wire_group_of`
10. **`__init__.py`** — public API exports
11. **`integrations/fastapi.py`** — `WireDepends()` adapter
12. **Tests** — written alongside each module, run with `pytest-asyncio`

---

## 16. Open Questions for Implementation

These do not block the spec but should be resolved during implementation:

1. **Duplicate token policy:** When `apply()` encounters a wire whose token is
   already registered, should it: (a) silently override (last-write-wins),
   (b) raise `DuplicateWireError`, or (c) be configurable? TypeWire TS behavior
   should be the default.

2. **Lazy vs eager resolution:** Should `apply()` resolve all wires immediately
   or defer to first `get_instance()` call? TypeWire TS defers (lazy).

3. **`py.typed` marker:** Include for PEP 561 compliance so downstream users
   get type checking benefits.

4. **PyPI name:** Resolved — `typewirepy`. Verify org availability on GitHub.

---

## 17. Review: Edge Cases and Validation

The following behaviors must be well-defined and tested.

### 17.1 Wire Validation at `type_wire_of` Time

When `type_wire_of` is called with both `imports` and `create_with`, the library
should validate (when detectable) that the `imports` keys align with the `create_with`
parameter names. Mismatches should raise `TypeWireError` eagerly — not at resolution
time — so errors are caught early.

```python
# Convention B — ❌ Should raise immediately — "db" not in imports
type_wire_of(
    token="Service",
    imports={"logger": logger_wire},
    create_with=lambda *, db: Service(db),  # "db" not in imports → TypeWireError
)
```

For Convention B (keyword-expanded), this validation is straightforward since we
can compare `imports.keys()` against the function's parameter names.

For Convention A (dict parameter), we cannot validate at definition time — errors
surface at resolution time as `KeyError`. This is an acceptable tradeoff.

### 17.2 Missing Imports in Groups

When `with_extra_wires` overrides a wire, the override may have the same imports
as the original. But what if an overriding wire references an import wire that
isn't in the group?

**Decision:** `apply()` recursively registers all imports, including those
transitively referenced by overrides. If an import wire's token is already
registered, it is skipped (not duplicated). This matches TypeWire TS behavior.

### 17.3 TypeWire Immutability

`TypeWire` instances must be truly immutable after creation. Implementation should
use `__slots__` and avoid any mutable state:

```python
class TypeWire(Generic[T]):
    __slots__ = ("_token", "_creator", "_imports", "_scope", "_original_creator")
    
    def __init__(self, ...):
        object.__setattr__(self, "_token", token)
        # ... etc
    
    def __setattr__(self, name, value):
        raise AttributeError("TypeWire instances are immutable")
```

This prevents accidental mutation and makes TypeWire safe for use as a module-level
constant (the expected pattern).

### 17.4 Debugging and Repr

`TypeWire` and `TypeWireGroup` should have meaningful `__repr__` for debuggability:

```python
>>> logger_wire
TypeWire(token='Logger', scope=Scope.SINGLETON, imports={})

>>> user_service_wire
TypeWire(token='UserService', scope=Scope.SINGLETON, imports={'logger': TypeWire(token='Logger', ...)})

>>> type_wire_group_of([logger_wire, user_service_wire])
TypeWireGroup(wires=[TypeWire(token='Logger', ...), TypeWire(token='UserService', ...)])
```

Public introspection properties (`token_label`, `imports`, `scope`) provide
programmatic access to the same data shown in `__repr__`, enabling users to
build dependency graphs, generate documentation, or debug resolution without
reaching into private attributes.

```python
wire.token_label  # "UserService"
wire.scope        # Scope.SINGLETON
wire.imports      # {"logger": TypeWire(...)}  — shallow copy, safe to mutate
```

### 17.5 Mutual Exclusivity of `creator` and `create_with`

`type_wire_of` accepts either `creator` (no-arg factory) or `create_with`
(factory receiving imports), but not both. Passing both should raise `TypeWireError`.
Passing neither should also raise.

When `imports` is provided, `create_with` is required.
When `imports` is omitted, `creator` is required.

### 17.6 Circular Dependency Detection

Detected at `apply()` time by tracking the resolution path. When wire A imports
wire B which imports wire A, raise `CircularDependencyError` with the full cycle
path in the message:

```
CircularDependencyError: Circular dependency: A → B → A
```

Detection uses a set of `_WireToken` identities during recursive `apply()`.

---

## 18. Review: Python Ecosystem Alignment

Final checklist confirming alignment with Python community conventions.

| Convention | Status | Notes |
|-----------|--------|-------|
| snake_case naming | ✅ | All public API is snake_case |
| PEP 621 pyproject.toml | ✅ | No setup.py / setup.cfg |
| src/ layout | ✅ | `src/typewirepy/` prevents accidental local imports |
| `__all__` in `__init__.py` | ✅ | Explicit public API |
| `py.typed` marker (PEP 561) | ✅ | For mypy/pyright support |
| Context manager protocol | ✅ | Container supports `async with` |
| Generator cleanup pattern | ✅ | Matches FastAPI/dishka convention |
| stdlib logging | ✅ | `logging.getLogger(__name__)` |
| Exception hierarchy | ✅ | Single base class, specific subclasses |
| Zero runtime deps | ✅ | stdlib only |
| Protocol over ABC | ✅ | ContainerAdapter uses Protocol (duck typing) |
| Frozen/immutable objects | ✅ | TypeWire uses `__slots__` + `__setattr__` guard |
| Async-first + sync escape | ✅ | Primary async, `*_sync()` convenience |
| pytest-friendly | ✅ | Fixtures map naturally to wire override pattern |
| Dataclass-compatible | ✅ | No special handling needed |
| Distributed-safe (Spark/Ray) | ✅ | Wires are module-level constants imported normally; containers are created locally per-process. No serialization of wires or containers is needed or supported |
| FastAPI integration | ✅ | `WireDepends()` adapter, zero coupling in core |
| Thread safety documented | ✅ | Explicitly not thread-safe; documented |
| `__repr__` for debugging | ✅ | Meaningful repr on all public types |
