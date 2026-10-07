"""The four domain events of the Order aggregate (`design.md` section 7.3).

Domain types only (`OrderNumber`, `GLN`, `Money`, `UniqueId`, `datetime`), never `otc_contracts`
models: mapping to the wire envelope is the outbox feature's. Frozen, slotted, keyword-only; every
sequence is a `tuple`, because a frozen dataclass holding a `list` is still mutable through it.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.compensation_step import CompensationStep
from otc_shared_kernel import GLN, Money, OrderNumber, Quantity, UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderEventBase:
    event_id: UniqueId
    aggregate_id: UniqueId
    correlation_id: UniqueId
    causation_id: UniqueId
    occurred_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderPlacedLine:
    product_code: str
    description: str | None
    quantity: Quantity
    unit_price: Money
    line_discount: Money


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderPlaced(OrderEventBase):
    EVENT_TYPE: ClassVar[str] = "order.placed.v1"

    order_reference: OrderNumber
    retailer_code: str
    company_code: str
    buyer_gln: GLN
    supplier_gln: GLN
    currency: str
    order_date: datetime
    lines: tuple[OrderPlacedLine, ...]
    initial_amount: Money
    initial_discount: Money
    total_amount: Money
    notes: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderConfirmed(OrderEventBase):
    EVENT_TYPE: ClassVar[str] = "order.confirmed.v1"

    order_reference: OrderNumber
    retailer_code: str
    company_code: str
    currency: str
    total_amount: Money
    confirmed_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCompleted(OrderEventBase):
    EVENT_TYPE: ClassVar[str] = "order.completed.v1"

    order_reference: OrderNumber
    retailer_code: str
    company_code: str
    currency: str
    total_amount: Money
    completed_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCancelled(OrderEventBase):
    EVENT_TYPE: ClassVar[str] = "order.cancelled.v1"

    order_reference: OrderNumber
    retailer_code: str
    company_code: str
    cancellation_reason: CancellationReason
    cancelled_at: datetime
    compensation_steps: tuple[CompensationStep, ...]
    note: str | None = None


type OrderEvent = OrderPlaced | OrderConfirmed | OrderCompleted | OrderCancelled
