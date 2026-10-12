"""`ReferenceCatalog`: the read-only reference data an order is placed against.

Each lookup answers `None` / `False` / a missing key for an unknown code; deciding that this is a
refusal is the handler's. Prices are `Money` (int minor units) in the product's own currency.

The four `list_*` methods are the SAME port's listing side (feature 40, `catalog.reference.list`):
one adapter answers the place-order lookups and the listings, so the tables are read from one place.
Each lists ordered by `code`; a row with `disabled_at` set is listed only when `include_disabled`.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from otc_shared_kernel import GLN, Money


@dataclass(frozen=True, slots=True)
class PartyReference:
    code: str
    gln: GLN


@dataclass(frozen=True, slots=True)
class ProductReference:
    product_code: str
    description: str | None
    price: Money


@dataclass(frozen=True, slots=True)
class ProductListing:
    code: str
    ean: str
    name: str
    description: str
    price: Money
    enabled: bool


@dataclass(frozen=True, slots=True)
class PartyListing:
    """A retailer or a company as the listing shows it (`gln` is the stored text)."""

    code: str
    name: str
    country: str
    vat: str
    gln: str
    currency: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class CurrencyListing:
    code: str
    iso_number: str
    symbol: str
    decimal_points: int


class ReferenceCatalog(Protocol):
    async def find_retailer(self, retailer_code: str) -> PartyReference | None: ...

    async def find_company(self, company_code: str) -> PartyReference | None: ...

    async def currency_exists(self, currency_code: str) -> bool: ...

    async def find_products(
        self, product_codes: Collection[str]
    ) -> Mapping[str, ProductReference]: ...

    async def list_products(self, *, include_disabled: bool) -> Sequence[ProductListing]: ...

    async def list_retailers(self, *, include_disabled: bool) -> Sequence[PartyListing]: ...

    async def list_companies(self, *, include_disabled: bool) -> Sequence[PartyListing]: ...

    async def list_currencies(self) -> Sequence[CurrencyListing]: ...
