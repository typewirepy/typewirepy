from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest

from typewirepy import (
    TeardownError,
    TypeWire,
    TypeWireContainer,
    TypeWireError,
    WireNotRegisteredError,
    type_wire_of,
)


def _three_wires(order: list[str], *, use_async: bool = True) -> list[TypeWire[Any]]:
    """First and third cleanups fail; the second succeeds.

    With *use_async*, the second and third creators are async generators.
    """

    def make_first() -> Generator[str, None, None]:
        yield "first"
        order.append("first")
        raise RuntimeError("first cleanup boom")

    def make_second_sync() -> Generator[str, None, None]:
        yield "second"
        order.append("second")

    def make_third_sync() -> Generator[str, None, None]:
        yield "third"
        order.append("third")
        raise ValueError("third cleanup boom")

    async def make_second() -> AsyncGenerator[str, None]:
        for value in make_second_sync():
            yield value

    async def make_third() -> AsyncGenerator[str, None]:
        for value in make_third_sync():
            yield value

    return [
        type_wire_of(token="First", creator=make_first),
        type_wire_of(token="Second", creator=make_second if use_async else make_second_sync),
        type_wire_of(token="Third", creator=make_third if use_async else make_third_sync),
    ]


async def test_teardown_runs_every_cleanup_and_raises_all_failures() -> None:
    order: list[str] = []
    wires = _three_wires(order)
    container = TypeWireContainer()
    for wire in wires:
        await wire.apply(container)
    for wire in wires:
        await wire.get_instance(container)

    with pytest.raises(TeardownError) as exc_info:
        await container.teardown()

    assert order == ["third", "second", "first"]
    group = exc_info.value
    assert isinstance(group, ExceptionGroup)
    assert isinstance(group, TypeWireError)
    assert [str(e) for e in group.exceptions] == ["third cleanup boom", "first cleanup boom"]
    assert [type(e) for e in group.exceptions] == [ValueError, RuntimeError]
    assert group.exceptions[0].__notes__ == ["raised by the cleanup of wire 'Third'"]
    assert group.exceptions[1].__notes__ == ["raised by the cleanup of wire 'First'"]
    assert "2 cleanup(s) failed" in str(group)
    assert "'Third': ValueError: third cleanup boom" in str(group)


async def test_teardown_errors_raised_from_async_context_manager() -> None:
    order: list[str] = []
    wires = _three_wires(order)

    async def run() -> None:
        async with TypeWireContainer() as container:
            for wire in wires:
                await wire.apply(container)
            for wire in wires:
                await wire.get_instance(container)

    with pytest.raises(TeardownError) as exc_info:
        await run()

    assert order == ["third", "second", "first"]
    assert len(exc_info.value.exceptions) == 2


def test_teardown_errors_raised_from_sync_context_manager() -> None:
    order: list[str] = []
    wires = _three_wires(order, use_async=False)

    def run() -> None:
        with TypeWireContainer.sync() as container:
            for wire in wires:
                wire.apply_sync(container)
            for wire in wires:
                wire.get_instance_sync(container)

    with pytest.raises(TeardownError) as exc_info:
        run()

    assert order == ["third", "second", "first"]
    assert len(exc_info.value.exceptions) == 2


async def test_teardown_errors_except_star() -> None:
    order: list[str] = []
    wires = _three_wires(order)
    container = TypeWireContainer()
    for wire in wires:
        await wire.apply(container)
        await wire.get_instance(container)

    caught: list[str] = []
    try:
        await container.teardown()
    except* ValueError as group:
        caught.extend(str(e) for e in group.exceptions)
    except* RuntimeError as group:
        caught.extend(str(e) for e in group.exceptions)

    assert caught == ["third cleanup boom", "first cleanup boom"]


async def test_teardown_cleans_each_wire_once_and_skips_unresolved() -> None:
    cleaned: list[str] = []

    def make(label: str) -> Any:
        def creator() -> Generator[str, None, None]:
            yield label
            cleaned.append(label)
            raise RuntimeError(f"{label} boom")

        return creator

    resolved = type_wire_of(token="Resolved", creator=make("Resolved"))
    unresolved = type_wire_of(token="Unresolved", creator=make("Unresolved"))
    container = TypeWireContainer()
    await resolved.apply(container)
    await unresolved.apply(container)
    await resolved.get_instance(container)
    await resolved.get_instance(container)  # cached singleton, no second generator

    with pytest.raises(TeardownError) as exc_info:
        await container.teardown()
    assert len(exc_info.value.exceptions) == 1

    await container.teardown()  # nothing left to clean, nothing raised
    assert cleaned == ["Resolved"]


async def test_teardown_with_no_cleanup_failure_raises_nothing() -> None:
    cleaned: list[str] = []

    def make_ok() -> Generator[str, None, None]:
        yield "ok"
        cleaned.append("ok")

    wire = type_wire_of(token="Ok", creator=make_ok)
    async with TypeWireContainer() as container:
        await wire.apply(container)
        await wire.get_instance(container)

    assert cleaned == ["ok"]


async def test_teardown_of_container_that_created_nothing() -> None:
    cleaned: list[str] = []

    def make() -> Generator[str, None, None]:
        yield "never"
        cleaned.append("never")
        raise RuntimeError("never boom")

    wire = type_wire_of(token="Never", creator=make)
    container = TypeWireContainer()
    await wire.apply(container)

    await container.teardown()  # nothing created: nothing cleaned, nothing raised

    assert cleaned == []


async def test_resolve_after_teardown_fails() -> None:
    wire = type_wire_of(token="Val", creator=lambda: "value")
    container = TypeWireContainer()
    await wire.apply(container)
    assert await wire.get_instance(container) == "value"

    await container.teardown()

    with pytest.raises(WireNotRegisteredError, match="Val"):
        await wire.get_instance(container)
    with pytest.raises(WireNotRegisteredError, match="Val"):
        await container.resolve(wire.token)


async def _resolved_container(order: list[str]) -> TypeWireContainer:
    container = TypeWireContainer()
    for wire in _three_wires(order):
        await wire.apply(container)
        await wire.get_instance(container)
    return container


async def test_split_and_subgroup_return_teardown_error() -> None:
    container = await _resolved_container([])
    with pytest.raises(TeardownError) as exc_info:
        await container.teardown()
    group = exc_info.value

    match, rest = group.split(ValueError)
    assert type(match) is TeardownError
    assert type(rest) is TeardownError
    assert match.message == group.message
    assert [str(e) for e in match.exceptions] == ["third cleanup boom"]
    assert [str(e) for e in rest.exceptions] == ["first cleanup boom"]

    sub = group.subgroup(RuntimeError)
    assert type(sub) is TeardownError
    assert [str(e) for e in sub.exceptions] == ["first cleanup boom"]


async def test_except_star_binds_teardown_error() -> None:
    container = await _resolved_container([])
    matched: list[type[BaseException]] = []
    try:
        await container.teardown()
    except* ValueError as group:
        matched.append(type(group))
    except* RuntimeError as group:
        matched.append(type(group))

    assert matched == [TeardownError, TeardownError]


async def test_teardown_errors_false_is_deprecated_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """raise_teardown_errors=False keeps the pre-0.2.0 behaviour: log, don't raise."""
    order: list[str] = []
    wires = _three_wires(order)
    with pytest.warns(DeprecationWarning, match="raise_teardown_errors=False"):
        container = TypeWireContainer(raise_teardown_errors=False)
    for wire in wires:
        await wire.apply(container)
        await wire.get_instance(container)

    await container.teardown()

    assert order == ["third", "second", "first"]
    assert "third cleanup boom" in caplog.text
    assert "first cleanup boom" in caplog.text


def test_sync_teardown_errors_false_is_deprecated_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    order: list[str] = []
    wires = _three_wires(order, use_async=False)
    with pytest.warns(DeprecationWarning, match="raise_teardown_errors=False") as record:
        cm = TypeWireContainer.sync(raise_teardown_errors=False)
    assert len(record) == 1
    assert record[0].filename == __file__

    with cm as container:
        for wire in wires:
            wire.apply_sync(container)
            wire.get_instance_sync(container)

    assert order == ["third", "second", "first"]
    assert "third cleanup boom" in caplog.text


def test_default_container_does_not_warn(recwarn: pytest.WarningsRecorder) -> None:
    TypeWireContainer()
    TypeWireContainer.sync()
    assert not [w for w in recwarn if issubclass(w.category, DeprecationWarning)]
