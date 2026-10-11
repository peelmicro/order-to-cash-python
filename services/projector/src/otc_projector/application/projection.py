"""`project(event) -> ProjectionDelta`: all fourteen facts, one `match` arm each (`PR2`, `PR12`).

It lives in `application`, not `domain`: `otc_contracts` is pydantic and import-linter's
`domain-purity` counts indirect chains, so a domain function typed on the generated events would
violate it (Notifications' templates are in `application` for the same reason). The arms are over
the `FactEvent` union (`otc_contracts.facts`) and end in `assert_never`, so `mypy --strict`
rejects a missing arm; `tests/unit/test_projection.py` closes the other direction against
`FACT_MODELS`.

This module decides WHICH facts are handled by matching classes, never by a list of `eventType`
strings (`PR36`): the type is read off the event (`event.event_type`).

The implied status and rank come from `PR12`'s table, applied in each arm: a status-less fact (the
five that prove no state was reached) has rank `0`. Only `order.placed.v1` carries a header.
"""

from typing import assert_never

from otc_contracts import FactEvent
from otc_contracts.generated.asyncapi import (
    CreditApprovedEvent,
    CreditRejectedEvent,
    CreditReleasedEvent,
    InvoiceIssuedEvent,
    OrderCancelledEvent,
    OrderCompletedEvent,
    OrderConfirmedEvent,
    OrderDespatchedEvent,
    OrderPlacedEvent,
    OrderSagaFailedEvent,
    PaymentReceivedEvent,
    StockRejectedEvent,
    StockReleasedEvent,
    StockReservedEvent,
)
from otc_projector.application import summaries
from otc_projector.application.summaries import Summary
from otc_projector.domain.projection_delta import (
    HeaderDelta,
    ItemDelta,
    ProjectionDelta,
    TimelineEntryDelta,
)
from otc_projector.domain.status_rank import rank_of


def _delta(
    event: FactEvent,
    summary: Summary,
    *,
    status: str | None = None,
    cancellation_reason: str | None = None,
    despatch_reference: str | None = None,
    invoice_reference: str | None = None,
    payment_reference: str | None = None,
    header: HeaderDelta | None = None,
) -> ProjectionDelta:
    return ProjectionDelta(
        order_id=str(event.correlation_id),
        entry=TimelineEntryDelta(
            event_id=str(event.event_id),
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            summary=summary.text,
            causation_id=str(event.causation_id),
            detail=summary.detail,
        ),
        implied_status=status,
        status_rank=rank_of(status),
        cancellation_reason_if_absent=cancellation_reason,
        despatch_reference_if_absent=despatch_reference,
        invoice_reference_if_absent=invoice_reference,
        payment_reference_if_absent=payment_reference,
        header=header,
    )


def _header(event: OrderPlacedEvent) -> HeaderDelta:
    payload = event.payload
    return HeaderDelta(
        order_reference=payload.order_reference,
        order_date=payload.order_date,
        retailer_code=payload.retailer_code,
        retailer_gln=payload.buyer_gln,
        company_code=payload.company_code,
        company_gln=payload.supplier_gln,
        currency=payload.currency,
        initial_amount=payload.initial_amount,
        initial_discount=payload.initial_discount,
        total_amount=payload.total_amount,
        items=tuple(
            ItemDelta(
                product_code=line.product_code,
                quantity=line.quantity,
                unit_price=line.unit_price,
                line_discount=line.line_discount,
            )
            for line in payload.lines
        ),
    )


def project(event: FactEvent) -> ProjectionDelta:
    match event:
        case OrderPlacedEvent():
            return _delta(
                event, summaries.order_placed(event.payload), status="placed", header=_header(event)
            )
        case StockReservedEvent():
            return _delta(event, summaries.stock_reserved(event.payload), status="stock_reserved")
        case StockRejectedEvent():
            return _delta(event, summaries.stock_rejected(event.payload))
        case StockReleasedEvent():
            return _delta(event, summaries.stock_released(event.payload))
        case CreditApprovedEvent():
            return _delta(event, summaries.credit_approved(event.payload), status="credit_approved")
        case CreditRejectedEvent():
            return _delta(event, summaries.credit_rejected(event.payload))
        case CreditReleasedEvent():
            return _delta(event, summaries.credit_released(event.payload))
        case OrderConfirmedEvent():
            return _delta(event, summaries.order_confirmed(event.payload), status="confirmed")
        case OrderDespatchedEvent():
            return _delta(
                event,
                summaries.order_despatched(event.payload),
                status="despatched",
                despatch_reference=event.payload.despatch_reference,
            )
        case InvoiceIssuedEvent():
            return _delta(
                event,
                summaries.invoice_issued(event.payload),
                status="invoiced",
                invoice_reference=event.payload.invoice_reference,
            )
        case PaymentReceivedEvent():
            return _delta(
                event,
                summaries.payment_received(event.payload),
                status="paid",
                payment_reference=event.payload.payment_reference,
            )
        case OrderCompletedEvent():
            return _delta(event, summaries.order_completed(event.payload), status="completed")
        case OrderCancelledEvent():
            return _delta(
                event,
                summaries.order_cancelled(event.payload),
                status="cancelled",
                cancellation_reason=event.payload.cancellation_reason.value,
            )
        case OrderSagaFailedEvent():
            return _delta(event, summaries.order_saga_failed(event.payload))
        case _:
            assert_never(event)
