"""FastAPI app of otc_orders: the routes (liveness and readiness) and nothing that builds adapters.

`create_app(lifespan=...)` takes the lifespan from its caller. The host (`otc_orders/main.py`) is
the one that passes the real one, because the real lifespan runs the composition root, and the
composition root imports the Kafka client (the outbox relay's publisher), which no presentation
module may reach, directly or through a chain (import-linter `fact-producer-confinement`, R14).

`/health/live` answers `200 {"status":"up"}` and consults nothing (`R60`). `/health/ready` answers
a `HealthResponse` built from the runtime the lifespan stored in `app.state.runtime`: one bounded
check per dependency, `200` when every one is up and `503` naming the ones that are down (a
dependency that does not answer within its bound, a transport task that ended, shutting down).
Before the lifespan has started, and after it has ended, it is `503` with no check.
"""

from collections.abc import Sequence
from typing import Protocol

from fastapi import FastAPI, Response
from starlette.types import Lifespan

from otc_contracts import to_wire_json
from otc_contracts.generated import openapi
from otc_orders.infrastructure.health.checks import CheckResult, health_body


class Readiness(Protocol):
    async def readiness(self) -> Sequence[CheckResult]: ...


def _wire(body: openapi.HealthResponse, status: int) -> Response:
    return Response(content=to_wire_json(body), media_type="application/json", status_code=status)


# FastAPI 0.142 creates server spans and `http.server.*` metrics whenever a global provider exists
# and adds OTLP exporters from `OTEL_EXPORTER_OTLP_ENDPOINT` at lifespan startup. This service's
# telemetry is its runtime's own (`infrastructure/observability/telemetry.py`), so every FastAPI
# facility is switched off, explicitly, in the call below
# (`tests/architecture/test_telemetry_wiring.py`).
def create_app(*, lifespan: Lifespan[FastAPI] | None = None) -> FastAPI:
    app = FastAPI(
        title="otc-orders",
        lifespan=lifespan,
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        },
    )
    app.state.runtime = None

    @app.get("/health/live", response_model=None)
    async def live() -> Response:
        # R60: consults NOTHING. A service whose dependency is unreachable is not ready, but alive.
        return _wire(openapi.HealthResponse(status=openapi.Status.up), 200)

    @app.get("/health/ready", response_model=None)
    async def ready() -> Response:
        runtime: Readiness | None = app.state.runtime
        if runtime is None:
            # Before the lifespan has started (and after it has ended): no check exists to name.
            return _wire(openapi.HealthResponse(status=openapi.Status.down, checks={}), 503)
        results = await runtime.readiness()
        return _wire(health_body(results), 200 if all(result.up for result in results) else 503)

    return app
