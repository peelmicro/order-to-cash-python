"""The fabricated saga history: 5 `completed` orders and exactly 1 `cancelled` one.

Every fact of every saga is built here ONCE and then fanned out by the writers into the three
PostgreSQL databases (as already-published outbox rows) and the MongoDB `order_timeline` document,
so the four stores can never disagree about what happened.

SEEDED CHAIN VERSUS LIVE CHAIN (backlog 201). The causal chain written here is #7's and #8's,
unchanged (dataset parity), and it is ONE LINK SHORTER than a live saga's. The seed has no
commands, so it follows the rule of the outbox design: the two root facts (`order.placed.v1`,
`payment.received.v1`) cite a synthetic deterministic command id
(`order:<seq>:command:orders.create` / `order:<seq>:command:payment.register`), and every other fact
cites the `eventId` of the fact that triggered it. In a LIVE saga a fact produced by an RPC
responder (Fulfillment's `stock.reserved.v1`, Billing's `credit.approved.v1`, ...) cites the
triggering COMMAND's `x-request-id`, which is never a timeline entry, so a live timeline links
"caused by" only for the facts Orders itself emits, while a seeded one links every entry. That
difference is the subject of backlog 201 (decided at the projector phase gate); this module must
not "fix" it, because the seeded chain is part of the parity claim.

References: `ORD-000001..006`, `DES-000001..005`, `INV-000001..005`. The seed owns those sequences
outright on an empty database, so it must run before any live order is placed, and the number
allocators (Phase 8) must start above them: neither #7 nor #8 seeds a counter row (#8's allocator
seeds its counter from `MAX(order_reference)`), and neither does this seed.

Fact ordering follows `specs/shared/saga.md`: the completed sagas follow the happy-path step table
of section 3.1 (one instant apart), the cancelled one follows 4.2 (Path B: release, then cancel).
`aggregate_id` is the id of the aggregate that actually produced the fact (order, stock item,
credit line, despatch or invoice id), never the order id for a fact Orders did not produce.

Payloads are plain dicts in WIRE shape (camelCase keys, instants as `YYYY-MM-DDTHH:MM:SS.mmmZ`,
money as `int` minor units). The domain cannot import `otc_contracts` (pydantic), so the
infrastructure validates every payload against the generated contract model before writing it
(`tests/unit/test_payloads_against_contracts.py`).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from otc_seed.domain.clock import BASE_DATE, add_days, add_minutes, add_seconds, format_instant
from otc_seed.domain.data.companies import company_by_code
from otc_seed.domain.data.credits import credit_by_retailer_and_company
from otc_seed.domain.data.currencies import CURRENCIES
from otc_seed.domain.data.products import product_by_code
from otc_seed.domain.data.retailers import retailer_by_code
from otc_seed.domain.deterministic import deterministic_id
from otc_shared_kernel import DespatchReference, InvoiceReference, OrderNumber, format_money

type Payload = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class OrderLineFixture:
    product_code: str
    description: str
    quantity: int
    unit_price: int
    line_discount: int


@dataclass(frozen=True, slots=True)
class OutboxFixture:
    id: str
    event_id: str
    event_type: str
    aggregate_id: str
    correlation_id: str
    # The eventId of the causing fact, or the id of the synthetic causing command (see the module
    # docstring).
    causation_id: str
    payload: Payload
    occurred_at: datetime
    published_at: datetime


@dataclass(frozen=True, slots=True)
class TimelineEntryFixture:
    event_id: str
    event_type: str
    occurred_at: datetime
    summary: str
    # The SAME causal value the matching OutboxFixture carries, copied so the timeline document can
    # record it exactly as the projector would; without it a seeded document's tie groups would
    # have no causal edges.
    causation_id: str
    detail: Payload | None = None


@dataclass(frozen=True, slots=True)
class ReservationFixture:
    id: str
    company_code: str
    retailer_code: str
    product_code: str
    units: int
    status: Literal["consumed", "released"]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DespatchItemFixture:
    product_code: str
    units: int


@dataclass(frozen=True, slots=True)
class DespatchFixture:
    id: str
    despatch_reference: str
    despatch_date: datetime
    company_code: str
    retailer_code: str
    items: tuple[DespatchItemFixture, ...]


@dataclass(frozen=True, slots=True)
class CreditLedgerEntryFixture:
    id: str
    credit_id: str
    order_reference: str
    amount: int
    type: Literal["hold", "consume", "release"]
    credit_date: datetime


@dataclass(frozen=True, slots=True)
class InvoiceItemFixture:
    product_code: str
    units: int
    price: int


@dataclass(frozen=True, slots=True)
class PaymentFixture:
    id: str
    payment_reference: str
    amount: int
    value_date: datetime
    source: str


@dataclass(frozen=True, slots=True)
class InvoiceFixture:
    id: str
    invoice_reference: str
    invoice_date: datetime
    amount: int
    discount: int
    total_amount: int
    status: Literal["paid"]
    paid_at: datetime
    items: tuple[InvoiceItemFixture, ...]
    payment: PaymentFixture


@dataclass(frozen=True, slots=True)
class OrderSagaFixture:
    sequence: int
    order_id: str
    order_reference: str
    order_date: datetime
    retailer_code: str
    company_code: str
    currency: str
    status: Literal["completed", "cancelled"]
    cancellation_reason: str | None
    notes: str | None
    lines: tuple[OrderLineFixture, ...]
    initial_amount: int
    initial_discount: int
    total_amount: int
    updated_at: datetime
    orders_outbox: tuple[OutboxFixture, ...]
    reservations: tuple[ReservationFixture, ...]
    despatch: DespatchFixture | None
    fulfillment_outbox: tuple[OutboxFixture, ...]
    credit_ledger_entries: tuple[CreditLedgerEntryFixture, ...]
    invoice: InvoiceFixture | None
    billing_outbox: tuple[OutboxFixture, ...]
    timeline: tuple[TimelineEntryFixture, ...]


def stock_row_id(company_code: str, product_code: str) -> str:
    """The id of the Fulfillment stock row of one (company, product) pair; stock.py shares it."""
    return deterministic_id(f"stock:{company_code}:{product_code}")


def _sum_lines(lines: tuple[OrderLineFixture, ...]) -> tuple[int, int, int]:
    initial_amount = sum(line.unit_price * line.quantity for line in lines)
    initial_discount = sum(line.line_discount for line in lines)
    return initial_amount, initial_discount, initial_amount - initial_discount


def _resolve_lines(
    lines: tuple[tuple[str, int], ...],
) -> tuple[OrderLineFixture, ...]:
    # `description` is the order_items.description snapshot, resolved once from the catalogue so the
    # persisted row and the published `order.placed.v1` line carry the same text by construction.
    return tuple(
        OrderLineFixture(
            product_code=code,
            description=product_by_code(code).name,
            quantity=quantity,
            unit_price=product_by_code(code).price,
            line_discount=0,
        )
        for code, quantity in lines
    )


def _order_placed_lines(lines: tuple[OrderLineFixture, ...]) -> list[dict[str, Any]]:
    return [
        {
            "productCode": line.product_code,
            "description": line.description,
            "quantity": line.quantity,
            "unitPrice": line.unit_price,
            "lineDiscount": line.line_discount,
        }
        for line in lines
    ]


def _outbox(
    sequence: int,
    event_type: str,
    *,
    aggregate_id: str,
    correlation_id: str,
    causation_id: str,
    payload: Payload,
    occurred_at: datetime,
) -> OutboxFixture:
    return OutboxFixture(
        id=deterministic_id(f"order:{sequence}:outbox:{event_type}"),
        event_id=deterministic_id(f"order:{sequence}:event:{event_type}"),
        event_type=event_type,
        aggregate_id=aggregate_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload=payload,
        occurred_at=occurred_at,
        published_at=occurred_at,
    )


def _event_id(sequence: int, event_type: str) -> str:
    return deterministic_id(f"order:{sequence}:event:{event_type}")


def _reservation_refs(reservations: tuple[ReservationFixture, ...]) -> list[dict[str, Any]]:
    return [
        {"reservationId": r.id, "productCode": r.product_code, "units": r.units}
        for r in reservations
    ]


def _build_completed_saga(
    sequence: int,
    retailer_code: str,
    company_code: str,
    order_date: datetime,
    raw_lines: tuple[tuple[str, int], ...],
) -> OrderSagaFixture:
    """One completed saga: the full happy path of `specs/shared/saga.md` 3.1."""
    t0 = order_date
    retailer = retailer_by_code(retailer_code)
    company = company_by_code(company_code)
    currency = next(c for c in CURRENCIES if c.code == retailer.currency_code).code
    lines = _resolve_lines(raw_lines)
    initial_amount, initial_discount, total_amount = _sum_lines(lines)

    order_id = deterministic_id(f"order:{sequence}")
    order_reference = str(OrderNumber.from_sequence(sequence))
    credit = credit_by_retailer_and_company(retailer_code, company_code)
    despatch_id = deterministic_id(f"order:{sequence}:despatch")
    despatch_reference = str(DespatchReference.from_sequence(sequence))
    invoice_id = deterministic_id(f"order:{sequence}:invoice")
    invoice_reference = str(InvoiceReference.from_sequence(sequence))
    payment_id = deterministic_id(f"order:{sequence}:payment")
    payment_reference = f"PAY-SEED-{sequence:06d}"
    first_stock_item_id = stock_row_id(company_code, lines[0].product_code)

    t_stock_reserved = add_minutes(t0, 1)
    t_credit_approved = add_minutes(t0, 2)
    t_order_confirmed = add_seconds(t_credit_approved, 30)
    t_despatched = add_minutes(t0, 3)
    t_invoice_issued = add_minutes(t0, 4)
    t_payment_received = add_days(t0, 1)
    t_credit_released = add_seconds(t_payment_received, 5)
    t_completed = add_seconds(t_payment_received, 10)

    reservations = tuple(
        ReservationFixture(
            id=deterministic_id(f"order:{sequence}:reservation:{line.product_code}"),
            company_code=company_code,
            retailer_code=retailer_code,
            product_code=line.product_code,
            units=line.quantity,
            status="consumed",
            created_at=t_stock_reserved,
            updated_at=t_despatched,
        )
        for line in lines
    )

    order_placed_payload: Payload = {
        "orderReference": order_reference,
        "retailerCode": retailer_code,
        "companyCode": company_code,
        "buyerGln": retailer.gln,
        "supplierGln": company.gln,
        "currency": currency,
        "orderDate": format_instant(t0),
        "lines": _order_placed_lines(lines),
        "initialAmount": initial_amount,
        "initialDiscount": initial_discount,
        "totalAmount": total_amount,
    }
    stock_reserved_payload: Payload = {
        "orderReference": order_reference,
        "companyCode": company_code,
        "retailerCode": retailer_code,
        "reservations": _reservation_refs(reservations),
    }
    credit_approved_payload: Payload = {
        "orderReference": order_reference,
        "retailerCode": retailer_code,
        "companyCode": company_code,
        "creditCode": credit.code,
        "currency": currency,
        "heldAmount": total_amount,
        "availableCreditAfter": credit.credit_limit - total_amount,
    }
    order_confirmed_payload: Payload = {
        "orderReference": order_reference,
        "retailerCode": retailer_code,
        "companyCode": company_code,
        "currency": currency,
        "totalAmount": total_amount,
        "confirmedAt": format_instant(t_order_confirmed),
    }
    order_despatched_payload: Payload = {
        "orderReference": order_reference,
        "despatchReference": despatch_reference,
        "despatchDate": format_instant(t_despatched),
        "companyCode": company_code,
        "retailerCode": retailer_code,
        "lines": [{"productCode": line.product_code, "units": line.quantity} for line in lines],
    }
    invoice_issued_payload: Payload = {
        "orderReference": order_reference,
        "invoiceReference": invoice_reference,
        "invoiceDate": format_instant(t_invoice_issued),
        "retailerCode": retailer_code,
        "companyCode": company_code,
        "currency": currency,
        "lines": [
            {"productCode": line.product_code, "units": line.quantity, "unitPrice": line.unit_price}
            for line in lines
        ],
        "amount": initial_amount,
        "discount": initial_discount,
        "totalAmount": total_amount,
    }
    payment_received_payload: Payload = {
        "orderReference": order_reference,
        "invoiceReference": invoice_reference,
        "paymentReference": payment_reference,
        "currency": currency,
        "amount": total_amount,
        "valueDate": format_instant(t_payment_received),
        "source": "test",
    }
    credit_released_payload: Payload = {
        "orderReference": order_reference,
        "retailerCode": retailer_code,
        "companyCode": company_code,
        "creditCode": credit.code,
        "currency": currency,
        "releasedAmount": total_amount,
        "availableCreditAfter": credit.credit_limit,
        "reason": "invoice_paid",
    }
    order_completed_payload: Payload = {
        "orderReference": order_reference,
        "retailerCode": retailer_code,
        "companyCode": company_code,
        "currency": currency,
        "totalAmount": total_amount,
        "completedAt": format_instant(t_completed),
    }

    order_placed_event_id = _event_id(sequence, "order.placed.v1")
    stock_reserved_event_id = _event_id(sequence, "stock.reserved.v1")
    credit_approved_event_id = _event_id(sequence, "credit.approved.v1")
    order_confirmed_event_id = _event_id(sequence, "order.confirmed.v1")
    order_despatched_event_id = _event_id(sequence, "order.despatched.v1")
    invoice_issued_event_id = _event_id(sequence, "invoice.issued.v1")
    payment_received_event_id = _event_id(sequence, "payment.received.v1")
    credit_released_event_id = _event_id(sequence, "credit.released.v1")
    order_completed_event_id = _event_id(sequence, "order.completed.v1")

    # The causal chain (module docstring): two roots cite a synthetic command id, every other fact
    # cites the eventId of the fact that triggered it.
    order_placed_causation_id = deterministic_id(f"order:{sequence}:command:orders.create")
    stock_reserved_causation_id = order_placed_event_id
    credit_approved_causation_id = stock_reserved_event_id
    order_confirmed_causation_id = credit_approved_event_id
    order_despatched_causation_id = credit_approved_event_id
    invoice_issued_causation_id = order_despatched_event_id
    payment_received_causation_id = deterministic_id(f"order:{sequence}:command:payment.register")
    credit_released_causation_id = payment_received_event_id
    order_completed_causation_id = credit_released_event_id

    orders_outbox = (
        _outbox(
            sequence,
            "order.placed.v1",
            aggregate_id=order_id,
            correlation_id=order_id,
            causation_id=order_placed_causation_id,
            payload=order_placed_payload,
            occurred_at=t0,
        ),
        _outbox(
            sequence,
            "order.confirmed.v1",
            aggregate_id=order_id,
            correlation_id=order_id,
            causation_id=order_confirmed_causation_id,
            payload=order_confirmed_payload,
            occurred_at=t_order_confirmed,
        ),
        _outbox(
            sequence,
            "order.completed.v1",
            aggregate_id=order_id,
            correlation_id=order_id,
            causation_id=order_completed_causation_id,
            payload=order_completed_payload,
            occurred_at=t_completed,
        ),
    )
    fulfillment_outbox = (
        _outbox(
            sequence,
            "stock.reserved.v1",
            aggregate_id=first_stock_item_id,
            correlation_id=order_id,
            causation_id=stock_reserved_causation_id,
            payload=stock_reserved_payload,
            occurred_at=t_stock_reserved,
        ),
        _outbox(
            sequence,
            "order.despatched.v1",
            aggregate_id=despatch_id,
            correlation_id=order_id,
            causation_id=order_despatched_causation_id,
            payload=order_despatched_payload,
            occurred_at=t_despatched,
        ),
    )
    billing_outbox = (
        _outbox(
            sequence,
            "credit.approved.v1",
            aggregate_id=credit.id,
            correlation_id=order_id,
            causation_id=credit_approved_causation_id,
            payload=credit_approved_payload,
            occurred_at=t_credit_approved,
        ),
        _outbox(
            sequence,
            "invoice.issued.v1",
            aggregate_id=invoice_id,
            correlation_id=order_id,
            causation_id=invoice_issued_causation_id,
            payload=invoice_issued_payload,
            occurred_at=t_invoice_issued,
        ),
        _outbox(
            sequence,
            "payment.received.v1",
            aggregate_id=invoice_id,
            correlation_id=order_id,
            causation_id=payment_received_causation_id,
            payload=payment_received_payload,
            occurred_at=t_payment_received,
        ),
        _outbox(
            sequence,
            "credit.released.v1",
            aggregate_id=credit.id,
            correlation_id=order_id,
            causation_id=credit_released_causation_id,
            payload=credit_released_payload,
            occurred_at=t_credit_released,
        ),
    )

    timeline = (
        TimelineEntryFixture(
            order_placed_event_id,
            "order.placed.v1",
            t0,
            f"Order {order_reference} placed for {retailer_code}",
            order_placed_causation_id,
        ),
        TimelineEntryFixture(
            stock_reserved_event_id,
            "stock.reserved.v1",
            t_stock_reserved,
            f"Stock reserved for {len(reservations)} line(s)",
            stock_reserved_causation_id,
        ),
        TimelineEntryFixture(
            credit_approved_event_id,
            "credit.approved.v1",
            t_credit_approved,
            f"Credit hold of {format_money(total_amount, currency)} approved",
            credit_approved_causation_id,
        ),
        TimelineEntryFixture(
            order_confirmed_event_id,
            "order.confirmed.v1",
            t_order_confirmed,
            "Order confirmed (ORDRSP)",
            order_confirmed_causation_id,
        ),
        TimelineEntryFixture(
            order_despatched_event_id,
            "order.despatched.v1",
            t_despatched,
            f"Despatch {despatch_reference} created",
            order_despatched_causation_id,
        ),
        TimelineEntryFixture(
            invoice_issued_event_id,
            "invoice.issued.v1",
            t_invoice_issued,
            f"Invoice {invoice_reference} issued",
            invoice_issued_causation_id,
        ),
        TimelineEntryFixture(
            payment_received_event_id,
            "payment.received.v1",
            t_payment_received,
            f"Payment {payment_reference} received",
            payment_received_causation_id,
        ),
        TimelineEntryFixture(
            credit_released_event_id,
            "credit.released.v1",
            t_credit_released,
            "Credit exposure released — invoice paid",
            credit_released_causation_id,
        ),
        TimelineEntryFixture(
            order_completed_event_id,
            "order.completed.v1",
            t_completed,
            f"Order {order_reference} completed",
            order_completed_causation_id,
        ),
    )

    return OrderSagaFixture(
        sequence=sequence,
        order_id=order_id,
        order_reference=order_reference,
        order_date=t0,
        retailer_code=retailer_code,
        company_code=company_code,
        currency=currency,
        status="completed",
        cancellation_reason=None,
        notes=None,
        lines=lines,
        initial_amount=initial_amount,
        initial_discount=initial_discount,
        total_amount=total_amount,
        updated_at=t_completed,
        orders_outbox=orders_outbox,
        reservations=reservations,
        despatch=DespatchFixture(
            id=despatch_id,
            despatch_reference=despatch_reference,
            despatch_date=t_despatched,
            company_code=company_code,
            retailer_code=retailer_code,
            items=tuple(DespatchItemFixture(line.product_code, line.quantity) for line in lines),
        ),
        fulfillment_outbox=fulfillment_outbox,
        credit_ledger_entries=(
            CreditLedgerEntryFixture(
                deterministic_id(f"order:{sequence}:credit-item:hold"),
                credit.id,
                order_reference,
                total_amount,
                "hold",
                t_credit_approved,
            ),
            CreditLedgerEntryFixture(
                deterministic_id(f"order:{sequence}:credit-item:consume"),
                credit.id,
                order_reference,
                total_amount,
                "consume",
                t_invoice_issued,
            ),
            CreditLedgerEntryFixture(
                deterministic_id(f"order:{sequence}:credit-item:release"),
                credit.id,
                order_reference,
                total_amount,
                "release",
                t_credit_released,
            ),
        ),
        invoice=InvoiceFixture(
            id=invoice_id,
            invoice_reference=invoice_reference,
            invoice_date=t_invoice_issued,
            amount=initial_amount,
            discount=initial_discount,
            total_amount=total_amount,
            status="paid",
            paid_at=t_payment_received,
            items=tuple(
                InvoiceItemFixture(line.product_code, line.quantity, line.unit_price)
                for line in lines
            ),
            payment=PaymentFixture(
                id=payment_id,
                payment_reference=payment_reference,
                amount=total_amount,
                value_date=t_payment_received,
                source="test",
            ),
        ),
        billing_outbox=billing_outbox,
        timeline=timeline,
    )


CANCELLED_ORDER_NOTES = "demo — compensation path (credit_rejected, .99 rule)"


def _build_cancelled_saga(
    sequence: int,
    retailer_code: str,
    company_code: str,
    order_date: datetime,
    raw_lines: tuple[tuple[str, int], ...],
) -> OrderSagaFixture:
    """The one cancelled saga: the compensation path of `specs/shared/saga.md` 4.2 (release, then
    cancel). Its total must end in `.99`: the credit simulator's `simulated_cents_rule`."""
    t0 = order_date
    retailer = retailer_by_code(retailer_code)
    company = company_by_code(company_code)
    currency = next(c for c in CURRENCIES if c.code == retailer.currency_code).code
    lines = _resolve_lines(raw_lines)
    initial_amount, initial_discount, total_amount = _sum_lines(lines)
    if total_amount % 100 != 99:
        raise ValueError(
            f"order {sequence} total {total_amount} does not end in .99: "
            "the simulated_cents_rule demo requires it"
        )

    order_id = deterministic_id(f"order:{sequence}")
    order_reference = str(OrderNumber.from_sequence(sequence))
    credit = credit_by_retailer_and_company(retailer_code, company_code)
    first_stock_item_id = stock_row_id(company_code, lines[0].product_code)

    t_stock_reserved = add_minutes(t0, 1)
    t_credit_rejected = add_minutes(t0, 2)
    t_stock_released = add_minutes(t0, 3)
    t_cancelled = add_seconds(t_stock_released, 30)

    reservations = tuple(
        ReservationFixture(
            id=deterministic_id(f"order:{sequence}:reservation:{line.product_code}"),
            company_code=company_code,
            retailer_code=retailer_code,
            product_code=line.product_code,
            units=line.quantity,
            status="released",
            created_at=t_stock_reserved,
            updated_at=t_stock_released,
        )
        for line in lines
    )
    reservation_refs = _reservation_refs(reservations)

    order_placed_event_id = _event_id(sequence, "order.placed.v1")
    stock_reserved_event_id = _event_id(sequence, "stock.reserved.v1")
    credit_rejected_event_id = _event_id(sequence, "credit.rejected.v1")
    stock_released_event_id = _event_id(sequence, "stock.released.v1")
    order_cancelled_event_id = _event_id(sequence, "order.cancelled.v1")

    # The causal chain (module docstring), Path B: release, then cancel.
    order_placed_causation_id = deterministic_id(f"order:{sequence}:command:orders.create")
    stock_reserved_causation_id = order_placed_event_id
    credit_rejected_causation_id = stock_reserved_event_id
    stock_released_causation_id = credit_rejected_event_id
    order_cancelled_causation_id = stock_released_event_id

    released_units = sum(r.units for r in reservations)
    order_placed_payload: Payload = {
        "orderReference": order_reference,
        "retailerCode": retailer_code,
        "companyCode": company_code,
        "buyerGln": retailer.gln,
        "supplierGln": company.gln,
        "currency": currency,
        "orderDate": format_instant(t0),
        "lines": _order_placed_lines(lines),
        "initialAmount": initial_amount,
        "initialDiscount": initial_discount,
        "totalAmount": total_amount,
        "notes": CANCELLED_ORDER_NOTES,
    }
    stock_reserved_payload: Payload = {
        "orderReference": order_reference,
        "companyCode": company_code,
        "retailerCode": retailer_code,
        "reservations": reservation_refs,
    }
    credit_rejected_payload: Payload = {
        "orderReference": order_reference,
        "retailerCode": retailer_code,
        "companyCode": company_code,
        "creditCode": credit.code,
        "currency": currency,
        "requestedAmount": total_amount,
        "availableCredit": credit.credit_limit,
        "reason": "simulated_cents_rule",
    }
    stock_released_payload: Payload = {
        "orderReference": order_reference,
        "companyCode": company_code,
        "retailerCode": retailer_code,
        "released": reservation_refs,
        "reason": "credit_rejected",
    }
    order_cancelled_payload: Payload = {
        "orderReference": order_reference,
        "retailerCode": retailer_code,
        "companyCode": company_code,
        "cancellationReason": "credit_rejected",
        "cancelledAt": format_instant(t_cancelled),
        "compensationSteps": [
            {
                "step": "stock_released",
                "eventId": stock_released_event_id,
                "eventType": "stock.released.v1",
                "occurredAt": format_instant(t_stock_released),
                "summary": f"{released_units} unit(s) released back to stock",
            }
        ],
    }

    orders_outbox = (
        _outbox(
            sequence,
            "order.placed.v1",
            aggregate_id=order_id,
            correlation_id=order_id,
            causation_id=order_placed_causation_id,
            payload=order_placed_payload,
            occurred_at=t0,
        ),
        _outbox(
            sequence,
            "order.cancelled.v1",
            aggregate_id=order_id,
            correlation_id=order_id,
            causation_id=order_cancelled_causation_id,
            payload=order_cancelled_payload,
            occurred_at=t_cancelled,
        ),
    )
    fulfillment_outbox = (
        _outbox(
            sequence,
            "stock.reserved.v1",
            aggregate_id=first_stock_item_id,
            correlation_id=order_id,
            causation_id=stock_reserved_causation_id,
            payload=stock_reserved_payload,
            occurred_at=t_stock_reserved,
        ),
        _outbox(
            sequence,
            "stock.released.v1",
            aggregate_id=first_stock_item_id,
            correlation_id=order_id,
            causation_id=stock_released_causation_id,
            payload=stock_released_payload,
            occurred_at=t_stock_released,
        ),
    )
    billing_outbox = (
        _outbox(
            sequence,
            "credit.rejected.v1",
            aggregate_id=credit.id,
            correlation_id=order_id,
            causation_id=credit_rejected_causation_id,
            payload=credit_rejected_payload,
            occurred_at=t_credit_rejected,
        ),
    )

    timeline = (
        TimelineEntryFixture(
            order_placed_event_id,
            "order.placed.v1",
            t0,
            f"Order {order_reference} placed for {retailer_code}",
            order_placed_causation_id,
        ),
        TimelineEntryFixture(
            stock_reserved_event_id,
            "stock.reserved.v1",
            t_stock_reserved,
            f"Stock reserved for {len(reservations)} line(s)",
            stock_reserved_causation_id,
        ),
        TimelineEntryFixture(
            credit_rejected_event_id,
            "credit.rejected.v1",
            t_credit_rejected,
            f"Credit hold of {format_money(total_amount, currency)} rejected "
            "(simulated_cents_rule)",
            credit_rejected_causation_id,
            detail={"reason": "simulated_cents_rule", "requestedAmount": total_amount},
        ),
        TimelineEntryFixture(
            stock_released_event_id,
            "stock.released.v1",
            t_stock_released,
            f"{released_units} unit(s) released back to stock (compensation)",
            stock_released_causation_id,
        ),
        TimelineEntryFixture(
            order_cancelled_event_id,
            "order.cancelled.v1",
            t_cancelled,
            f"Order {order_reference} cancelled (credit_rejected)",
            order_cancelled_causation_id,
            detail={"cancellationReason": "credit_rejected"},
        ),
    )

    return OrderSagaFixture(
        sequence=sequence,
        order_id=order_id,
        order_reference=order_reference,
        order_date=t0,
        retailer_code=retailer_code,
        company_code=company_code,
        currency=currency,
        status="cancelled",
        cancellation_reason="credit_rejected",
        notes=CANCELLED_ORDER_NOTES,
        lines=lines,
        initial_amount=initial_amount,
        initial_discount=initial_discount,
        total_amount=total_amount,
        updated_at=t_cancelled,
        orders_outbox=orders_outbox,
        reservations=reservations,
        despatch=None,
        fulfillment_outbox=fulfillment_outbox,
        credit_ledger_entries=(),
        invoice=None,
        billing_outbox=billing_outbox,
        timeline=timeline,
    )


SAGAS: tuple[OrderSagaFixture, ...] = (
    _build_completed_saga(
        1, "CarrefourEs", "IBERFOODS", BASE_DATE, (("PRD-0002", 5), ("PRD-0003", 3))
    ),
    _build_completed_saga(
        2, "CarrefourFr", "FRESHFR", add_days(BASE_DATE, 1), (("PRD-0002", 4), ("PRD-0008", 2))
    ),
    _build_completed_saga(
        3,
        "LeroyMerlinEs",
        "TOOLIBERIA",
        add_days(BASE_DATE, 2),
        (("PRD-0004", 10), ("PRD-0005", 6)),
    ),
    _build_completed_saga(
        4, "AldiDe", "GERMANFOODS", add_days(BASE_DATE, 3), (("PRD-0002", 8), ("PRD-0003", 4))
    ),
    _build_completed_saga(
        5, "AldiGb", "UKDISTRIB", add_days(BASE_DATE, 4), (("PRD-0009", 20), ("PRD-0010", 15))
    ),
    _build_cancelled_saga(
        6, "CarrefourEs", "IBERFOODS", add_days(BASE_DATE, 5), (("PRD-0001", 1),)
    ),
)

COMPLETED_SAGAS: tuple[OrderSagaFixture, ...] = tuple(s for s in SAGAS if s.status == "completed")
CANCELLED_SAGAS: tuple[OrderSagaFixture, ...] = tuple(s for s in SAGAS if s.status == "cancelled")
