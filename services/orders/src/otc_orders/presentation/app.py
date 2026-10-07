"""FastAPI app of otc_orders: the routes (liveness and readiness) and nothing that builds adapters.

`create_app(lifespan=...)` takes the lifespan from its caller. The host (`otc_orders/main.py`) is
the one that passes the real one, because the real lifespan runs the composition root, and the
composition root imports the Kafka client (the outbox relay's publisher), which no presentation
module may reach, directly or through a chain (import-linter `fact-producer-confinement`, R14).

`/health/live` says the process is up. `/health/ready` says the runtime the lifespan stored in
`app.state.runtime` reports no reason to be unready: 503 with the reasons while it does (a
transport task that ended, shutting down) and before the lifespan has started it.
"""

from typing import Protocol

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.types import Lifespan


class Readiness(Protocol):
    def unready_reasons(self) -> list[str]: ...


def create_app(*, lifespan: Lifespan[FastAPI] | None = None) -> FastAPI:
    app = FastAPI(title="otc-orders", lifespan=lifespan)
    app.state.runtime = None

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready", response_model=None)
    async def ready() -> JSONResponse:
        runtime: Readiness | None = app.state.runtime
        reasons = ["the service has not started"] if runtime is None else runtime.unready_reasons()
        if reasons:
            return JSONResponse({"status": "unready", "reasons": reasons}, status_code=503)
        return JSONResponse({"status": "ready"})

    return app
