"""`GET /stock`, `POST /stock/replenish` (tag `fulfillment`)."""

from typing import Annotated

from fastapi import APIRouter, Query, Response

from otc_contracts.generated import openapi
from otc_gateway.application.messages import ListStockQuery, ReplenishStockCommand
from otc_gateway.presentation import contract
from otc_gateway.presentation.dependencies import Runtime
from otc_gateway.presentation.wire import ReplenishStockBody, wire_response

router = APIRouter(tags=["fulfillment"])


@router.get(
    "/stock",
    operation_id="listStock",
    summary="On-hand and reserved units.",
    response_model=openapi.StockPage,
    responses={**contract.UNAUTHORIZED, **contract.UPSTREAM_UNAVAILABLE},
)
async def list_stock(
    runtime: Runtime,
    company_code: Annotated[
        str | None, Query(alias="companyCode", min_length=1, max_length=20)
    ] = None,
    product_code: Annotated[
        str | None, Query(alias="productCode", min_length=1, max_length=30)
    ] = None,
    below_threshold: Annotated[bool, Query(alias="belowThreshold")] = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
) -> Response:
    stock = await runtime.dispatcher.ask(
        ListStockQuery(
            page=page,
            page_size=page_size,
            company_code=company_code,
            product_code=product_code,
            below_threshold=below_threshold,
        ),
        runtime.scope,
    )
    return wire_response(stock)


@router.post(
    "/stock/replenish",
    operation_id="replenishStock",
    summary="Add on-hand units.",
    response_model=openapi.ReplenishStockResponse,
    responses={
        **contract.BAD_REQUEST,
        **contract.UNAUTHORIZED,
        **contract.NOT_FOUND,
        **contract.UPSTREAM_UNAVAILABLE,
    },
)
async def replenish_stock(body: ReplenishStockBody, runtime: Runtime) -> Response:
    replenished = await runtime.dispatcher.send(ReplenishStockCommand(request=body), runtime.scope)
    return wire_response(replenished)
