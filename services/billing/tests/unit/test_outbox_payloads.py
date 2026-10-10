"""Domain event -> wire fact, every field against a distinct source value (task F3).

No store, no broker. Each event is built with values pairwise distinct across the whole test (four
ids, `companyCode` and `retailerCode` apart, held / available / requested / released apart), so a
mapper that reads `company_code` for `retailer_code`, transposes two amounts or hard-codes a
`reason` produces a value the assertion cannot mistake for the right one. The reply key sets are
parsed from the bytes `to_wire_json` produced.

Loop scope: nothing here is async.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

import pytest

from otc_billing.domain.events import CreditApproved, CreditRejected, CreditReleased
from otc_billing.domain.invoice_events import (
    InvoiceFactLine,
    InvoiceIssued,
    PaymentReceived,
    PaymentSource,
)
from otc_billing.domain.reasons import CreditRejectionReason, CreditReleaseReason
from otc_billing.infrastructure.outbox.errors import UnmappedDomainEventError
from otc_billing.infrastructure.outbox.payloads import build_fact, narrow
from otc_contracts import to_wire_json
from otc_shared_kernel import InvoiceReference, UniqueId


def uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(f"00000000-0000-4000-8000-{n:012d}"))


EVENT_ID, AGGREGATE_ID, CORRELATION_ID, CAUSATION_ID = uid(1), uid(2), uid(3), uid(4)
OCCURRED_AT = datetime(2026, 10, 8, 9, 30, 5, 123987, tzinfo=UTC)  # sub-millisecond: truncated
ORDER_REFERENCE = "ORD-000123"
COMPANY = "CMP-88"
RETAILER = "RET-77"
CODE = "CR-000555"


class Fields(TypedDict):
    event_id: UniqueId
    aggregate_id: UniqueId
    correlation_id: UniqueId
    causation_id: UniqueId
    occurred_at: datetime
    order_reference: str
    retailer_code: str
    company_code: str
    credit_code: str
    currency: str


def fields() -> Fields:
    return Fields(
        event_id=EVENT_ID,
        aggregate_id=AGGREGATE_ID,
        correlation_id=CORRELATION_ID,
        causation_id=CAUSATION_ID,
        occurred_at=OCCURRED_AT,
        order_reference=ORDER_REFERENCE,
        retailer_code=RETAILER,
        company_code=COMPANY,
        credit_code=CODE,
        currency="EUR",
    )


def approved() -> CreditApproved:
    return CreditApproved(**fields(), held_amount=4210, available_credit_after=95790)


def rejected(reason: CreditRejectionReason = CreditRejectionReason.OVER_LIMIT) -> CreditRejected:
    return CreditRejected(**fields(), requested_amount=777, available_credit=333, reason=reason)


def released(reason: CreditReleaseReason = CreditReleaseReason.ORDER_CANCELLED) -> CreditReleased:
    return CreditReleased(
        **fields(), released_amount=555, available_credit_after=99445, reason=reason
    )


def wire(payload: object) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(to_wire_json(payload))  # type: ignore[arg-type]
    return parsed


def assert_envelope(fact_envelope: object, event_type: str) -> None:
    dumped = wire(fact_envelope)
    assert list(dumped)[:7] == [
        "eventId",
        "eventType",
        "aggregateId",
        "correlationId",
        "causationId",
        "occurredAt",
        "payload",
    ], "the envelope's field order is the spec's"
    assert dumped["eventId"] == str(EVENT_ID)
    assert dumped["eventType"] == event_type
    assert dumped["aggregateId"] == str(AGGREGATE_ID)
    assert dumped["correlationId"] == str(CORRELATION_ID)
    assert dumped["causationId"] == str(CAUSATION_ID)
    assert dumped["occurredAt"] == "2026-10-08T09:30:05.123Z", "truncated to the millisecond"


IDENTITY = {
    "orderReference": ORDER_REFERENCE,
    "retailerCode": RETAILER,
    "companyCode": COMPANY,
    "creditCode": CODE,
    "currency": "EUR",
}


def test_credit_approved_becomes_its_payload_with_every_field_equal_to_the_supplied_value() -> None:
    built = build_fact(narrow(approved()))
    assert_envelope(built.envelope, "credit.approved.v1")
    assert wire(built.payload) == {**IDENTITY, "heldAmount": 4210, "availableCreditAfter": 95790}, (
        "held_amount and available_credit_after must not be transposed"
    )
    assert built.occurred_at == datetime(2026, 10, 8, 9, 30, 5, 123000, tzinfo=UTC)


@pytest.mark.parametrize("reason", list(CreditRejectionReason))
def test_credit_rejected_becomes_its_payload_with_the_reason_token(
    reason: CreditRejectionReason,
) -> None:
    built = build_fact(narrow(rejected(reason)))
    assert_envelope(built.envelope, "credit.rejected.v1")
    assert wire(built.payload) == {
        **IDENTITY,
        "requestedAmount": 777,
        "availableCredit": 333,
        "reason": reason.value,
    }


@pytest.mark.parametrize("reason", list(CreditReleaseReason))
def test_credit_released_becomes_its_payload_with_the_reason_token(
    reason: CreditReleaseReason,
) -> None:
    built = build_fact(narrow(released(reason)))
    assert_envelope(built.envelope, "credit.released.v1")
    assert wire(built.payload) == {
        **IDENTITY,
        "releasedAmount": 555,
        "availableCreditAfter": 99445,
        "reason": reason.value,
    }


def test_an_event_class_nobody_mapped_is_refused() -> None:
    with pytest.raises(UnmappedDomainEventError):
        narrow(object())
    with pytest.raises(UnmappedDomainEventError):
        narrow("credit.approved.v1")


# ----------------------------------------------------------------- feature 21 (task F9)

INVOICE_REFERENCE = InvoiceReference.from_sequence(456)
INVOICE_DATE = datetime(2026, 10, 7, 7, 41, 20, 456789, tzinfo=UTC)  # NOT the envelope's instant
VALUE_DATE = datetime(2026, 10, 10, 18, 5, 9, 987654, tzinfo=UTC)  # nor this
LINES = (
    InvoiceFactLine(product_code="PRD-ZZ", units=3, unit_price=1999),
    InvoiceFactLine(product_code="PRD-AA", units=2, unit_price=1234),
)


def invoice_issued() -> InvoiceIssued:
    return InvoiceIssued(
        event_id=EVENT_ID,
        aggregate_id=AGGREGATE_ID,
        correlation_id=CORRELATION_ID,
        causation_id=CAUSATION_ID,
        occurred_at=OCCURRED_AT,
        order_reference=ORDER_REFERENCE,
        invoice_reference=INVOICE_REFERENCE,
        invoice_date=INVOICE_DATE,
        retailer_code=RETAILER,
        company_code=COMPANY,
        currency="EUR",
        lines=LINES,
        amount=8465,
        discount=350,
        total_amount=8115,
    )


def payment_received(source: PaymentSource = PaymentSource.ROBOT) -> PaymentReceived:
    return PaymentReceived(
        event_id=EVENT_ID,
        aggregate_id=AGGREGATE_ID,
        correlation_id=CORRELATION_ID,
        causation_id=CAUSATION_ID,
        occurred_at=OCCURRED_AT,
        order_reference=ORDER_REFERENCE,
        invoice_reference=INVOICE_REFERENCE,
        payment_reference="PAY-77-ABC",
        amount=8115,
        currency="EUR",
        value_date=VALUE_DATE,
        source=source,
    )


def test_invoice_issued_becomes_its_payload_with_every_field_equal_to_the_supplied_value() -> None:
    built = build_fact(narrow(invoice_issued()))

    assert_envelope(built.envelope, "invoice.issued.v1")
    assert wire(built.payload) == {
        "orderReference": ORDER_REFERENCE,
        "invoiceReference": "INV-000456",
        "invoiceDate": "2026-10-07T07:41:20.456Z",
        "retailerCode": RETAILER,
        "companyCode": COMPANY,
        "currency": "EUR",
        "lines": [
            {"productCode": "PRD-ZZ", "units": 3, "unitPrice": 1999},
            {"productCode": "PRD-AA", "units": 2, "unitPrice": 1234},
        ],
        "amount": 8465,
        "discount": 350,
        "totalAmount": 8115,
    }, "a field of the invoice.issued.v1 payload is not the supplied value"
    assert built.occurred_at == datetime(2026, 10, 8, 9, 30, 5, 123000, tzinfo=UTC)
    # the lines keep the REQUEST's order (PRD-ZZ before PRD-AA)
    assert [line["productCode"] for line in wire(built.payload)["lines"]] == ["PRD-ZZ", "PRD-AA"]


@pytest.mark.parametrize("source", list(PaymentSource))
def test_payment_received_becomes_its_payload_with_every_field_equal_to_the_supplied_value(
    source: PaymentSource,
) -> None:
    built = build_fact(narrow(payment_received(source)))

    assert_envelope(built.envelope, "payment.received.v1")
    assert wire(built.payload) == {
        "orderReference": ORDER_REFERENCE,
        "invoiceReference": "INV-000456",
        "paymentReference": "PAY-77-ABC",
        "currency": "EUR",
        "amount": 8115,
        "valueDate": "2026-10-10T18:05:09.987Z",
        "source": source.value,
    }, "a field of the payment.received.v1 payload is not the supplied value"
    assert built.occurred_at == datetime(2026, 10, 8, 9, 30, 5, 123000, tzinfo=UTC)
