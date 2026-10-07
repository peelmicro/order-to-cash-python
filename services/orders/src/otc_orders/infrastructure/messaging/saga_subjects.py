"""NATS subjects of the six saga commands (`asyncapi.yaml` channels `stockReserve`, `stockRelease`,
`despatchCreate`, `creditHold`, `invoiceIssue`, `creditRelease`). A unit test reads the spec and
compares: the constants are not the authority.
"""

from collections.abc import Mapping

from otc_orders.application.saga.command_kind import SagaCommandKind

STOCK_RESERVE_SUBJECT = "fulfillment.stock.reserve"
STOCK_RELEASE_SUBJECT = "fulfillment.stock.release"
DESPATCH_CREATE_SUBJECT = "fulfillment.despatch.create"
CREDIT_HOLD_SUBJECT = "billing.credit.hold"
INVOICE_ISSUE_SUBJECT = "billing.invoice.issue"
CREDIT_RELEASE_SUBJECT = "billing.credit.release"

SAGA_SUBJECTS: Mapping[SagaCommandKind, str] = {
    SagaCommandKind.STOCK_RESERVE: STOCK_RESERVE_SUBJECT,
    SagaCommandKind.STOCK_RELEASE: STOCK_RELEASE_SUBJECT,
    SagaCommandKind.DESPATCH_CREATE: DESPATCH_CREATE_SUBJECT,
    SagaCommandKind.CREDIT_HOLD: CREDIT_HOLD_SUBJECT,
    SagaCommandKind.INVOICE_ISSUE: INVOICE_ISSUE_SUBJECT,
    SagaCommandKind.CREDIT_RELEASE: CREDIT_RELEASE_SUBJECT,
}
