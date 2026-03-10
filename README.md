# typewirepy

[![CI](https://github.com/typewirepy/typewirepy/actions/workflows/ci.yml/badge.svg)](https://github.com/typewirepy/typewirepy/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Lightweight, container-agnostic dependency injection for Python — typed, explicit, composable.

## Features

- **Zero runtime dependencies** — only stdlib
- **Fully typed** — strict mypy + pyright out of the box
- **Async-first** — native `async`/`await`; sync wrappers included
- **Immutable wires** — safe to share across threads and modules
- **Scopes** — singleton (default) and transient
- **Generator lifecycle** — `yield`-based creators with automatic cleanup
- **FastAPI integration** — `WireDepends()` bridges wires to FastAPI's `Depends()`

## Installation

```bash
pip install typewirepy
```

With FastAPI support:

```bash
pip install typewirepy[fastapi]
```

## Quick Start

### Async (primary)

```python
from typewirepy import Scope, TypeWireContainer, type_wire_group_of, type_wire_of

config_wire = type_wire_of(token="Config", creator=lambda: {"db_url": "sqlite://"})

db_wire = type_wire_of(
    token="Database",
    imports={"config": config_wire},
    create_with=lambda deps: f"db({deps['config']['db_url']})",
)

app_wires = type_wire_group_of([config_wire, db_wire])

async def main():
    async with TypeWireContainer() as container:
        await app_wires.apply(container)
        db = await db_wire.get_instance(container)
        print(db)  # "db(sqlite://)"
```

### Sync

```python
from typewirepy import TypeWireContainer, type_wire_of

wire = type_wire_of(token="Greeting", creator=lambda: "hello")

with TypeWireContainer.sync() as container:
    wire.apply_sync(container)
    print(wire.get_instance_sync(container))  # "hello"
```

## Key Concepts

### Wires

A **wire** is an immutable description of a dependency — its token (name), how to create it, and what it depends on. Create wires with `type_wire_of()`:

- **Leaf wire** — uses `creator` (zero-arg callable)
- **Composed wire** — uses `create_with` + `imports` to receive resolved dependencies

### Imports

Imports declare which other wires a composed wire depends on. They're passed as a `dict[str, TypeWire]` and delivered to `create_with` as a dict (Convention A) or as keyword arguments (Convention B):

```python
# Convention A: dict parameter
type_wire_of(token="Svc", imports={"db": db_wire}, create_with=lambda deps: deps["db"])

# Convention B: keyword-only parameters
def create_svc(*, db: Database) -> Service: ...
type_wire_of(token="Svc", imports={"db": db_wire}, create_with=create_svc)
```

### Scopes

- `Scope.SINGLETON` (default) — resolved once, cached for the container's lifetime
- `Scope.TRANSIENT` — resolved fresh on every call

### Groups

A `TypeWireGroup` bundles wires together for batch application:

```python
group = type_wire_group_of([config_wire, db_wire, service_wire])
await group.apply(container)
```

Override wires for testing with `with_extra_wires()`:

```python
test_group = group.with_extra_wires([service_wire.with_creator(lambda _: mock_svc)])
```

## FastAPI Integration

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from typewirepy import TypeWireContainer, type_wire_group_of, type_wire_of
from typewirepy.integrations.fastapi import WireDepends

db_wire = type_wire_of(token="DB", creator=lambda: "db_connection")
app_wires = type_wire_group_of([db_wire])

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with TypeWireContainer() as container:
        await app_wires.apply(container)
        app.state.typewire_container = container
        yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root(db: str = WireDepends(db_wire)):
    return {"db": db}
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
