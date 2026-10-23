"""Concurrent resolution: separate chains, shared singleton creation, no hangs.

Regression tests for issue #15.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from typewirepy import (
    TRANSIENT,
    CircularDependencyError,
    CreatorError,
    TypeWire,
    TypeWireContainer,
    WireToken,
    type_wire_group_of,
    type_wire_of,
)
from typewirepy.container import _RESOLVING
from typewirepy.scope import SINGLETON

# Every test that could deadlock if a rule regressed runs under this bound.
HANG_GUARD = 2.0


def _client_and_evaluator(created: list[str]) -> tuple[TypeWire[str], TypeWire[str]]:
    async def make_client() -> str:
        created.append("client")
        await asyncio.sleep(0.02)
        return "client"

    client: TypeWire[str] = type_wire_of(token="Client", creator=make_client)
    evaluator: TypeWire[str] = type_wire_of(
        token="Evaluator",
        imports={"client": client},
        create_with=lambda *, client: f"evaluator({client})",
    )
    return client, evaluator


# ---------------------------------------------------------------------------
# Issue #15 reproductions
# ---------------------------------------------------------------------------


async def test_concurrent_resolves_of_cold_singleton() -> None:
    created: list[str] = []
    client, evaluator = _client_and_evaluator(created)
    async with TypeWireContainer() as container:
        await type_wire_group_of([client, evaluator]).apply(container)
        a, b = await asyncio.gather(
            evaluator.get_instance(container), evaluator.get_instance(container)
        )
    assert a == b == "evaluator(client)"
    assert created == ["client"]


async def test_group_with_shared_import() -> None:
    created: list[str] = []
    client, evaluator = _client_and_evaluator(created)
    group = type_wire_group_of([client, evaluator])
    async with TypeWireContainer() as container:
        await group.apply(container)
        assert await group.get_all_instances(container) == ["client", "evaluator(client)"]
    assert created == ["client"]


def test_threads_resolving_cold_singleton() -> None:
    count = 0
    count_lock = threading.Lock()

    def make_client() -> object:
        nonlocal count
        with count_lock:
            count += 1
        time.sleep(0.02)
        return object()

    client = type_wire_of(token="Client", creator=make_client)
    evaluator = type_wire_of(
        token="Evaluator", imports={"client": client}, create_with=lambda *, client: client
    )
    container = TypeWireContainer()
    evaluator.apply_sync(container)

    results: list[object] = []
    errors: list[BaseException] = []

    def resolve() -> None:
        try:
            results.append(evaluator.get_instance_sync(container))
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=resolve) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(HANG_GUARD)

    assert errors == []
    assert len(results) == 4
    assert all(r is results[0] for r in results)
    assert count == 1


async def test_concurrent_transient_resolves() -> None:
    """Transients are created per resolve, and concurrent ones don't see each other."""
    count = 0

    async def make() -> int:
        nonlocal count
        count += 1
        mine = count
        await asyncio.sleep(0.01)
        return mine

    inner: TypeWire[int] = type_wire_of(token="Inner", creator=make, scope=TRANSIENT)
    outer = type_wire_of(
        token="Outer", imports={"inner": inner}, create_with=lambda *, inner: inner, scope=TRANSIENT
    )
    async with TypeWireContainer() as container:
        await outer.apply(container)
        values = await asyncio.gather(*(outer.get_instance(container) for _ in range(3)))
    assert sorted(values) == [1, 2, 3]


# ---------------------------------------------------------------------------
# Shared creation
# ---------------------------------------------------------------------------


async def test_generator_singleton_opened_and_cleaned_once() -> None:
    opened: list[int] = []
    closed: list[int] = []

    async def make() -> Any:  # async generator creator, as in test_generators.py
        i = len(opened)
        opened.append(i)
        await asyncio.sleep(0.01)
        yield f"conn{i}"
        closed.append(i)

    wire = type_wire_of(token="Conn", creator=make)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        values = await asyncio.gather(*(wire.get_instance(container) for _ in range(3)))
        assert values == ["conn0"] * 3
    assert opened == [0]
    assert closed == [0]


async def test_failed_creation_is_shared_and_not_cached() -> None:
    attempts = 0

    async def make() -> str:
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.01)
        if attempts == 1:
            raise ValueError("first attempt fails")
        return "ok"

    wire: TypeWire[str] = type_wire_of(token="Flaky", creator=make)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        results = await asyncio.gather(
            wire.get_instance(container), wire.get_instance(container), return_exceptions=True
        )
        assert attempts == 1
        assert all(isinstance(r, CreatorError) for r in results)
        assert results[0] is results[1]  # the one creation's error, shared

        assert await wire.get_instance(container) == "ok"  # nothing was cached
        assert attempts == 2


async def test_cancelled_creation_lets_waiters_retry() -> None:
    attempts = 0
    started = asyncio.Event()

    async def make() -> str:
        nonlocal attempts
        attempts += 1
        started.set()
        await asyncio.sleep(0.05)
        return f"value{attempts}"

    wire: TypeWire[str] = type_wire_of(token="Slow", creator=make)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        creator_task = asyncio.create_task(wire.get_instance(container))
        await started.wait()
        waiter = asyncio.create_task(wire.get_instance(container))
        await asyncio.sleep(0)
        creator_task.cancel()

        assert await asyncio.wait_for(waiter, HANG_GUARD) == "value2"
        with pytest.raises(asyncio.CancelledError):
            await creator_task
    assert attempts == 2


async def test_cancelled_waiter_does_not_affect_others() -> None:
    async def make() -> str:
        await asyncio.sleep(0.05)
        return "value"

    wire: TypeWire[str] = type_wire_of(token="Slow", creator=make)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        first = asyncio.create_task(wire.get_instance(container))
        second = asyncio.create_task(wire.get_instance(container))
        await asyncio.sleep(0.01)
        second.cancel()

        assert await first == "value"
        with pytest.raises(asyncio.CancelledError):
            await second
        assert await wire.get_instance(container) == "value"


# ---------------------------------------------------------------------------
# Cycles still raise, and never hang
# ---------------------------------------------------------------------------


async def test_cycle_through_a_task_spawned_by_the_creator() -> None:
    """The child task inherits its parent's chain, so waiting on itself is a cycle."""
    container = TypeWireContainer()
    token: WireToken[str] = WireToken("S")

    async def factory() -> str:
        return await asyncio.create_task(container.resolve(token))

    await container.register(token, factory, SINGLETON)
    with pytest.raises(CircularDependencyError, match="S -> S"):
        await asyncio.wait_for(container.resolve(token), HANG_GUARD)


async def test_cycle_split_across_two_concurrent_chains() -> None:
    """S needs T and T needs S; two resolves each hold one and would wait forever."""
    container = TypeWireContainer()
    token_s: WireToken[str] = WireToken("S")
    token_t: WireToken[str] = WireToken("T")

    async def factory_s() -> str:
        await asyncio.sleep(0.01)
        return f"S({await container.resolve(token_t)})"

    async def factory_t() -> str:
        await asyncio.sleep(0.02)
        return f"T({await container.resolve(token_s)})"

    await container.register(token_s, factory_s, SINGLETON)
    await container.register(token_t, factory_t, SINGLETON)

    results = await asyncio.wait_for(
        asyncio.gather(
            container.resolve(token_s), container.resolve(token_t), return_exceptions=True
        ),
        HANG_GUARD,
    )
    assert all(isinstance(r, CircularDependencyError) for r in results)
    assert any(r.path == ["T", "S", "T"] for r in results if isinstance(r, CircularDependencyError))


async def test_cycle_on_one_chain_with_noop_monitor() -> None:
    """Cycle detection no longer depends on the monitor, so a no-op monitor can't hang."""

    class NoopMonitor:
        def enter(self, token: WireToken[object]) -> None:
            pass

        def exit(self, token: WireToken[object]) -> None:
            pass

    container = TypeWireContainer(monitor_factory=NoopMonitor)
    token_a: WireToken[str] = WireToken("A")
    token_b: WireToken[str] = WireToken("B")

    async def factory_a() -> str:
        return await container.resolve(token_b)

    async def factory_b() -> str:
        return await container.resolve(token_a)

    await container.register(token_a, factory_a, SINGLETON)
    await container.register(token_b, factory_b, SINGLETON)
    with pytest.raises(CircularDependencyError, match="A -> B -> A"):
        await asyncio.wait_for(container.resolve(token_a), HANG_GUARD)


# ---------------------------------------------------------------------------
# Monitors and chain bookkeeping
# ---------------------------------------------------------------------------


async def test_each_task_gets_a_monitor_with_nested_calls() -> None:
    """A monitor instance only ever sees one strictly nested enter/exit sequence."""
    monitors: list[list[str]] = []

    class RecordingMonitor:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.depth = 0
            monitors.append(self.calls)

        def enter(self, token: WireToken[object]) -> None:
            self.depth += 1
            self.calls.append(f"+{token.label}")

        def exit(self, token: WireToken[object]) -> None:
            self.depth -= 1
            assert self.depth >= 0
            self.calls.append(f"-{token.label}")

    created: list[str] = []
    _client, evaluator = _client_and_evaluator(created)
    async with TypeWireContainer(monitor_factory=RecordingMonitor) as container:
        await evaluator.apply(container)
        await asyncio.gather(evaluator.get_instance(container), evaluator.get_instance(container))

    # One resolve creates Evaluator (and Client inside it); the other waits on that
    # creation. Each monitor saw its own balanced sequence, never the other's.
    assert sorted(monitors) == [
        ["+Evaluator", "+Client", "-Client", "-Evaluator"],
        ["+Evaluator", "-Evaluator"],
    ]


async def test_chain_is_empty_after_resolution() -> None:
    created: list[str] = []
    _client, evaluator = _client_and_evaluator(created)
    async with TypeWireContainer() as container:
        await evaluator.apply(container)
        await evaluator.get_instance(container)
        assert _RESOLVING.get() == ()


async def test_cycle_split_across_chains_through_a_nested_creation() -> None:
    """A -> B -> T on one chain, T -> A on another: the wait is recorded on A too."""
    container = TypeWireContainer()
    token_a: WireToken[str] = WireToken("A")
    token_b: WireToken[str] = WireToken("B")
    token_t: WireToken[str] = WireToken("T")

    async def factory_a() -> str:
        return f"A({await container.resolve(token_b)})"

    async def factory_b() -> str:
        await asyncio.sleep(0.01)
        return f"B({await container.resolve(token_t)})"

    async def factory_t() -> str:
        await asyncio.sleep(0.03)
        return f"T({await container.resolve(token_a)})"

    for token, factory in ((token_a, factory_a), (token_b, factory_b), (token_t, factory_t)):
        await container.register(token, factory, SINGLETON)

    results = await asyncio.wait_for(
        asyncio.gather(
            container.resolve(token_a), container.resolve(token_t), return_exceptions=True
        ),
        HANG_GUARD,
    )
    assert all(isinstance(r, CircularDependencyError) for r in results)
    paths = [r.path for r in results if isinstance(r, CircularDependencyError)]
    assert ["T", "A", "B", "T"] in paths
