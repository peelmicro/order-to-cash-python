"""The projector host: the ASGI app the server runs (`uvicorn otc_projector.main:app`).

The lifespan loads the settings from the environment (`load_settings`, no argument: the host asks
for its own configuration) and starts the runtime (`start_runtime`): the dispatcher is validated,
MongoDB pinged, the indexes created and verified, the documents migrated, NATS connected within a
bound, and the Kafka fact-consumer task started. Anything wrong raises HERE, so the server does not
come up. On exit the runtime stops its task (its in-flight record first, then a cancel after a
bounded grace) and closes what it opened. Importing this module reads no configuration and opens
nothing.

It lives beside `composition.py`, outside the layers: the `fact-producer-confinement` contract (R14)
forbids `presentation` from reaching aiokafka, even through the composition root.

Importing this module also installs the JSON log handler (`install_json_logging`, `R58`) BEFORE
`create_app()`: uvicorn logs `Started server process` after importing the app and before the
lifespan runs, so the lifespan is too late for that line. The install reads no configuration and
opens no resource, so the sentence above stays true.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from otc_projector.composition import load_settings, start_runtime
from otc_projector.infrastructure.observability.logging import install_json_logging
from otc_projector.presentation.app import create_app as create_routes


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


install_json_logging("projector")
app = create_app()
