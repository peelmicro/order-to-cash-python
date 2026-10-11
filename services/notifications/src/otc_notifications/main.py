"""The Notifications host: the ASGI app the server runs (`uvicorn otc_notifications.main:app`).

The lifespan loads the settings from the environment (`load_settings`, no argument: the host asks
for its own configuration) and starts the runtime (`start_runtime`): the dispatcher is validated,
every binding proven, the Kafka fact-consumer task started. Anything wrong raises HERE, so the
server does not come up. On exit the runtime stops its task (its in-flight record first) and closes
what it opened. Importing this module reads no configuration and opens nothing.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from otc_notifications.composition import load_settings, start_runtime
from otc_notifications.presentation.app import create_app as create_routes


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runtime = await start_runtime(load_settings())
    app.state.runtime = runtime
    try:
        yield
    finally:
        app.state.runtime = None
        await runtime.stop()


def create_app() -> FastAPI:
    return create_routes(lifespan=lifespan)


app = create_app()
