"""`GET /orders/stream` (tag `stream`, feature 26): server-sent saga progress (R55).

Mapped in its own router, included BEFORE `routes_orders.router` in `app.create_app`: the literal
`/orders/stream` must be matched before `/orders/{id}` or `stream` is read as an id (#8's ledger row
licenses its framework's precedence; FastAPI's router is order-sensitive, so this one is a guard,
`tests/unit/test_gateway_sse_route.py`). The stream is PROTECTED: it is not in `PUBLIC_OPERATIONS`.

`openapi.yaml` declares `200` and `401` only. A malformed `orderId` is answered `400` by the
framework's validation handler, like every other route's malformed parameter: an undeclared status
(backlog 215), not a new one.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from starlette.responses import Response

from otc_gateway.presentation import contract
from otc_gateway.presentation.dependencies import Runtime
from otc_gateway.presentation.event_stream import EventStreamResponse

router = APIRouter(tags=["stream"])


@router.get(
    "/orders/stream",
    operation_id="streamOrderEvents",
    summary="Live saga progress as server-sent events.",
    response_class=Response,
    responses={
        200: {
            "description": "The event stream.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        **contract.UNAUTHORIZED,
    },
)
async def stream_order_events(
    runtime: Runtime,
    order_id: Annotated[UUID | None, Query(alias="orderId")] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> Response:
    return EventStreamResponse(
        runtime.stream_hub,
        order_id=order_id,
        last_event_id=last_event_id,
        ping_interval_seconds=runtime.stream_ping_interval_seconds,
        now=runtime.clock.now,
    )
