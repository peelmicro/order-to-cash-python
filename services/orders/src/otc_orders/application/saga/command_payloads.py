"""`build_command_payload`: the request of each saga command, built from the LOADED AGGREGATE only
(`design.md` 9.4; #7 `application/saga-command-payloads.ts`).

Returns the generated request model (drift-tested against `asyncapi.yaml`), so there is no
hand-retyped key list to drift. Every amount is an `int` of minor units copied from a `Money`: no
arithmetic, no `Decimal`, no `float`. The `orderReference` of every command is the aggregate's own,
never a value read from an inbound fact (SO12).
"""

from otc_contracts import WireModel
from otc_contracts.generated.asyncapi import (
    CreditHoldRequestPayload,
    CreditReleaseRequestPayload,
    DespatchCreateRequestPayload,
    InvoiceIssueRequestPayload,
    InvoiceLine,
    Line3,
    Reason4,
    StockReleaseRequestPayload,
    StockReserveRequestPayload,
)
from otc_contracts.generated.asyncapi import Money as WireMoney
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.fact import SagaFact
from otc_orders.domain.order import Order

# The only fact that owes `stock.release` in this feature (R27): feature 41 adds the operator's.
RELEASE_OWED_BY = "credit.rejected.v1"


class UnsupportedReleaseTriggerError(Exception):
    """`stock.release` was requested by a fact that does not owe it."""


def build_command_payload(kind: SagaCommandKind, order: Order, fact: SagaFact) -> WireModel:
    reference = order.order_reference.value
    match kind:
        case SagaCommandKind.STOCK_RESERVE:
            return StockReserveRequestPayload(
                order_reference=reference,
                retailer_code=order.retailer_code,
                company_code=order.company_code,
                lines=[
                    Line3(product_code=line.product_code, units=line.quantity.value)
                    for line in order.lines
                ],
            )
        case SagaCommandKind.STOCK_RELEASE:
            if fact.event_type != RELEASE_OWED_BY:
                raise UnsupportedReleaseTriggerError(
                    f"{fact.event_type} does not owe stock.release; only {RELEASE_OWED_BY} does"
                )
            return StockReleaseRequestPayload(
                order_reference=reference, reason=Reason4.credit_rejected
            )
        case SagaCommandKind.DESPATCH_CREATE:
            return DespatchCreateRequestPayload(order_reference=reference)
        case SagaCommandKind.CREDIT_HOLD:
            return CreditHoldRequestPayload(
                order_reference=reference,
                retailer_code=order.retailer_code,
                company_code=order.company_code,
                amount=WireMoney(amount=order.total_amount.amount, currency=order.currency),
            )
        case SagaCommandKind.INVOICE_ISSUE:
            return InvoiceIssueRequestPayload(
                order_reference=reference,
                retailer_code=order.retailer_code,
                company_code=order.company_code,
                currency=order.currency,
                lines=[
                    InvoiceLine(
                        product_code=line.product_code,
                        units=line.quantity.value,
                        unit_price=line.unit_price.amount,
                    )
                    for line in order.lines
                ],
                discount=order.initial_discount.amount,
            )
        case SagaCommandKind.CREDIT_RELEASE:
            return CreditReleaseRequestPayload(
                order_reference=reference,
                retailer_code=order.retailer_code,
                company_code=order.company_code,
            )
