"""What `StockItem.rehydrate` takes and `to_snapshot` returns: a stored item as business values.

Built by the repository's row mapper (infrastructure); keyword-constructed. The reservations are
only those LOADED with the item (the order being handled), as in #7 and #8. Timestamps are not here:
`created_at` / `updated_at` are the mapper's (the domain reads no clock).
"""

from dataclasses import dataclass
from datetime import datetime

from otc_fulfillment.domain.reservation import ReservationStatus
from otc_shared_kernel import DespatchReference, UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ReservationSnapshot:
    id: UniqueId
    stock_id: UniqueId
    product_code: str
    order_reference: str
    retailer_code: str
    units: int
    status: ReservationStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class StockItemSnapshot:
    id: UniqueId
    company_code: str
    product_code: str
    units: int
    reserved_units: int
    low_stock_threshold: int
    reservations: tuple[ReservationSnapshot, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class DespatchLineSnapshot:
    id: UniqueId
    product_code: str
    units: int


@dataclass(frozen=True, slots=True, kw_only=True)
class DespatchSnapshot:
    """A despatch advice as business values: what `DespatchAdvice.to_snapshot` returns and the
    repository's `find_by_order_reference` rebuilds from the rows (F8's repeat answers with it).
    `lines` are in the canonical order (`despatch_advice.line_order_key`)."""

    id: UniqueId
    despatch_reference: DespatchReference
    despatch_date: datetime
    order_reference: str
    company_code: str
    retailer_code: str
    lines: tuple[DespatchLineSnapshot, ...]
