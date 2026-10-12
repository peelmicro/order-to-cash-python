"""`POST /orders`, `GET /orders`, `GET /orders/{id}`, `POST /orders/{id}/cancel` (tag `orders`).

`GET /orders/stream` is feature 26's (`gateway_sse_push`): a literal route that must be mapped
BEFORE `GET /orders/{id}` when it lands, or `stream` is read as an id.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from otc_contracts.generated import openapi
from otc_gateway.application.messages import (
    CancelOrderCommand,
    GetOrderQuery,
    ListOrdersQuery,
    PlaceOrderCommand,
)
from otc_gateway.application.order_queries import PROJECTION_PENDING_RETRY_AFTER_MS
from otc_gateway.application.ports.order_read_model import OrderListFilter
from otc_gateway.presentation import contract
from otc_gateway.presentation.dependencies import Runtime
from otc_gateway.presentation.wire import CancelOrderBody, PlaceOrderBody, wire_response

router = APIRouter(tags=["orders"])

PartyCodeQuery = Annotated[str | None, Query(min_length=1, max_length=20)]


@router.post(
    "/orders",
    operation_id="placeOrder",
    summary="Place an order.",
    status_code=201,
    response_model=openapi.PlaceOrderResponse,
    responses={
        **contract.BAD_REQUEST,
        **contract.UNAUTHORIZED,
        **contract.declared(
            409, openapi.StockUnavailableProblem, "The availability check failed at acceptance."
        ),
        **contract.DOMAIN_ERROR,
        **contract.UPSTREAM_UNAVAILABLE,
    },
)
async def place_order(
    body: PlaceOrderBody,
    runtime: Runtime,
    idempotency_key: Annotated[UUID | None, Header(alias="Idempotency-Key")] = None,
) -> Response:
    placed = await runtime.dispatcher.send(
        PlaceOrderCommand(request=body, idempotency_key=idempotency_key), runtime.scope
    )
    return wire_response(
        placed,
        201,
        {"Location": f"/orders/{placed.order_id}", "X-Correlation-Id": str(placed.order_id)},
    )


@router.get(
    "/orders",
    operation_id="listOrders",
    summary="List orders from the read model.",
    response_model=openapi.OrderSummaryPage,
    responses={**contract.BAD_REQUEST, **contract.UNAUTHORIZED},
)
async def list_orders(
    runtime: Runtime,
    status: Annotated[list[openapi.OrderStatus] | None, Query()] = None,
    retailer_code: Annotated[PartyCodeQuery, Query(alias="retailerCode")] = None,
    company_code: Annotated[PartyCodeQuery, Query(alias="companyCode")] = None,
    order_reference: Annotated[
        str | None, Query(alias="orderReference", pattern=r"^ORD-[0-9]{6,}$")
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
) -> Response:
    result = await runtime.dispatcher.ask(
        ListOrdersQuery(
            order_filter=OrderListFilter(
                statuses=tuple(s.value for s in status or []),
                retailer_code=retailer_code,
                company_code=company_code,
                order_reference=order_reference,
                page=page,
                page_size=page_size,
            )
        ),
        runtime.scope,
    )
    return wire_response(result)


@router.get(
    "/orders/{id}",
    operation_id="getOrder",
    summary="Fetch one order with its full timeline.",
    response_model=openapi.OrderDetail,
    responses={
        **contract.declared(202, openapi.ProjectionPending, "The order is not projected yet."),
        **contract.UNAUTHORIZED,
        **contract.NOT_FOUND,
    },
)
async def get_order(id: UUID, runtime: Runtime) -> Response:
    found = await runtime.dispatcher.ask(GetOrderQuery(order_id=id), runtime.scope)
    if isinstance(found, openapi.ProjectionPending):
        # R55: an id the caller has just been given, not yet projected: explicit, never a 404
        return wire_response(
            found, 202, {"Retry-After": str(PROJECTION_PENDING_RETRY_AFTER_MS // 1000)}
        )
    return wire_response(found)


@router.post(
    "/orders/{id}/cancel",
    operation_id="cancelOrder",
    summary="Operator cancellation, pre-despatched only.",
    status_code=202,
    response_model=openapi.CancelOrderResponse,
    responses={
        **contract.UNAUTHORIZED,
        **contract.NOT_FOUND,
        **contract.declared(409, openapi.Problem, "The order is despatched or later, or terminal."),
        **contract.UPSTREAM_UNAVAILABLE,
    },
)
async def cancel_order(
    id: UUID,
    runtime: Runtime,
    body: CancelOrderBody = None,
) -> Response:
    cancelled = await runtime.dispatcher.send(
        CancelOrderCommand(order_id=id, note=None if body is None else body.note), runtime.scope
    )
    return wire_response(cancelled, 202)
