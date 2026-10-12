"""`GET /stock` -> `fulfillment.stock.list`; `POST /stock/replenish` ->
`fulfillment.stock.replenish`."""

from otc_contracts.generated import asyncapi, openapi
from otc_gateway.application.messages import ListStockQuery, ReplenishStockCommand
from otc_gateway.application.rpc_subjects import STOCK_LIST, STOCK_REPLENISH
from otc_gateway.application.scope import GatewayScope
from otc_shared_kernel import UniqueId


def stock_item(view: asyncapi.StockView) -> openapi.StockItem:
    return openapi.StockItem(
        company_code=view.company_code,
        product_code=view.product_code,
        units=view.units,
        reserved_units=view.reserved_units,
        available_units=view.available_units,
        low_stock_threshold=view.low_stock_threshold,
    )


def page_info(page: asyncapi.PageInfo) -> openapi.PageInfo:
    return openapi.PageInfo(page=page.page, page_size=page.page_size, total=page.total)


class ListStockHandler:
    def __init__(self, scope: GatewayScope) -> None:
        self._scope = scope

    async def handle(self, query: ListStockQuery, /) -> openapi.StockPage:
        request_id = UniqueId.new().value
        reply = await self._scope.rpc.call(
            STOCK_LIST,
            asyncapi.StockListRequestPayload(
                page=query.page,
                page_size=query.page_size,
                company_code=query.company_code,
                product_code=query.product_code,
                below_threshold=query.below_threshold,
            ),
            asyncapi.StockListReplyPayload,
            correlation_id=request_id,
            request_id=request_id,
        )
        return openapi.StockPage(
            items=[stock_item(view) for view in reply.items], page=page_info(reply.page)
        )


class ReplenishStockHandler:
    def __init__(self, scope: GatewayScope) -> None:
        self._scope = scope

    async def handle(self, command: ReplenishStockCommand, /) -> openapi.ReplenishStockResponse:
        request = command.request
        request_id = UniqueId.new().value
        reply = await self._scope.rpc.call(
            STOCK_REPLENISH,
            asyncapi.StockReplenishRequestPayload(
                company_code=request.company_code,
                lines=[
                    asyncapi.Line3(product_code=line.product_code, units=line.units)
                    for line in request.lines
                ],
            ),
            asyncapi.StockReplenishReplyPayload,
            correlation_id=request_id,
            request_id=request_id,
        )
        return openapi.ReplenishStockResponse(items=[stock_item(view) for view in reply.items])
