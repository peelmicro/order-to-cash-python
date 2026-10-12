"""`GET /orders` and `GET /orders/{id}`: served from the read model ONLY (R54).

This module is the one the import-linter contract `gateway-order-queries-read-model-only` guards:
it may import the read-model port, the window and the views, and nothing that reaches NATS, an RPC
client, the full `GatewayScope` or another context's write model. Its handlers take an
`OrderReadScope`, which has nothing else to offer.
"""

from otc_contracts.generated import openapi
from otc_gateway.application.errors import GatewayNotFoundError
from otc_gateway.application.messages import GetOrderQuery, ListOrdersQuery
from otc_gateway.application.order_views import order_detail, order_summary
from otc_gateway.application.ports.order_read_model import OrderReadScope

PROJECTION_PENDING_RETRY_AFTER_MS = 2000


class ListOrdersHandler:
    def __init__(self, scope: OrderReadScope) -> None:
        self._read_model = scope.read_model

    async def handle(self, query: ListOrdersQuery, /) -> openapi.OrderSummaryPage:
        page = await self._read_model.list_orders(query.order_filter)
        return openapi.OrderSummaryPage(
            items=[order_summary(header) for header in page.items],
            page=openapi.PageInfo(
                page=query.order_filter.page,
                page_size=query.order_filter.page_size,
                total=page.total,
            ),
        )


class GetOrderHandler:
    def __init__(self, scope: OrderReadScope) -> None:
        self._read_model = scope.read_model
        self._issued_orders = scope.issued_orders

    async def handle(
        self, query: GetOrderQuery, /
    ) -> openapi.OrderDetail | openapi.ProjectionPending:
        order = await self._read_model.find_by_id(query.order_id)
        if order is not None:
            return order_detail(order)
        if self._issued_orders.is_recently_issued(query.order_id):
            return openapi.ProjectionPending(
                order_id=query.order_id,
                status="projection_pending",
                message=(
                    "The order was accepted and is not projected yet. "
                    "Subscribe to /orders/stream or retry."
                ),
                retry_after_ms=PROJECTION_PENDING_RETRY_AFTER_MS,
            )
        raise GatewayNotFoundError(f"no order for id {str(query.order_id)!r}")
