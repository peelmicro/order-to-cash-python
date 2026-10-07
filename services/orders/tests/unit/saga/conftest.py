"""Builders for the saga's pure unit tests (`design.md` 14.1).

Fixtures, not helper modules: the repository runs `--import-mode=importlib`, so a test module cannot
import a sibling module, and `unit/domain/conftest.py`'s fixtures are not visible here. Builders,
not mocks. Every instant is aware UTC; the event id, the correlation id, the order id and the
aggregate id of one fact are pairwise DISTINCT (a step built from the wrong id cannot coincide with
the right one), and the two order lines differ in product, quantity, price and discount.

Loop scope: nothing here is async.
"""

import dataclasses
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from otc_contracts import Envelope, WireModel, to_wire_json
from otc_contracts.generated.asyncapi import (
    CancellationReason as CancellationReasonWire,
)
from otc_contracts.generated.asyncapi import (
    CreditApprovedPayload,
    CreditRejectedPayload,
    CreditReleasedPayload,
    DespatchLine,
    InvoiceIssuedPayload,
    InvoiceLine,
    OrderCancelledPayload,
    OrderCompletedPayload,
    OrderConfirmedPayload,
    OrderDespatchedPayload,
    OrderPlacedPayload,
    OrderSagaFailedPayload,
    PaymentReceivedPayload,
    PaymentSource,
    Reason,
    Reason1,
    Reason2,
    Reason3,
    ReservationRef,
    Shortage,
    StockRejectedPayload,
    StockReleasedPayload,
    StockReservedPayload,
)
from otc_contracts.generated.asyncapi import (
    OrderLine as WireOrderLine,
)
from otc_orders.application.saga.fact import SagaFact
from otc_orders.domain.order import Order
from otc_orders.domain.snapshot import OrderLineSnapshot, OrderSnapshot
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import GLN, Money, OrderNumber, Quantity, UniqueId

BASE_INSTANT = datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC)
# hex letters in the id, so an upper-case spelling of it differs from the canonical one
ORDER_ID = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000d1"))
EVENT_ID = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000e1"))
AGGREGATE_ID = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000a9"))
CAUSATION_ID = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000c5"))
LINE_A_ID = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000a1"))
LINE_B_ID = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000b2"))
FACT_INSTANT = BASE_INSTANT + timedelta(minutes=90, milliseconds=123)
REFERENCE = "ORD-000007"

ALL_STATUSES = tuple(OrderStatus)


@pytest.fixture
def order_in() -> Callable[..., Order]:
    """`order_in(status, reason=None)`: an order restored in `status` (`Order.rehydrate`)."""

    def build(
        status: OrderStatus,
        *,
        reason: CancellationReason | None = None,
        order_id: UniqueId = ORDER_ID,
    ) -> Order:
        if status is OrderStatus.CANCELLED and reason is None:
            reason = CancellationReason.OPERATOR_CANCELLED
        return Order.rehydrate(
            OrderSnapshot(
                id=order_id,
                order_reference=OrderNumber(REFERENCE),
                order_date=BASE_INSTANT,
                retailer_code="RET-01",
                buyer_gln=GLN("4012345000009"),
                company_code="CMP-01",
                supplier_gln=GLN("5412345000006"),
                currency="EUR",
                status=status,
                cancellation_reason=reason,
                notes=None,
                lines=(
                    OrderLineSnapshot(
                        id=LINE_A_ID,
                        product_code="SKU-A",
                        description="Alpha pallet",
                        quantity=Quantity(3),
                        unit_price=Money(1999, "EUR"),
                        line_discount=Money(250, "EUR"),
                    ),
                    OrderLineSnapshot(
                        id=LINE_B_ID,
                        product_code="SKU-B",
                        description=None,
                        quantity=Quantity(2),
                        unit_price=Money(1234, "EUR"),
                        line_discount=Money(100, "EUR"),
                    ),
                ),
                created_at=BASE_INSTANT,
                updated_at=BASE_INSTANT + timedelta(minutes=5),
            )
        )

    return build


def _payload_of(event_type: str, *, release_reason: Reason1) -> WireModel:
    reservation = ReservationRef(
        reservation_id=uuid.UUID("00000000-0000-4000-8000-0000000000f1"),
        product_code="SKU-A",
        units=3,
    )
    match event_type:
        case "order.placed.v1":
            return OrderPlacedPayload(
                order_reference=REFERENCE,
                retailer_code="RET-01",
                company_code="CMP-01",
                buyer_gln="4012345000009",
                supplier_gln="5412345000006",
                currency="EUR",
                order_date=BASE_INSTANT,
                lines=[
                    WireOrderLine(
                        product_code="SKU-A", quantity=3, unit_price=1999, line_discount=250
                    )
                ],
                initial_amount=8465,
                initial_discount=350,
                total_amount=8115,
            )
        case "stock.reserved.v1":
            return StockReservedPayload(
                order_reference=REFERENCE, company_code="CMP-01", reservations=[reservation]
            )
        case "stock.rejected.v1":
            return StockRejectedPayload(
                order_reference=REFERENCE,
                company_code="CMP-01",
                shortages=[Shortage(product_code="SKU-A", requested=3, available=1)],
                reason=Reason.insufficient_stock,
            )
        case "stock.released.v1":
            return StockReleasedPayload(
                order_reference=REFERENCE,
                company_code="CMP-01",
                released=[reservation],
                reason=release_reason,
            )
        case "credit.approved.v1":
            return CreditApprovedPayload(
                order_reference=REFERENCE,
                retailer_code="RET-01",
                company_code="CMP-01",
                credit_code="CR-000001",
                currency="EUR",
                held_amount=8115,
                available_credit_after=91885,
            )
        case "credit.rejected.v1":
            return CreditRejectedPayload(
                order_reference=REFERENCE,
                retailer_code="RET-01",
                company_code="CMP-01",
                currency="EUR",
                requested_amount=8115,
                available_credit=100,
                reason=Reason2.over_limit,
            )
        case "order.despatched.v1":
            return OrderDespatchedPayload(
                order_reference=REFERENCE,
                despatch_reference="DES-000001",
                despatch_date=BASE_INSTANT,
                company_code="CMP-01",
                retailer_code="RET-01",
                lines=[DespatchLine(product_code="SKU-A", units=3)],
            )
        case "invoice.issued.v1":
            return InvoiceIssuedPayload(
                order_reference=REFERENCE,
                invoice_reference="INV-000001",
                invoice_date=BASE_INSTANT,
                retailer_code="RET-01",
                company_code="CMP-01",
                currency="EUR",
                lines=[InvoiceLine(product_code="SKU-A", units=3, unit_price=1999)],
                amount=8465,
                discount=350,
                total_amount=8115,
            )
        case "payment.received.v1":
            return PaymentReceivedPayload(
                order_reference=REFERENCE,
                invoice_reference="INV-000001",
                payment_reference="PAY-1",
                currency="EUR",
                amount=8115,
                value_date=BASE_INSTANT,
                source=PaymentSource.test,
            )
        case "credit.released.v1":
            return CreditReleasedPayload(
                order_reference=REFERENCE,
                retailer_code="RET-01",
                company_code="CMP-01",
                currency="EUR",
                released_amount=8115,
                available_credit_after=100000,
                reason=Reason3.invoice_paid,
            )
        case "order.confirmed.v1":
            return OrderConfirmedPayload(
                order_reference=REFERENCE,
                retailer_code="RET-01",
                company_code="CMP-01",
                currency="EUR",
                total_amount=8115,
                confirmed_at=BASE_INSTANT,
            )
        case "order.completed.v1":
            return OrderCompletedPayload(
                order_reference=REFERENCE,
                retailer_code="RET-01",
                company_code="CMP-01",
                currency="EUR",
                total_amount=8115,
                completed_at=BASE_INSTANT,
            )
        case "order.cancelled.v1":
            return OrderCancelledPayload(
                order_reference=REFERENCE,
                retailer_code="RET-01",
                company_code="CMP-01",
                cancellation_reason=CancellationReasonWire.stock_rejected,
                cancelled_at=BASE_INSTANT,
                compensation_steps=[],
            )
        case "order.saga_failed.v1":
            return OrderSagaFailedPayload(
                order_reference=REFERENCE,
                command="stock.reserve",
                attempts=3,
                last_error="no responders",
                failed_at=BASE_INSTANT,
            )
    raise AssertionError(f"the fixture builds no payload for {event_type}")


FactBuilder = Callable[..., SagaFact]


@pytest.fixture
def make_fact() -> FactBuilder:
    """`make_fact(event_type, release_reason=..., **overrides)`: a consumed fact whose event id,
    correlation id and aggregate id are pairwise distinct."""

    def build(
        event_type: str,
        *,
        release_reason: Reason1 = Reason1.credit_rejected,
        **overrides: Any,
    ) -> SagaFact:
        fact = SagaFact(
            event_id=EVENT_ID,
            event_type=event_type,
            correlation_id=ORDER_ID,
            occurred_at=FACT_INSTANT,
            payload=_payload_of(event_type, release_reason=release_reason),
            topic="otc.test.facts.v1",
        )
        return dataclasses.replace(fact, **overrides)

    return build


EnvelopeBytes = Callable[..., bytes]


@pytest.fixture
def envelope_bytes() -> EnvelopeBytes:
    """`envelope_bytes(event_type, **overrides)`: the wire bytes of one fact envelope, written by
    the one serializer. Overrides replace envelope fields by their wire (camelCase) names AFTER
    serialisation, so a test can write a malformed or unusual value the models would refuse."""

    def build(
        event_type: str, *, release_reason: Reason1 = Reason1.credit_rejected, **raw: Any
    ) -> bytes:
        payload = json.loads(to_wire_json(_payload_of(event_type, release_reason=release_reason)))
        envelope = Envelope[dict[str, Any]](
            event_id=EVENT_ID.value,
            event_type=event_type,
            aggregate_id=AGGREGATE_ID.value,
            correlation_id=ORDER_ID.value,
            causation_id=CAUSATION_ID.value,
            occurred_at=FACT_INSTANT,
            payload=payload,
        )
        document = json.loads(to_wire_json(envelope))
        document.update(raw)
        return json.dumps(document, separators=(",", ":")).encode("utf-8")

    return build
