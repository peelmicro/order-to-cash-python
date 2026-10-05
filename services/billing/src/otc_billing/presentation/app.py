"""FastAPI app of otc_billing: lifespan and liveness only."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Engines, pools and transport tasks belong to the lifespan: started here, awaited on exit.
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="otc-billing", lifespan=lifespan)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    return app


app = create_app()
