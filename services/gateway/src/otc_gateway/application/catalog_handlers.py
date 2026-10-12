"""`GET /catalog/{products,retailers,companies}` -> `catalog.reference.list` (one kind each)."""

from otc_contracts.generated import asyncapi, openapi
from otc_gateway.application.messages import (
    ListCompaniesQuery,
    ListProductsQuery,
    ListRetailersQuery,
)
from otc_gateway.application.rpc_subjects import CATALOG_REFERENCE_LIST
from otc_gateway.application.scope import GatewayScope
from otc_shared_kernel import UniqueId


async def _reference_list(
    scope: GatewayScope, kind: asyncapi.Kind, include_disabled: bool
) -> asyncapi.CatalogReferenceListReplyPayload:
    request_id = UniqueId.new().value
    return await scope.rpc.call(
        CATALOG_REFERENCE_LIST,
        asyncapi.CatalogReferenceListRequestPayload(
            kinds=[kind], include_disabled=include_disabled
        ),
        asyncapi.CatalogReferenceListReplyPayload,
        correlation_id=request_id,
        request_id=request_id,
    )


def _party(party: asyncapi.Party) -> openapi.Party:
    return openapi.Party(
        code=party.code,
        name=party.name,
        country=party.country,
        vat=party.vat,
        gln=party.gln,
        currency=party.currency,
        enabled=party.enabled,
    )


class ListProductsHandler:
    def __init__(self, scope: GatewayScope) -> None:
        self._scope = scope

    async def handle(self, query: ListProductsQuery, /) -> list[openapi.Product]:
        reply = await _reference_list(self._scope, asyncapi.Kind.products, query.include_disabled)
        return [
            openapi.Product(
                code=product.code,
                ean=product.ean,
                name=product.name,
                description=product.description,
                price=product.price,
                currency=product.currency,
                enabled=product.enabled,
            )
            for product in reply.products or []
        ]


class ListRetailersHandler:
    def __init__(self, scope: GatewayScope) -> None:
        self._scope = scope

    async def handle(self, query: ListRetailersQuery, /) -> list[openapi.Party]:
        reply = await _reference_list(self._scope, asyncapi.Kind.retailers, query.include_disabled)
        return [_party(party) for party in reply.retailers or []]


class ListCompaniesHandler:
    def __init__(self, scope: GatewayScope) -> None:
        self._scope = scope

    async def handle(self, query: ListCompaniesQuery, /) -> list[openapi.Party]:
        reply = await _reference_list(self._scope, asyncapi.Kind.companies, query.include_disabled)
        return [_party(party) for party in reply.companies or []]
