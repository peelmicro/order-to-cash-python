"""The facts of the Fulfillment service: the three stock facts (`design.md` 5.4: reserved, rejected,
released) and `order.despatched.v1` (feature 18: the despatch advice's one fact).

Domain types only (`UniqueId`, `str`, `int`, `datetime`), never `otc_contracts` models: mapping to
the wire envelope is `infrastructure/outbox/payloads.py`. Frozen, slotted, keyword-only; every
sequence is a `tuple`, because a frozen dataclass holding a `list` is still mutable through it.
Reasons are plain `Enum`s with written-out tokens, as `ReservationStatus` is.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import ClassVar

from otc_shared_kernel import DespatchReference, UniqueId


class RejectionReason(Enum):
    INSUFFICIENT_STOCK = "insufficient_stock"
    UNKNOWN_PRODUCT = "unknown_product"


class ReleaseReason(Enum):
    CREDIT_REJECTED = "credit_rejected"
    ORDER_CANCELLED = "order_cancelled"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReservationRef:
    reservation_id: UniqueId
    product_code: str
    units: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Shortage:
    product_code: str
    requested: int
    available: int


@dataclass(frozen=True, slots=True, kw_only=True)
class StockEventBase:
    event_id: UniqueId
    aggregate_id: UniqueId
    correlation_id: UniqueId
    causation_id: UniqueId
    occurred_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class StockReserved(StockEventBase):
    EVENT_TYPE: ClassVar[str] = "stock.reserved.v1"

    order_reference: str
    company_code: str
    retailer_code: str
    reservations: tuple[ReservationRef, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class StockRejected(StockEventBase):
    EVENT_TYPE: ClassVar[str] = "stock.rejected.v1"

    order_reference: str
    company_code: str
    retailer_code: str
    shortages: tuple[Shortage, ...]
    reason: RejectionReason


@dataclass(frozen=True, slots=True, kw_only=True)
class StockReleased(StockEventBase):
    EVENT_TYPE: ClassVar[str] = "stock.released.v1"

    order_reference: str
    company_code: str
    retailer_code: str
    released: tuple[ReservationRef, ...]
    reason: ReleaseReason


type StockEvent = StockReserved | StockRejected | StockReleased


@dataclass(frozen=True, slots=True, kw_only=True)
class DespatchedLine:
    """One line of the fact: the product and the units despatched (F7: the reserved units)."""

    product_code: str
    units: int


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderDespatched(StockEventBase):
    """`order.despatched.v1`. Its `aggregate_id` is the DESPATCH ADVICE's own id: the advice is the
    aggregate that produced the fact (unlike the stock facts, whose carrier is a stock item)."""

    EVENT_TYPE: ClassVar[str] = "order.despatched.v1"

    order_reference: str
    despatch_reference: DespatchReference
    despatch_date: datetime
    company_code: str
    retailer_code: str
    lines: tuple[DespatchedLine, ...]


type FulfillmentEvent = StockEvent | OrderDespatched
