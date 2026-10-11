"""`ProjectionDelta`: what one fact changes in its order's read-model document, store-agnostic.

Frozen, slotted value objects with `int` minor units, `datetime` instants and `str` ids. Nothing
here knows a document, a pipeline or a wire format:
`infrastructure/persistence/delta_to_pipeline.py` renders it for MongoDB.
`None` in an `*_if_absent` field means "this fact does not write it".
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TimelineEntryDelta:
    event_id: str
    event_type: str
    occurred_at: datetime
    summary: str
    causation_id: str
    detail: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class ItemDelta:
    product_code: str
    quantity: int
    unit_price: int
    line_discount: int


@dataclass(frozen=True, slots=True)
class HeaderDelta:
    """The header only `order.placed.v1` carries. Master-data names are on no fact (`PR9`)."""

    order_reference: str
    order_date: datetime
    retailer_code: str
    retailer_gln: str
    company_code: str
    company_gln: str
    currency: str
    initial_amount: int
    initial_discount: int
    total_amount: int
    items: tuple[ItemDelta, ...]


@dataclass(frozen=True, slots=True)
class ProjectionDelta:
    order_id: str  # the fact's correlationId (R12)
    entry: TimelineEntryDelta
    implied_status: str | None  # None for the five status-less facts
    status_rank: int  # 0 when implied_status is None
    cancellation_reason_if_absent: str | None
    despatch_reference_if_absent: str | None
    invoice_reference_if_absent: str | None
    payment_reference_if_absent: str | None
    header: HeaderDelta | None  # only for order.placed.v1
