from __future__ import annotations

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from typewirepy._introspect import detect_creator_arity
from typewirepy.errors import CircularDependencyError, CreatorError, WireNotRegisteredError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from typewirepy._token import _WireToken
    from typewirepy.protocols import ContainerAdapter
    from typewirepy.scope import Scope

T = TypeVar("T")

logger = logging.getLogger(__name__)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class TypeWire(Generic[T]):
    __slots__ = ("_convention", "_create_with", "_creator", "_imports", "_scope", "_token")

    def __init__(
        self,
        token: _WireToken,
        creator: Callable[..., Any] | None,
        create_with: Callable[..., Any] | None,
        imports: dict[str, TypeWire[Any]],
        scope: Scope,
        convention: str,
    ) -> None:
        object.__setattr__(self, "_token", token)
        object.__setattr__(self, "_creator", creator)
        object.__setattr__(self, "_create_with", create_with)
        object.__setattr__(self, "_imports", imports)
        object.__setattr__(self, "_scope", scope)
        object.__setattr__(self, "_convention", convention)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("TypeWire instances are immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("TypeWire instances are immutable")

    def __repr__(self) -> str:
        import_keys = set(self._imports.keys()) if self._imports else set()
        scope_name = f"Scope.{self._scope.name}"
        return f"TypeWire(token={self._token.label!r}, scope={scope_name}, imports={import_keys!r})"

    async def apply(
        self,
        container: ContainerAdapter,
        _path: list[_WireToken] | None = None,
        _is_import: bool = False,
    ) -> None:
        if _path is None:
            _path = []

        if self._token in _path:
            labels = [t.label for t in _path] + [self._token.label]
            raise CircularDependencyError(labels)

        # Skip already-registered tokens only during import recursion (SPEC 17.2)
        if _is_import and container.has(self._token):
            return

        _path.append(self._token)

        for _name, imp_wire in self._imports.items():
            await imp_wire.apply(container, _path, _is_import=True)

        factory = self._make_factory(container)
        await container.register(self._token, factory, self._scope)

        _path.pop()

    def _make_factory(self, container: ContainerAdapter) -> Callable[[], Awaitable[T]]:
        wire = self

        async def factory() -> T:
            try:
                if wire._create_with is not None:
                    resolved: dict[str, Any] = {}
                    for name, imp_wire in wire._imports.items():
                        resolved[name] = await container.resolve(imp_wire._token)
                    if wire._convention == "kwargs":
                        result = wire._create_with(**resolved)
                    else:
                        result = wire._create_with(resolved)
                    return await _maybe_await(result)  # type: ignore[return-value]
                else:
                    return await _maybe_await(wire._creator())  # type: ignore[misc, return-value]
            except CreatorError:
                raise
            except Exception as e:
                raise CreatorError(wire._token.label, e) from e

        return factory

    async def get_instance(self, container: ContainerAdapter) -> T:
        if not container.has(self._token):
            raise WireNotRegisteredError(self._token.label)
        return await container.resolve(self._token)  # type: ignore[return-value]

    def with_creator(
        self,
        fn: Callable[..., Any],
    ) -> TypeWire[T]:
        arity = detect_creator_arity(fn)

        if arity == 2:
            original_wire = self

            def wrapped_creator() -> Any:
                original_factory = original_wire._creator or original_wire._create_with

                async def _call_with_original() -> Any:
                    async def original_caller() -> Any:
                        return await _maybe_await(original_factory())  # type: ignore[misc]

                    return await _maybe_await(fn(None, original_caller))

                return _call_with_original()

            return TypeWire(
                token=self._token,
                creator=wrapped_creator,
                create_with=None,
                imports={},
                scope=self._scope,
                convention="dict",
            )
        else:

            def one_arg_creator() -> Any:
                return fn(None)

            return TypeWire(
                token=self._token,
                creator=one_arg_creator,
                create_with=None,
                imports={},
                scope=self._scope,
                convention="dict",
            )

    def apply_sync(self, container: ContainerAdapter) -> None:
        _check_no_running_loop()
        asyncio.run(self.apply(container))

    def get_instance_sync(self, container: ContainerAdapter) -> T:
        _check_no_running_loop()
        return asyncio.run(self.get_instance(container))


def _check_no_running_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        "Cannot use sync API from within a running event loop. Use the async API instead."
    )
