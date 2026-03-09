from __future__ import annotations

import logging
from typing import Any, TypeVar

from fastapi import Depends, Request

from typewirepy.wire import TypeWire

T = TypeVar("T")

CONTAINER_ATTR = "typewire_container"

logger = logging.getLogger(__name__)


def WireDepends(wire: TypeWire[T]) -> Any:
    """FastAPI dependency that resolves a wire from the request's container.

    The container must be stored on ``app.state.typewire_container``
    (e.g. during the FastAPI lifespan).

    Usage::

        @app.get("/")
        async def endpoint(svc: MyService = WireDepends(service_wire)):
            ...
    """

    async def _resolver(request: Request) -> T:
        container = getattr(request.app.state, CONTAINER_ATTR, None)
        if container is None:
            logger.error(
                "No TypeWireContainer found on app.state.%s. "
                "Set it during your FastAPI lifespan, e.g.:\n\n"
                "    @asynccontextmanager\n"
                "    async def lifespan(app: FastAPI):\n"
                "        async with TypeWireContainer() as container:\n"
                "            await wires.apply(container)\n"
                "            app.state.%s = container\n"
                "            yield\n",
                CONTAINER_ATTR,
                CONTAINER_ATTR,
            )
            raise RuntimeError(
                f"No TypeWireContainer on app.state.{CONTAINER_ATTR}. "
                "See logs for setup instructions."
            )
        return await wire.get_instance(container)

    return Depends(_resolver)
