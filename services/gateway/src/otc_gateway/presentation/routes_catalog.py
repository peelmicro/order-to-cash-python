"""`GET /catalog/products`, `/catalog/retailers`, `/catalog/companies` (tag `catalog`)."""

from typing import Annotated

from fastapi import APIRouter, Query, Response

from otc_gateway.application.messages import (
    ListCompaniesQuery,
    ListProductsQuery,
    ListRetailersQuery,
)
from otc_gateway.presentation import contract
from otc_gateway.presentation.dependencies import Runtime
from otc_gateway.presentation.wire import (
    CompaniesResponse,
    ProductsResponse,
    RetailersResponse,
    wire_response,
)

router = APIRouter(tags=["catalog"])

IncludeDisabled = Annotated[bool, Query(alias="includeDisabled")]


@router.get(
    "/catalog/products",
    operation_id="listProducts",
    summary="Catalogue products for the place-order form.",
    response_model=ProductsResponse,
    responses={**contract.UNAUTHORIZED, **contract.UPSTREAM_UNAVAILABLE},
)
async def list_products(runtime: Runtime, include_disabled: IncludeDisabled = False) -> Response:
    items = await runtime.dispatcher.ask(
        ListProductsQuery(include_disabled=include_disabled), runtime.scope
    )
    return wire_response(ProductsResponse(items=items))


@router.get(
    "/catalog/retailers",
    operation_id="listRetailers",
    summary="Retailers (buyers) for the place-order form.",
    response_model=RetailersResponse,
    responses={**contract.UNAUTHORIZED, **contract.UPSTREAM_UNAVAILABLE},
)
async def list_retailers(runtime: Runtime, include_disabled: IncludeDisabled = False) -> Response:
    items = await runtime.dispatcher.ask(
        ListRetailersQuery(include_disabled=include_disabled), runtime.scope
    )
    return wire_response(RetailersResponse(items=items))


@router.get(
    "/catalog/companies",
    operation_id="listCompanies",
    summary="Companies (suppliers) for the place-order form.",
    response_model=CompaniesResponse,
    responses={**contract.UNAUTHORIZED, **contract.UPSTREAM_UNAVAILABLE},
)
async def list_companies(runtime: Runtime, include_disabled: IncludeDisabled = False) -> Response:
    items = await runtime.dispatcher.ask(
        ListCompaniesQuery(include_disabled=include_disabled), runtime.scope
    )
    return wire_response(CompaniesResponse(items=items))
