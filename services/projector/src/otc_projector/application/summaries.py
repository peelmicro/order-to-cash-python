"""The fourteen human-readable summary / detail builders (`PR16`, `PR46`).

Each is a pure function of one fact's payload alone: no read-model access, no clock. The strings are
#7's (`../order-to-cash-nestjs/apps/projector/src/domain/summaries.ts`), copied verbatim, and the
seed's own (`services/seed/src/otc_seed/domain/data/sagas.py:510-566, 824-854`) agree with them for
every fact the seed fabricates (checked line by line in the implementation report), so a seeded and
a projected document read alike. Money goes through `otc_shared_kernel.format_money` (SA-5 exponent:
`(9245, "EUR")` -> `"92.45 EUR"`), `divmod` and never `/`.

`detail` exists for exactly five facts: `stock.rejected.v1`, `stock.released.v1`,
`credit.rejected.v1`, `order.cancelled.v1` (its optional operator `note` only when present: `PR46`)
and `order.saga_failed.v1`. Its nested values are the generated sub-models' JSON form
(`model_dump(mode="json", by_alias=True)`: camelCase keys, `.mmmZ` instants), so a
`compensationSteps[].occurredAt` is the same text the wire carried.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from otc_contracts.generated.asyncapi import (
    CreditApprovedPayload,
    CreditRejectedPayload,
    CreditReleasedPayload,
    InvoiceIssuedPayload,
    OrderCancelledPayload,
    OrderCompletedPayload,
    OrderConfirmedPayload,
    OrderDespatchedPayload,
    OrderPlacedPayload,
    OrderSagaFailedPayload,
    PaymentReceivedPayload,
    StockRejectedPayload,
    StockReleasedPayload,
    StockReservedPayload,
)
from otc_shared_kernel import format_money


@dataclass(frozen=True, slots=True)
class Summary:
    text: str
    detail: Mapping[str, object] | None = None


def order_placed(payload: OrderPlacedPayload) -> Summary:
    return Summary(f"Order {payload.order_reference} placed for {payload.retailer_code}")


def stock_reserved(payload: StockReservedPayload) -> Summary:
    return Summary(f"Stock reserved for {len(payload.reservations)} line(s)")


def stock_rejected(payload: StockRejectedPayload) -> Summary:
    total_short = sum(s.requested - s.available for s in payload.shortages)
    first_product = payload.shortages[0].product_code
    return Summary(
        f"Stock rejected: {total_short} unit(s) short on {first_product}",
        {
            "shortages": [s.model_dump(mode="json", by_alias=True) for s in payload.shortages],
            "reason": payload.reason.value,
        },
    )


def stock_released(payload: StockReleasedPayload) -> Summary:
    units = sum(r.units for r in payload.released)
    suffix = " (compensation)" if payload.reason.value == "credit_rejected" else ""
    return Summary(
        f"{units} unit(s) released back to stock{suffix}",
        {
            "released": [r.model_dump(mode="json", by_alias=True) for r in payload.released],
            "reason": payload.reason.value,
        },
    )


def credit_approved(payload: CreditApprovedPayload) -> Summary:
    return Summary(f"Credit hold of {format_money(payload.held_amount, payload.currency)} approved")


def credit_rejected(payload: CreditRejectedPayload) -> Summary:
    amount = format_money(payload.requested_amount, payload.currency)
    return Summary(
        f"Credit hold of {amount} rejected ({payload.reason.value})",
        {"reason": payload.reason.value, "requestedAmount": payload.requested_amount},
    )


def credit_released(payload: CreditReleasedPayload) -> Summary:
    suffix = "invoice paid" if payload.reason.value == "invoice_paid" else "order cancelled"
    return Summary(f"Credit exposure released — {suffix}")


def order_confirmed(_payload: OrderConfirmedPayload) -> Summary:
    return Summary("Order confirmed (ORDRSP)")


def order_despatched(payload: OrderDespatchedPayload) -> Summary:
    return Summary(f"Despatch {payload.despatch_reference} created")


def invoice_issued(payload: InvoiceIssuedPayload) -> Summary:
    return Summary(f"Invoice {payload.invoice_reference} issued")


def payment_received(payload: PaymentReceivedPayload) -> Summary:
    return Summary(f"Payment {payload.payment_reference} received")


def order_completed(payload: OrderCompletedPayload) -> Summary:
    return Summary(f"Order {payload.order_reference} completed")


def order_cancelled(payload: OrderCancelledPayload) -> Summary:
    detail: dict[str, object] = {
        "cancellationReason": payload.cancellation_reason.value,
        "compensationSteps": [
            step.model_dump(mode="json", by_alias=True) for step in payload.compensation_steps
        ],
    }
    if payload.note is not None:
        detail["note"] = payload.note
    return Summary(
        f"Order {payload.order_reference} cancelled ({payload.cancellation_reason.value})", detail
    )


def order_saga_failed(payload: OrderSagaFailedPayload) -> Summary:
    return Summary(
        f'Saga command "{payload.command}" dead-lettered after {payload.attempts} attempt(s)',
        {
            "command": payload.command,
            "attempts": payload.attempts,
            "lastError": payload.last_error,
        },
    )
