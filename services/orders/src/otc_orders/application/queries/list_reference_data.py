"""`ListReferenceDataQuery`: the reference lists behind `catalog.reference.list` (feature 40).

Reads through `scope.catalog`: the SAME `ReferenceCatalog` the place-order handler resolves, so the
listing and the order's lookups cannot read the reference tables differently. It issues reads only:
no unit of work is opened, nothing is written or locked. A collection that was not asked for stays
`None` (the wire omits it); one that was asked for and is empty is an empty tuple.
"""

from dataclasses import dataclass
from enum import StrEnum

from otc_cqrs import Query
from otc_orders.application.ports.reference_catalog import (
    CurrencyListing,
    PartyListing,
    ProductListing,
)
from otc_orders.application.scope import OrdersScope


class ReferenceKind(StrEnum):
    PRODUCTS = "products"
    RETAILERS = "retailers"
    COMPANIES = "companies"
    CURRENCIES = "currencies"


@dataclass(frozen=True, slots=True)
class ReferenceListing:
    products: tuple[ProductListing, ...] | None = None
    retailers: tuple[PartyListing, ...] | None = None
    companies: tuple[PartyListing, ...] | None = None
    currencies: tuple[CurrencyListing, ...] | None = None


@dataclass(frozen=True, slots=True)
class ListReferenceDataQuery(Query[ReferenceListing]):
    kinds: frozenset[ReferenceKind]
    include_disabled: bool


class ListReferenceDataQueryHandler:
    def __init__(self, scope: OrdersScope) -> None:
        self._scope = scope

    async def handle(self, query: ListReferenceDataQuery, /) -> ReferenceListing:
        catalog = self._scope.catalog
        include_disabled = query.include_disabled
        kinds = query.kinds
        return ReferenceListing(
            products=(
                tuple(await catalog.list_products(include_disabled=include_disabled))
                if ReferenceKind.PRODUCTS in kinds
                else None
            ),
            retailers=(
                tuple(await catalog.list_retailers(include_disabled=include_disabled))
                if ReferenceKind.RETAILERS in kinds
                else None
            ),
            companies=(
                tuple(await catalog.list_companies(include_disabled=include_disabled))
                if ReferenceKind.COMPANIES in kinds
                else None
            ),
            currencies=(
                tuple(await catalog.list_currencies())
                if ReferenceKind.CURRENCIES in kinds
                else None
            ),
        )
