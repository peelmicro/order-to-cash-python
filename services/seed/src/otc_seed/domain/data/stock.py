"""Initial Fulfillment stock: 215 rows, derived from the sagas and a per-company baseline.

Derived straight from `SAGAS` (the single source of truth) rather than duplicating quantities, so
the stock table and the fabricated reservation history cannot drift apart. A `consumed` reservation
permanently removed units (the despatch happened); a `released` one never removed any. Every
`reserved_units` is 0: every seeded saga is already terminal, nothing is left reserved.

Baseline: the sagas touch only some of the 22 companies; a live order against any other company
could never get past `stock.reserve` (`NOT_FOUND`, parked forever). Every company the saga-derived
pairs do not cover therefore gets a full row per PRODUCT, so no company can hit that wall whatever
product a later demo order names. Purely additive: no saga-derived id, company or quantity changes.
"""

from dataclasses import dataclass

from otc_seed.domain.data.companies import COMPANIES
from otc_seed.domain.data.products import PRODUCTS
from otc_seed.domain.data.sagas import SAGAS, stock_row_id

INITIAL_UNITS_ON_HAND = 500
LOW_STOCK_THRESHOLD = 20


@dataclass(frozen=True, slots=True)
class StockSeed:
    id: str
    company_code: str
    product_code: str
    units: int
    reserved_units: int
    low_stock_threshold: int


def _saga_derived() -> tuple[StockSeed, ...]:
    consumed: dict[tuple[str, str], int] = {}
    for saga in SAGAS:
        for reservation in saga.reservations:
            key = (reservation.company_code, reservation.product_code)
            consumed.setdefault(key, 0)
            if reservation.status == "consumed":
                consumed[key] += reservation.units
    rows: list[StockSeed] = []
    for (company_code, product_code), used in consumed.items():
        units = INITIAL_UNITS_ON_HAND - used
        if units < 0:
            raise ValueError(f"stock ({company_code}, {product_code}) would go negative")
        rows.append(
            StockSeed(
                id=stock_row_id(company_code, product_code),
                company_code=company_code,
                product_code=product_code,
                units=units,
                reserved_units=0,
                low_stock_threshold=LOW_STOCK_THRESHOLD,
            )
        )
    return tuple(rows)


_SAGA_DERIVED = _saga_derived()
_SAGA_COVERED_COMPANIES = frozenset(row.company_code for row in _SAGA_DERIVED)

_BASELINE: tuple[StockSeed, ...] = tuple(
    StockSeed(
        id=stock_row_id(company.code, product.code),
        company_code=company.code,
        product_code=product.code,
        units=INITIAL_UNITS_ON_HAND,
        reserved_units=0,
        low_stock_threshold=LOW_STOCK_THRESHOLD,
    )
    for company in COMPANIES
    if company.code not in _SAGA_COVERED_COMPANIES
    for product in PRODUCTS
)

# #7 sorts by `(companyCode + productCode).localeCompare(...)`; with ASCII-only upper-case company
# codes and `PRD-nnnn` product codes a plain string sort of the same key agrees on every row (the
# test pins the order against #7's dump).
STOCK: tuple[StockSeed, ...] = tuple(
    sorted(_SAGA_DERIVED + _BASELINE, key=lambda row: row.company_code + row.product_code)
)
