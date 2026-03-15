from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar, cast, overload

from typewirepy._introspect import detect_creator_arity
from typewirepy._token import _WireToken
from typewirepy.errors import CircularDependencyError, CreatorError, WireNotRegisteredError
from typewirepy.protocols import ContainerAdapter
from typewirepy.scope import Scope

T = TypeVar("T")
_R = TypeVar("_R")

logger = logging.getLogger(__name__)


@overload
async def _maybe_await(value: Awaitable[_R]) -> _R: ...


@overload
async def _maybe_await(value: _R) -> _R: ...


async def _maybe_await(value: _R | Awaitable[_R]) -> _R:
    if inspect.isawaitable(value):
        return cast("_R", await cast("Awaitable[object]", value))
    return value


class TypeWire(Generic[T]):
    """Immutable description of a dependency — its token, creator, imports, and scope."""

    __slots__ = (
        "_convention",
        "_create_with",
        "_creator",
        "_frozen",
        "_imports",
        "_scope",
        "_token",
    )

    def __init__(
        self,
        token: _WireToken[T],
        creator: Callable[[], T | Awaitable[T]] | None,
        create_with: Callable[..., T | Awaitable[T]] | None,
        imports: dict[str, TypeWire[Any]],
        scope: Scope,
        convention: str,
    ) -> None:
        self._token = token
        self._creator = creator
        self._create_with = create_with
        self._imports = imports
        self._scope = scope
        self._convention = convention
        self._frozen = True

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("TypeWire instances are immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("TypeWire instances are immutable")

    def __repr__(self) -> str:
        import_keys: set[str] = set(self._imports.keys()) if self._imports else set()
        return (
            f"TypeWire(token={self._token.label!r}, scope={self._scope!r}, imports={import_keys!r})"
        )

    @property
    def token_label(self) -> str:
        """The string label identifying this wire's token."""
        return self._token.label

    @property
    def imports(self) -> dict[str, TypeWire[Any]]:
        """Read-only copy of this wire's import dependencies."""
        return dict(self._imports)

    @property
    def scope(self) -> Scope:
        """This wire's scope ("singleton" or "transient")."""
        return self._scope

    async def apply(
        self,
        container: ContainerAdapter,
        _path: list[_WireToken[object]] | None = None,
        _is_import: bool = False,
    ) -> None:
        """Register this wire and its imports into the container."""
        if _path is None:
            _path = []

        if self._token in _path:
            labels = [t.label for t in _path] + [self._token.label]
            raise CircularDependencyError(labels)

        # Skip already-registered tokens only during import recursion (SPEC 17.2)
        if _is_import and container.has(self._token):
            return

        _path.append(self._token)

        for imp_wire in self._imports.values():
            await imp_wire.apply(container, _path, _is_import=True)

        factory = self._make_factory(container)
        await container.register(self._token, factory, self._scope)

        _path.pop()

    def _make_factory(self, container: ContainerAdapter) -> Callable[[], Awaitable[T]]:
        wire = self

        async def factory() -> T:
            try:
                if wire._create_with is not None:
                    resolved: dict[str, object] = {}
                    for name, imp_wire in wire._imports.items():
                        resolved[name] = await container.resolve(imp_wire._token)
                    if wire._convention == "kwargs":
                        result = wire._create_with(**resolved)
                    else:
                        result = wire._create_with(resolved)
                    return cast("T", await _maybe_await(result))
                else:
                    return await _maybe_await(wire._creator())  # type: ignore[misc]
            except CreatorError:
                raise
            except Exception as e:
                raise CreatorError(wire._token.label, e) from e

        return factory

    async def get_instance(self, container: ContainerAdapter) -> T:
        """Resolve this wire's value from the container."""
        if not container.has(self._token):
            raise WireNotRegisteredError(self._token.label)
        return await container.resolve(self._token)

    def with_creator(
        self,
        fn: Callable[..., T | Awaitable[T]],
    ) -> TypeWire[T]:
        """Return a new wire with the creator replaced by *fn*."""
        arity = detect_creator_arity(fn)

        if arity == 2:
            original_wire = self

            if original_wire._create_with is not None:
                orig_create_with = original_wire._create_with
                orig_convention = original_wire._convention

                def new_create_with(deps: dict[str, object]) -> Awaitable[T]:
                    async def _call_with_original() -> T:
                        async def original_caller() -> T:
                            if orig_convention == "kwargs":
                                return cast("T", await _maybe_await(orig_create_with(**deps)))
                            else:
                                return cast("T", await _maybe_await(orig_create_with(deps)))

                        return cast("T", await _maybe_await(fn(None, original_caller)))

                    return _call_with_original()

                return TypeWire(
                    token=self._token,
                    creator=None,
                    create_with=new_create_with,
                    imports=dict(self._imports),
                    scope=self._scope,
                    convention="dict",
                )
            else:

                def wrapped_creator() -> Awaitable[T]:
                    async def _call_with_original() -> T:
                        async def original_caller() -> T:
                            return await _maybe_await(original_wire._creator())  # type: ignore[misc]

                        return cast("T", await _maybe_await(fn(None, original_caller)))

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

            def one_arg_creator() -> T | Awaitable[T]:
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
        """Synchronous wrapper around :meth:`apply`."""
        _check_no_running_loop()
        asyncio.run(self.apply(container))

    def get_instance_sync(self, container: ContainerAdapter) -> T:
        """Synchronous wrapper around :meth:`get_instance`."""
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
