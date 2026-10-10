"""`billing.payment.register` on the wire (feature 22; R47 - R49; #8's N2 class: a field corrupted
between the request and the command with the suite green).

The request is decoded from BYTES and every command field is asserted against a value that differs
from every other (the amount 8115 is neither the gross nor the limit; the id, the correlation and
the request are three UUIDs). The reply is parsed from the bytes `to_wire_json` writes.

Loop scope: nothing here is async.
"""

import json
import uuid
from datetime import UTC, datetime

import pytest

from otc_billing.application.messages import PaymentOutcome, PaymentRegisterResult
from otc_billing.domain.invoice_events import PaymentSource
from otc_billing.domain.invoice_state import InvoiceStatus
from otc_billing.presentation import payment_wire
from otc_billing.presentation.credit_headers import RpcCorrelation
from otc_billing.presentation.payment_wire import InvalidPaymentRequestError
from otc_shared_kernel import UniqueId

INVOICE = "11111111-2222-4333-8444-555555555555"
CORRELATION = UniqueId(uuid.UUID(int=0xC0))
REQUEST = UniqueId(uuid.UUID(int=0xD0))
HEADERS = RpcCorrelation(correlation_id=CORRELATION, request_id=REQUEST)


def body(**overrides: object) -> bytes:
    base: dict[str, object] = {
        "invoiceId": INVOICE,
        "paymentReference": "BANK-REF-7731",
        "amount": {"amount": 8115, "currency": "EUR"},
        "valueDate": "2026-10-09T13:45:10.123987+02:00",
        "source": "robot",
    }
    return json.dumps({**base, **overrides}).encode()


def test_every_command_field_is_the_requests_own_value() -> None:
    command = payment_wire.decode_register(body(), HEADERS)

    assert command.invoice_id == UniqueId(uuid.UUID(INVOICE))
    assert command.invoice_reference is None
    assert command.payment_reference == "BANK-REF-7731"
    assert (command.amount.amount, command.amount.currency) == (8115, "EUR")
    assert command.source is PaymentSource.ROBOT
    assert command.correlation_id == CORRELATION
    assert command.request_id == REQUEST
    # cut (never rounded) to the millisecond and converted to UTC: the stored column, the fact's
    # valueDate and the request name the same instant (OI19; #8's N2)
    assert command.value_date == datetime(2026, 10, 9, 11, 45, 10, 123000, tzinfo=UTC)


def test_the_reference_alone_is_enough_to_name_the_invoice() -> None:
    raw = json.loads(body())
    del raw["invoiceId"]
    raw["invoiceReference"] = "INV-000042"

    command = payment_wire.decode_register(json.dumps(raw).encode(), HEADERS)

    assert command.invoice_id is None
    assert command.invoice_reference == "INV-000042"


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps({k: v for k, v in json.loads(body()).items() if k != "invoiceId"}).encode(),
        body(paymentReference=""),
        body(paymentReference="X" * 31),
        body(amount={"amount": 81.15, "currency": "EUR"}),
        body(amount={"amount": 8115, "currency": "eur"}),
        body(source="bank"),
        body(valueDate="2026-10-09T13:45:10"),
        body(invoiceReference="INV-1"),
        b"not json",
    ],
    ids=[
        "neither invoiceId nor invoiceReference",
        "empty paymentReference",
        "paymentReference over 30",
        "a float amount",
        "a lower-case currency",
        "an unknown source",
        "a naive valueDate",
        "a malformed invoiceReference",
        "not JSON",
    ],
)
def test_a_request_that_fails_the_schema_or_the_edge_check_is_invalid(raw: bytes) -> None:
    with pytest.raises(InvalidPaymentRequestError):
        payment_wire.decode_register(raw, HEADERS)


@pytest.mark.parametrize("outcome", list(PaymentOutcome))
def test_the_reply_carries_the_outcome_the_references_the_status_and_the_millisecond_instant(
    outcome: PaymentOutcome,
) -> None:
    paid_at = datetime(2026, 10, 11, 17, 45, 59, 987000, tzinfo=UTC)
    reply = payment_wire.register_reply(
        PaymentRegisterResult(
            outcome=outcome,
            payment_reference="BANK-REF-7731",
            invoice_reference="INV-000042",
            order_reference="ORD-000101",
            invoice_status=InvoiceStatus.PAID,
            paid_at=paid_at,
        )
    )

    written = json.loads(payment_wire.encode(reply))

    assert written == {
        "outcome": outcome.value,
        "paymentReference": "BANK-REF-7731",
        "invoiceReference": "INV-000042",
        "orderReference": "ORD-000101",
        "invoiceStatus": "paid",
        "paidAt": "2026-10-11T17:45:59.987Z",
    }
