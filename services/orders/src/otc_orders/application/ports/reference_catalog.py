"""`ReferenceCatalog`: the read-only reference data an order is placed against.

Each lookup answers `None` / `False` / a missing key for an unknown code; deciding that this is a
refusal is the handler's. Prices are `Money` (int minor units) in the product's own currency.
"""

from collections.abc import Collection, Mapping
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


class ReferenceCatalog(Protocol):
    async def find_retailer(self, retailer_code: str) -> PartyReference | None: ...

    async def find_company(self, company_code: str) -> PartyReference | None: ...

    async def currency_exists(self, currency_code: str) -> bool: ...

    async def find_products(
        self, product_codes: Collection[str]
    ) -> Mapping[str, ProductReference]: ...
