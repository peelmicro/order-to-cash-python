"""FastAPI app of otc_gateway: the routes, the middlewares and the exception handlers, no adapters.

`create_app(lifespan=...)` takes the lifespan from its caller. The host (`otc_gateway.main`) passes
the real one, because the real lifespan runs the composition root; this module imports no adapter.
The framework's own documentation routes are off (`/docs` is the contract's: a rendering of the
COMMITTED `openapi.yaml`, `routes_ops.docs`; `/redoc` and `/openapi.json` are not in the contract,
so they are not served): every route this app has is a route `openapi.yaml` declares, which
`tests/unit/test_openapi_conformance.py` holds in both directions.
"""

from datetime import UTC, datetime
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Lifespan

from otc_gateway.presentation import (
    contract,
    routes_auth,
    routes_billing,
    routes_catalog,
    routes_fulfillment,
    routes_ops,
    routes_orders,
    routes_stream,
)
from otc_gateway.presentation.asgi import (
    BearerAuthMiddleware,
    CorrelationMiddleware,
    ProblemMiddleware,
    TelemetryMiddleware,
    clock_of,
    correlation_of,
    problem_headers,
)
from otc_gateway.presentation.openapi_shape import shaped_openapi
from otc_gateway.presentation.problems import (
    ProblemSpec,
    problem_body,
    validation_failed,
)


def _problem_response(request: Request, spec: ProblemSpec) -> Response:
    clock = clock_of(request.scope)
    body = problem_body(
        spec, correlation_of(request.scope), datetime.now(UTC) if clock is None else clock.now()
    )
    return Response(
        content=body,
        status_code=spec.status,
        headers={k.decode("latin-1"): v.decode("latin-1") for k, v in problem_headers(spec, body)},
    )


async def _validation_handler(request: Request, error: Exception) -> Response:
    # Field and message only. `input` (the submitted value) is never echoed: a login body holds a
    # password.
    failure = cast("RequestValidationError", error)
    fields = [
        (".".join(str(part) for part in e["loc"][1:]) or str(e["loc"][0]), str(e["msg"]))
        for e in failure.errors()
    ]
    return _problem_response(request, validation_failed(fields))


async def _http_handler(request: Request, error: Exception) -> Response:
    known = {
        404: ("NOT_FOUND", "No such resource"),
        405: ("METHOD_NOT_ALLOWED", "Method not allowed"),
        503: ("UPSTREAM_UNAVAILABLE", "The service has not started"),
    }
    failure = cast("StarletteHTTPException", error)
    code, title = known.get(failure.status_code, ("HTTP_ERROR", "The request could not be served"))
    spec = ProblemSpec(failure.status_code, code, title, title + ".", dict(failure.headers or {}))
    return _problem_response(request, spec)


# FastAPI 0.142 creates server spans and `http.server.*` metrics whenever a global provider exists
# and adds OTLP exporters from `OTEL_EXPORTER_OTLP_ENDPOINT` at lifespan startup. This service's
# telemetry is its runtime's own (`infrastructure/observability/telemetry.py`), so every FastAPI
# facility is switched off, explicitly, in the call below
# (`tests/architecture/test_telemetry_wiring.py`).
def create_app(*, lifespan: Lifespan[FastAPI] | None = None) -> FastAPI:
    app = FastAPI(
        title="otc-gateway",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        separate_input_output_schemas=False,
        responses=contract.UNLISTED_PROBLEM,
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        },
    )
    app.state.runtime = None
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    for router in (
        routes_auth.router,
        # BEFORE routes_orders: the literal /orders/stream must win over /orders/{id}
        routes_stream.router,
        routes_orders.router,
        routes_fulfillment.router,
        routes_billing.router,
        routes_catalog.router,
        routes_ops.router,
    ):
        app.include_router(router)
    # Last added is outermost: telemetry -> correlation -> problems -> bearer -> routes.
    app.add_middleware(BearerAuthMiddleware)
    app.add_middleware(ProblemMiddleware)
    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(TelemetryMiddleware)

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = shaped_openapi(app)
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
    return app
