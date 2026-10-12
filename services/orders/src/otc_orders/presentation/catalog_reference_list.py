"""`catalog.reference.list` on the wire: request validation, the query, the reply.

Request validation is the wire contract's: `CatalogReferenceListRequestPayload` (generated from
`asyncapi.yaml`) has `kinds` (a non-empty list of `products | retailers | companies | currencies`,
omitted = all four) and `includeDisabled` (a boolean, omitted or null = false), both parsed
strictly. An absent body is the all-defaults request (every field is optional; #7's controller
treats an omitted body the same way, `catalog-reference-list.controller.spec.ts:33`). A body that
fails the schema (an unknown kind, an empty `kinds`, `"includeDisabled": "yes"`, a JSON value that
is not an object) is `InvalidCatalogReferenceListRequestError` -> `VALIDATION_FAILED`, never an
`INTERNAL_ERROR`.

The reply carries only the collections that were asked for (an absent one is omitted by the wire
serializer, an asked-for empty one is `[]`); prices are integer minor units with the product's own
currency code.
"""

from pydantic import ValidationError

from otc_contracts import from_wire_json, to_wire_json
from otc_contracts.generated.asyncapi import (
    CatalogReferenceListReplyPayload,
    CatalogReferenceListRequestPayload,
    CurrencyView,
    Kind,
    Party,
    Product,
    RpcError,
)
from otc_orders.application.ports.reference_catalog import (
    CurrencyListing,
    PartyListing,
    ProductListing,
)
from otc_orders.application.queries.list_reference_data import (
    ListReferenceDataQuery,
    ReferenceKind,
    ReferenceListing,
)


class InvalidCatalogReferenceListRequestError(Exception):
    """The request does not satisfy the wire schema."""


def decode_request(body: bytes) -> CatalogReferenceListRequestPayload:
    if not body:
        return CatalogReferenceListRequestPayload()
    try:
        return from_wire_json(CatalogReferenceListRequestPayload, body)
    except ValidationError as error:
        fields = ", ".join(
            dict.fromkeys(
                ".".join(str(part) for part in e["loc"]) or "(body)" for e in error.errors()
            )
        )
        raise InvalidCatalogReferenceListRequestError(
            f"catalog.reference.list request is invalid: {fields}."
        ) from None


def to_query(request: CatalogReferenceListRequestPayload) -> ListReferenceDataQuery:
    requested = request.kinds if request.kinds is not None else list(Kind)
    return ListReferenceDataQuery(
        kinds=frozenset(ReferenceKind(kind.value) for kind in requested),
        include_disabled=bool(request.include_disabled),
    )


def _product(listing: ProductListing) -> Product:
    return Product(
        code=listing.code,
        ean=listing.ean,
        name=listing.name,
        description=listing.description,
        price=listing.price.amount,
        currency=listing.price.currency,
        enabled=listing.enabled,
    )


def _party(listing: PartyListing) -> Party:
    return Party(
        code=listing.code,
        name=listing.name,
        country=listing.country,
        vat=listing.vat,
        gln=listing.gln,
        currency=listing.currency,
        enabled=listing.enabled,
    )


def _currency(listing: CurrencyListing) -> CurrencyView:
    return CurrencyView(
        code=listing.code,
        iso_number=listing.iso_number,
        symbol=listing.symbol,
        decimal_points=listing.decimal_points,
    )


def to_reply(listing: ReferenceListing) -> CatalogReferenceListReplyPayload:
    return CatalogReferenceListReplyPayload(
        products=None if listing.products is None else [_product(p) for p in listing.products],
        retailers=None if listing.retailers is None else [_party(p) for p in listing.retailers],
        companies=None if listing.companies is None else [_party(p) for p in listing.companies],
        currencies=(
            None if listing.currencies is None else [_currency(c) for c in listing.currencies]
        ),
    )


def encode(model: RpcError | CatalogReferenceListReplyPayload) -> bytes:
    return to_wire_json(model).encode("utf-8")
