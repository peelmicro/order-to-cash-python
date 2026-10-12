"""`GET /health/live`, `GET /health/ready`, `GET /docs` (tag `ops`); all three are public."""

import asyncio
import html

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

from otc_contracts.generated import openapi
from otc_gateway.presentation import contract
from otc_gateway.presentation.dependencies import Runtime
from otc_gateway.presentation.wire import wire_response

router = APIRouter(tags=["ops"])


@router.get(
    "/health/live",
    operation_id="healthLive",
    summary="Liveness probe.",
    response_model=openapi.HealthResponse,
)
async def live() -> Response:
    # R60: consults NOTHING. A gateway whose broker is unreachable is not ready, but it is alive.
    return wire_response(openapi.HealthResponse(status=openapi.Status.up))


@router.get(
    "/health/ready",
    operation_id="healthReady",
    summary="Readiness probe.",
    response_model=openapi.HealthResponse,
    responses={
        **contract.declared(503, openapi.HealthResponse, "At least one dependency is down.")
    },
)
async def ready(runtime: Runtime) -> Response:
    # R60: the Gateway owns no write model; its dependencies are the RPC transport and the read
    # model. Each check is bounded, and they run together so a hung one costs one bound, not two.
    results = await asyncio.gather(*(check.run() for check in runtime.health_checks))
    up = all(result.up for result in results)
    body = openapi.HealthResponse(
        status=openapi.Status.up if up else openapi.Status.down,
        checks={
            result.name: openapi.Checks(
                status=openapi.Status.up if result.up else openapi.Status.down,
                detail=result.detail,
            )
            for result in results
        },
    )
    return wire_response(body, 200 if up else 503)


@router.get(
    "/docs",
    operation_id="apiDocs",
    summary="Interactive API documentation.",
    response_class=HTMLResponse,
    # `default` is written out here: the application-level one is a model, which the framework would
    # serve in this route's own media type (`text/html`), and the contract's is a Problem.
    responses={
        200: {"description": "The documentation page.", "content": {"text/html": {}}},
        "default": {
            "description": "Any status this operation does not list. The body is always a Problem.",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
    },
)
async def docs(runtime: Runtime) -> HTMLResponse:
    """A human-facing rendering of the COMMITTED contract (`specs/shared/openapi.yaml`, loaded at
    boot), not of FastAPI's generated document. It needs no script and no network resource."""
    return HTMLResponse(render_docs(runtime.openapi_document))


def render_docs(openapi_yaml: str) -> str:
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        "<title>Order-To-Cash - Gateway REST API</title>\n"
        "<style>body{font-family:monospace;margin:2rem}pre{white-space:pre-wrap}</style>\n"
        "</head>\n<body>\n<h1>Order-To-Cash - Gateway REST API</h1>\n"
        "<p>The contract this gateway implements, verbatim from "
        "<code>specs/shared/openapi.yaml</code>.</p>\n"
        f"<pre>{html.escape(openapi_yaml)}</pre>\n</body>\n</html>\n"
    )
