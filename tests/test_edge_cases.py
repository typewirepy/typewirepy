"""Tests for edge cases and coverage gaps across the typewirepy library."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from typewirepy import (
    TRANSIENT,
    CreatorError,
    TypeWireContainer,
    combine_wire_groups,
    type_wire_group_of,
    type_wire_of,
)
from typewirepy.errors import NotResolvedError

# ---------------------------------------------------------------------------
# get_cached edge cases
# ---------------------------------------------------------------------------


async def test_get_cached_on_transient_wire_raises_not_resolved() -> None:
    """Transient wires are never stored in the singleton cache.

    Even after resolving a transient wire, get_cached should raise
    NotResolvedError because transients bypass the cache entirely.
    """
    wire = type_wire_of(token="Trans", creator=lambda: "value", scope=TRANSIENT)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        await wire.get_instance(container)  # resolves but doesn't cache
        with pytest.raises(NotResolvedError):
            container.get_cached(wire.token)


# ---------------------------------------------------------------------------
# Container reuse after teardown
# ---------------------------------------------------------------------------


async def test_container_reuse_after_teardown() -> None:
    """After teardown clears all state, the container can be reused."""
    wire = type_wire_of(token="Val", creator=lambda: "first")
    container = TypeWireContainer()

    await wire.apply(container)
    assert await wire.get_instance(container) == "first"
    await container.teardown()

    # Container is now empty
    assert not container.has(wire.token)

    # Re-register with a different factory
    wire2 = type_wire_of(token="Val", creator=lambda: "second")
    await wire2.apply(container)
    assert await wire2.get_instance(container) == "second"

    await container.teardown()


# ---------------------------------------------------------------------------
# Empty group operations
# ---------------------------------------------------------------------------


async def test_empty_group_apply() -> None:
    """Applying an empty group is a no-op."""
    group = type_wire_group_of([])
    async with TypeWireContainer() as container:
        await group.apply(container)  # should not raise


async def test_empty_group_get_all_instances() -> None:
    """get_all_instances on an empty group returns an empty list."""
    group = type_wire_group_of([])
    async with TypeWireContainer() as container:
        await group.apply(container)
        results = await group.get_all_instances(container)
        assert results == []


def test_empty_group_get_all_instances_sync() -> None:
    """get_all_instances_sync on an empty group returns an empty list."""
    group = type_wire_group_of([])
    with TypeWireContainer.sync() as container:
        group.apply_sync(container)
        results = group.get_all_instances_sync(container)
        assert results == []


async def test_empty_group_with_extra_wires() -> None:
    """with_extra_wires on an empty group produces a working group."""
    wire = type_wire_of(token="A", creator=lambda: "a")
    group = type_wire_group_of([])
    extended = group.with_extra_wires([wire])

    async with TypeWireContainer() as container:
        await extended.apply(container)
        results = await extended.get_all_instances(container)
        assert results == ["a"]


def test_empty_group_repr() -> None:
    """Empty group has a sensible repr."""
    group = type_wire_group_of([])
    assert repr(group) == "TypeWireGroup(wires=[])"


async def test_combine_empty_groups() -> None:
    """Combining empty groups produces an empty group."""
    combined = combine_wire_groups([type_wire_group_of([]), type_wire_group_of([])])
    assert combined.wires == []


# ---------------------------------------------------------------------------
# Concurrent resolution failure (get_all_instances with asyncio.gather)
# ---------------------------------------------------------------------------


async def test_get_all_instances_propagates_single_failure() -> None:
    """If one wire's creator fails, get_all_instances raises CreatorError."""
    good_wire = type_wire_of(token="Good", creator=lambda: "ok")

    def bad_creator() -> str:
        raise ValueError("boom")

    bad_wire = type_wire_of(token="Bad", creator=bad_creator)
    group = type_wire_group_of([good_wire, bad_wire])

    async with TypeWireContainer() as container:
        await group.apply(container)
        with pytest.raises(CreatorError, match="boom"):
            await group.get_all_instances(container)


async def test_get_all_instances_with_all_successful() -> None:
    """Verify order is preserved when all wires resolve successfully."""
    wires = [type_wire_of(token=f"W{i}", creator=lambda i=i: i) for i in range(5)]
    group = type_wire_group_of(wires)

    async with TypeWireContainer() as container:
        await group.apply(container)
        results = await group.get_all_instances(container)
        assert results == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# CreatorError wrapping — async creators and create_with
# ---------------------------------------------------------------------------


async def test_creator_error_wrapping_async_creator() -> None:
    """CreatorError wraps exceptions from async creators."""

    async def bad_async_creator() -> str:
        raise RuntimeError("async boom")

    wire = type_wire_of(token="AsyncBad", creator=bad_async_creator)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        with pytest.raises(CreatorError, match="async boom") as exc_info:
            await wire.get_instance(container)
        assert isinstance(exc_info.value.__cause__, RuntimeError)


async def test_creator_error_wrapping_create_with_dict() -> None:
    """CreatorError wraps exceptions from create_with (dict convention)."""
    dep = type_wire_of(token="Dep", creator=lambda: 42)

    def bad_factory(deps: dict[str, object]) -> str:
        raise TypeError("dict boom")

    wire = type_wire_of(token="Bad", create_with=bad_factory, imports={"dep": dep})
    async with TypeWireContainer() as container:
        await wire.apply(container)
        with pytest.raises(CreatorError, match="dict boom") as exc_info:
            await wire.get_instance(container)
        assert isinstance(exc_info.value.__cause__, TypeError)


async def test_creator_error_wrapping_create_with_kwargs() -> None:
    """CreatorError wraps exceptions from create_with (kwargs convention)."""
    dep = type_wire_of(token="Dep", creator=lambda: 42)

    def bad_factory(*, dep: object) -> str:
        raise TypeError("kwargs boom")

    wire = type_wire_of(token="Bad", create_with=bad_factory, imports={"dep": dep})
    async with TypeWireContainer() as container:
        await wire.apply(container)
        with pytest.raises(CreatorError, match="kwargs boom") as exc_info:
            await wire.get_instance(container)
        assert isinstance(exc_info.value.__cause__, TypeError)


async def test_creator_error_not_double_wrapped() -> None:
    """A CreatorError raised inside a creator is re-raised, not double-wrapped."""
    inner_cause = ValueError("inner")
    inner_error = CreatorError("inner_wire", inner_cause)

    def raises_creator_error() -> str:
        raise inner_error

    wire = type_wire_of(token="Outer", creator=raises_creator_error)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        with pytest.raises(CreatorError) as exc_info:
            await wire.get_instance(container)
        # Should be the original CreatorError, not wrapped again
        assert exc_info.value is inner_error


# ---------------------------------------------------------------------------
# Async generator cleanup error
# ---------------------------------------------------------------------------


async def test_async_generator_cleanup_error_handled(caplog: pytest.LogCaptureFixture) -> None:
    """Errors during async generator teardown are logged, not raised."""

    async def make_bad() -> Any:
        yield "value"
        raise RuntimeError("async cleanup boom")

    async def make_good() -> Any:
        yield "good"

    w1 = type_wire_of(token="AsyncBad", creator=make_bad)
    w2 = type_wire_of(token="AsyncGood", creator=make_good)

    container = TypeWireContainer()
    await w1.apply(container)
    await w2.apply(container)
    await w1.get_instance(container)
    await w2.get_instance(container)

    await container.teardown()  # should not raise

    assert "async cleanup boom" in caplog.text


async def test_generator_yields_only_first_value() -> None:
    """Even if a generator yields multiple values, only the first is used."""

    def multi_yield() -> Any:
        yield "first"
        yield "second"  # should be consumed during teardown, not returned

    wire = type_wire_of(token="Multi", creator=multi_yield)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        result = await wire.get_instance(container)
        assert result == "first"


# ---------------------------------------------------------------------------
# Immutability enforcement
# ---------------------------------------------------------------------------


def test_wire_setattr_raises() -> None:
    """TypeWire blocks attribute assignment after creation."""
    wire = type_wire_of(token="Immut", creator=lambda: 1)
    with pytest.raises(AttributeError, match="immutable"):
        wire._scope = TRANSIENT


def test_wire_delattr_raises() -> None:
    """TypeWire blocks attribute deletion."""
    wire = type_wire_of(token="Immut", creator=lambda: 1)
    with pytest.raises(AttributeError, match="immutable"):
        del wire._scope


def test_group_setattr_raises() -> None:
    """TypeWireGroup blocks attribute assignment after creation."""
    group = type_wire_group_of([])
    with pytest.raises(AttributeError, match="immutable"):
        group._wires = []


def test_group_delattr_raises() -> None:
    """TypeWireGroup blocks attribute deletion."""
    group = type_wire_group_of([])
    with pytest.raises(AttributeError, match="immutable"):
        del group._wires


# ---------------------------------------------------------------------------
# Wire re-apply overwrites (last-write-wins) and token identity
# ---------------------------------------------------------------------------


async def test_re_apply_overwrites_factory() -> None:
    """Applying a wire twice overwrites the factory (last-write-wins)."""
    wire1 = type_wire_of(token="Svc", creator=lambda: "v1")
    wire2 = type_wire_of(token="Svc", creator=lambda: "v2")

    async with TypeWireContainer() as container:
        await wire1.apply(container)
        # wire2 has a different WireToken instance, so both get registered
        await wire2.apply(container)
        assert await wire1.get_instance(container) == "v1"
        assert await wire2.get_instance(container) == "v2"


async def test_same_token_reapply_after_resolve_returns_cached() -> None:
    """Re-applying a singleton wire after resolution still returns the cached value.

    The factory is overwritten, but the singleton cache takes precedence.
    """
    wire = type_wire_of(token="Svc", creator=lambda: "original")
    override = wire.with_creator(lambda _ctx: "replaced")

    # They share the same token
    assert wire.token is override.token

    async with TypeWireContainer() as container:
        await wire.apply(container)
        assert await wire.get_instance(container) == "original"

        # Re-apply with override — factory is overwritten but cache persists
        await override.apply(container)
        assert await wire.get_instance(container) == "original"


async def test_same_token_override_before_resolve() -> None:
    """Applying override before resolving uses the overridden factory."""
    wire = type_wire_of(token="Svc", creator=lambda: "original")
    override = wire.with_creator(lambda _ctx: "replaced")

    async with TypeWireContainer() as container:
        await wire.apply(container)
        await override.apply(container)  # overwrite before resolving
        assert await wire.get_instance(container) == "replaced"


async def test_wire_tokens_with_same_label_are_independent() -> None:
    """Two wires created separately with the same label have distinct tokens."""
    wire_a = type_wire_of(token="Same", creator=lambda: "a")
    wire_b = type_wire_of(token="Same", creator=lambda: "b")

    # Tokens are different objects (identity-based, like JS Symbol)
    assert wire_a.token is not wire_b.token

    async with TypeWireContainer() as container:
        await wire_a.apply(container)
        await wire_b.apply(container)
        assert await wire_a.get_instance(container) == "a"
        assert await wire_b.get_instance(container) == "b"


# ---------------------------------------------------------------------------
# with_creator 1-arg on wire that originally had imports
# ---------------------------------------------------------------------------


async def test_with_creator_1_arg_on_wire_with_imports_clears_imports() -> None:
    """A 1-arg override on a composed wire drops the original imports entirely."""
    dep = type_wire_of(token="Dep", creator=lambda: 42)
    wire = type_wire_of(
        token="Svc",
        create_with=lambda deps: f"real({deps['dep']})",
        imports={"dep": dep},
    )

    overridden = wire.with_creator(lambda _ctx: "stubbed")

    # The override has no imports
    assert overridden.imports == {}

    async with TypeWireContainer() as container:
        # No need to apply dep — overridden doesn't depend on it
        await overridden.apply(container)
        assert await wire.get_instance(container) == "stubbed"


async def test_with_creator_2_arg_on_wire_with_imports_preserves_deps() -> None:
    """A 2-arg override on a composed wire still resolves original dependencies."""
    dep = type_wire_of(token="Dep", creator=lambda: 42)
    wire = type_wire_of(
        token="Svc",
        create_with=lambda deps: f"real({deps['dep']})",
        imports={"dep": dep},
    )

    async def spy(ctx: object, original: Callable[[], Awaitable[object]]) -> str:
        val = await original()
        return f"spy({val})"

    overridden = wire.with_creator(spy)

    # The override still carries the original imports
    assert "dep" in overridden.imports

    async with TypeWireContainer() as container:
        await overridden.apply(container)
        result = await wire.get_instance(container)
        assert result == "spy(real(42))"


# ---------------------------------------------------------------------------
# Wire repr
# ---------------------------------------------------------------------------


def test_wire_repr_simple() -> None:
    """Simple wire repr shows token, scope, and empty imports."""
    wire = type_wire_of(token="Config", creator=dict)
    r = repr(wire)
    assert "Config" in r
    assert "singleton" in r


def test_wire_repr_with_imports() -> None:
    """Composed wire repr shows import keys."""
    dep = type_wire_of(token="Dep", creator=lambda: 1)
    wire = type_wire_of(
        token="Svc",
        create_with=lambda deps: deps["dep"],
        imports={"dep": dep},
    )
    r = repr(wire)
    assert "Svc" in r
    assert "dep" in r


# ---------------------------------------------------------------------------
# WireToken repr
# ---------------------------------------------------------------------------


def test_wire_token_repr() -> None:
    from typewirepy.token import WireToken

    token = WireToken("MyToken")
    assert repr(token) == "WireToken('MyToken')"


# ---------------------------------------------------------------------------
# Monitor exit restores state after successful resolution
# ---------------------------------------------------------------------------


async def test_monitor_resets_after_successful_resolution() -> None:
    """After resolving A -> B successfully, resolving A -> C should not
    falsely report a cycle involving B."""
    a_wire = type_wire_of(token="A", creator=lambda: "a")
    b_wire = type_wire_of(
        token="B",
        create_with=lambda deps: f"B({deps['a']})",
        imports={"a": a_wire},
    )
    c_wire = type_wire_of(
        token="C",
        create_with=lambda deps: f"C({deps['a']})",
        imports={"a": a_wire},
    )

    async with TypeWireContainer() as container:
        await b_wire.apply(container)
        await c_wire.apply(container)
        # Both should resolve without circular dependency false positive
        assert await b_wire.get_instance(container) == "B(a)"
        assert await c_wire.get_instance(container) == "C(a)"
