"""The Gateway host: the ASGI app the server runs (`python -m otc_gateway`, or
`uvicorn otc_gateway.main:app --port N` by hand).

The lifespan loads the settings from the environment (`load_settings`, no argument: the host asks
for its own configuration) and starts the runtime (`start_runtime`): the dispatcher is validated,
the contract read, MongoDB pinged and NATS connected within a bound. Anything wrong raises HERE,
so the server does not come up. On exit the runtime closes what it opened. Importing this module
reads no configuration and opens nothing.

It lives beside `composition.py`, outside the layers, like every other service's host.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from otc_gateway.composition import load_settings, start_runtime
from otc_gateway.presentation.app import create_app as create_routes


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    running = await start_runtime(load_settings())
    app.state.runtime = running.runtime
    try:
        yield
    finally:
        app.state.runtime = None
        await running.stop()


def create_app() -> FastAPI:
    return create_routes(lifespan=lifespan)


app = create_app()
