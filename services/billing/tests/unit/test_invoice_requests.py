"""Every schema constraint and every edge check of `billing.invoice.issue` / `.list` ->
`VALIDATION_FAILED`, with the dispatcher called ZERO times (task E3; BI2, BI33).

#7's review `N2` / `N10`, inherited through #8: a refusal made inside the transaction would leave
the same residue as one made before it, so the placement is proven by OBSERVING THE ENTRY -- the
recording dispatcher counts its calls. The generated model is the validator for the schema half
(strict integers, patterns, `minItems`, `units >= 1`); the edge checks are `unitPrice >= 0`,
`discount >= 0`, `discount <= sum(unitPrice x units)`, and BI33's three bounds. Boundary controls
accept the neighbouring valid values.

Loop scope: function (pytest-asyncio default); only in-memory fakes are awaited.
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_billing.presentation import invoice_wire
from otc_billing.presentation.credit_headers import RpcCorrelation
from otc_billing.presentation.credit_responder import CreditResponder
from otc_contracts import from_wire_json
from otc_contracts.generated.asyncapi import Code, RpcError
from otc_shared_kernel import UniqueId

CORRELATION = RpcCorrelation(
    correlation_id=UniqueId(uuid.UUID(int=0xC0)), request_id=UniqueId(uuid.UUID(int=0xD0))
)
HEADERS = {"x-correlation-id": str(uuid.UUID(int=0xC0)), "x-request-id": str(uuid.UUID(int=0xD0))}
ISSUE = "billing.invoice.issue"
LIST = "billing.invoice.list"
LINES = [
    {"productCode": "PRD-ZZ", "units": 3, "unitPrice": 1999},
    {"productCode": "PRD-AA", "units": 2, "unitPrice": 1234},
]  # 8465


def issue(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "orderReference": "ORD-000101",
        "retailerCode": "RETAIL-77",
        "companyCode": "SUPPLY-CO",
        "currency": "EUR",
        "lines": LINES,
        "discount": 350,
    }
    return {k: v for k, v in (base | changes).items() if v is not ...}


def line(units: Any = 1, price: Any = 100, code: str = "PRD-AA") -> dict[str, Any]:
    return {"productCode": code, "units": units, "unitPrice": price}


# (subject, label, body): each ONE constraint broken; `...` removes a field
CASES: list[tuple[str, str, Any]] = [
    (ISSUE, "missing orderReference", issue(orderReference=...)),
    (ISSUE, "orderReference without the prefix", issue(orderReference="000101")),
    (ISSUE, "orderReference lower case", issue(orderReference="ord-000101")),
    (ISSUE, "missing retailerCode", issue(retailerCode=...)),
    (ISSUE, "retailerCode over 20", issue(retailerCode="R" * 21)),
    (ISSUE, "missing companyCode", issue(companyCode=...)),
    (ISSUE, "companyCode empty", issue(companyCode="")),
    (ISSUE, "missing currency", issue(currency=...)),
    (ISSUE, "a lower-case currency", issue(currency="eur")),
    (ISSUE, "a four-letter currency", issue(currency="EURO")),
    (ISSUE, "missing lines", issue(lines=...)),
    (ISSUE, "empty lines", issue(lines=[])),
    (ISSUE, "units zero", issue(lines=[line(units=0)])),
    (ISSUE, "units negative", issue(lines=[line(units=-1)])),
    (ISSUE, "units a string", issue(lines=[line(units="2")])),
    (ISSUE, "units 2.0", issue(lines=[line(units=2.0)])),
    (ISSUE, "missing productCode", issue(lines=[{"units": 1, "unitPrice": 100}])),
    (ISSUE, "empty productCode", issue(lines=[line(code="")])),
    (ISSUE, "productCode over 30", issue(lines=[line(code="P" * 31)])),
    (ISSUE, "unitPrice as a string", issue(lines=[line(price="100")])),
    (ISSUE, "unitPrice above int64", issue(lines=[line(price=2**63)])),
    (ISSUE, "discount as a string", issue(discount="350")),
    (ISSUE, "discount above int64", issue(discount=2**63)),
    (ISSUE, "not an object", []),
    (ISSUE, "BI2: a negative unitPrice", issue(lines=[*LINES, line(price=-1, code="PRD-NEG")])),
    (ISSUE, "BI2: a negative discount", issue(discount=-1)),
    (ISSUE, "BI2: discount one minor unit above the sum", issue(discount=8466)),
    (ISSUE, "BI33: orderReference of 21 characters", issue(orderReference="ORD-" + "1" * 17)),
    (ISSUE, "BI33: units above int32", issue(lines=[line(units=2_147_483_648, price=0)])),
    (
        ISSUE,
        "BI33: a sum above int64",
        issue(lines=[line(units=2, price=(1 << 62)), line(units=1, price=1, code="PRD-BB")]),
    ),
    (LIST, "page zero", {"page": 0}),
    (LIST, "page as a string", {"page": "1"}),
    (LIST, "pageSize zero", {"pageSize": 0}),
    (LIST, "pageSize 201", {"pageSize": 201}),
    (LIST, "an unknown status", {"status": "settled"}),
    (LIST, "a capitalised status", {"status": "Paid"}),
    (LIST, "retailerCode empty", {"retailerCode": ""}),
    (LIST, "companyCode over 20", {"companyCode": "C" * 21}),
    (LIST, "a malformed orderReference", {"orderReference": "ORD-12"}),
    (LIST, "issuedBeforeMinutes negative", {"issuedBeforeMinutes": -1}),
    (LIST, "issuedBeforeMinutes a string", {"issuedBeforeMinutes": "60"}),
]
DECODERS: dict[str, Callable[[bytes], object]] = {
    ISSUE: lambda body: invoice_wire.decode_issue(body, CORRELATION),
    LIST: invoice_wire.decode_list,
}


def enc(body: object) -> bytes:
    return json.dumps(body).encode()


@pytest.mark.parametrize(("subject", "label", "body"), CASES, ids=[f"{s}:{c}" for s, c, _ in CASES])
def test_each_constraint_violation_is_refused_by_the_decoder(
    subject: str, label: str, body: Any
) -> None:
    try:
        decoded = DECODERS[subject](enc(body))
    except invoice_wire.InvalidInvoiceRequestError:
        return
    pytest.fail(f"the {subject} decoder accepted a request with {label}: {decoded}")


@pytest.mark.parametrize("raw", [b"", b"not json", b"{", b"null"])
def test_a_body_that_is_not_a_json_object_is_refused(raw: bytes) -> None:
    for decode in DECODERS.values():
        with pytest.raises(invoice_wire.InvalidInvoiceRequestError):
            decode(raw)


def test_the_boundary_values_the_schema_and_the_edge_allow_are_accepted() -> None:
    # discount == the sum is a zero total, legal; discount absent is zero
    assert invoice_wire.decode_issue(enc(issue(discount=8465)), CORRELATION).discount == 8465
    absent = invoice_wire.decode_issue(enc(issue(discount=...)), CORRELATION)
    assert absent.discount == 0
    # the largest units, price zero
    big = invoice_wire.decode_issue(
        enc(issue(lines=[line(units=2_147_483_647, price=0)], discount=0)), CORRELATION
    )
    assert big.lines[0].units == 2_147_483_647
    # the sum exactly at int64's maximum
    top = invoice_wire.decode_issue(
        enc(issue(lines=[line(units=1, price=(1 << 63) - 1)], discount=0)), CORRELATION
    )
    assert top.lines[0].unit_price == (1 << 63) - 1
    # orderReference of exactly 20 characters
    twenty = "ORD-" + "1" * 16
    assert len(twenty) == 20
    assert invoice_wire.decode_issue(enc(issue(orderReference=twenty)), CORRELATION)
    # a zero unit price and a zero discount
    zero = invoice_wire.decode_issue(
        enc(issue(lines=[line(units=1, price=0)], discount=0)), CORRELATION
    )
    assert zero.lines[0].unit_price == 0
    # the decoded command carries the headers and every field
    command = invoice_wire.decode_issue(enc(issue()), CORRELATION)
    assert (command.correlation_id, command.request_id) == (
        CORRELATION.correlation_id,
        CORRELATION.request_id,
    )
    assert command.discount == 350
    assert [(ln.product_code, ln.units, ln.unit_price) for ln in command.lines] == [
        ("PRD-ZZ", 3, 1999),
        ("PRD-AA", 2, 1234),
    ]
    # the list defaults and the full filter set
    default = invoice_wire.decode_list(b"{}")
    assert (default.page, default.page_size, default.status) == (1, 25, None)
    full = invoice_wire.decode_list(
        enc(
            {
                "page": 2,
                "pageSize": 200,
                "status": "paid",
                "retailerCode": "RETAIL-77",
                "companyCode": "SUPPLY-CO",
                "orderReference": "ORD-000101",
                "issuedBeforeMinutes": 0,
            }
        )
    )
    assert (full.page, full.page_size, full.status.value if full.status else None) == (
        2,
        200,
        "paid",
    )
    assert (full.retailer_code, full.company_code, full.order_reference) == (
        "RETAIL-77",
        "SUPPLY-CO",
        "ORD-000101",
    )
    assert full.issued_before_minutes == 0


def _refused(decode: Callable[[], object], what: str, match: str) -> None:
    try:
        accepted = decode()
    except invoice_wire.InvalidInvoiceRequestError as error:
        message = str(error)
    else:
        pytest.fail(f"{what} was accepted: {accepted}")
    assert match in message, what


def test_bi2_the_edge_checks_each_name_their_field() -> None:
    _refused(
        lambda: invoice_wire.decode_issue(
            enc(issue(lines=[*LINES, line(price=-1, code="PRD-NEG")])), CORRELATION
        ),
        "a negative unitPrice",
        "unitPrice",
    )
    _refused(
        lambda: invoice_wire.decode_issue(enc(issue(discount=-1)), CORRELATION),
        "a negative discount",
        "discount must not be negative",
    )
    _refused(
        lambda: invoice_wire.decode_issue(enc(issue(discount=8466)), CORRELATION),
        "a discount above the sum",
        "discount exceeds",
    )


# ---------------------------------------------------------------- nothing is dispatched


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    async def send(self, command: Any, scope: Any) -> Any:
        self.calls += 1
        raise AssertionError("a request that fails validation must never be dispatched")

    ask = send


class FakeMessage:
    def __init__(
        self, data: bytes, reply: str = "_INBOX.x", headers: dict[str, str] | None = None
    ) -> None:
        self.data = data
        self.reply = reply
        self.headers = headers
        self.replies: list[bytes] = []

    async def respond(self, data: bytes) -> None:
        self.replies.append(data)


class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 10, 9, tzinfo=UTC)


async def _serve(subject: str, body: Any) -> tuple[RecordingDispatcher, FakeMessage]:
    dispatcher = RecordingDispatcher()
    responder = CreditResponder(
        connection=None,  # type: ignore[arg-type]
        dispatcher=dispatcher,  # type: ignore[arg-type]
        scope_factory=lambda: None,  # type: ignore[arg-type,return-value]
        clock=FakeClock(),
        max_concurrent_requests=2,
    )
    message = FakeMessage(enc(body), headers=HEADERS)
    await asyncio.wait_for(responder._serve(subject, message), timeout=5)  # type: ignore[arg-type]
    return dispatcher, message


@pytest.mark.parametrize(("subject", "label", "body"), CASES, ids=[f"{s}:{c}" for s, c, _ in CASES])
async def test_bi2_refuses_a_malformed_issue_request_with_validation_failed_without_calling_the_dispatcher(  # noqa: E501
    subject: str, label: str, body: Any
) -> None:
    dispatcher, message = await _serve(subject, body)

    assert dispatcher.calls == 0, f"{label}: the request was dispatched"
    [reply] = message.replies
    error = from_wire_json(RpcError, reply)
    assert error.code is Code.validation_failed, (label, error)


async def test_bi33_an_order_reference_over_twenty_characters_units_above_int32_and_a_line_sum_above_int64_are_validation_failed() -> (  # noqa: E501
    None
):
    over = {
        "an orderReference of 21 characters": issue(orderReference="ORD-" + "1" * 17),
        "units above int32": issue(lines=[line(units=2_147_483_648, price=0)], discount=0),
        "a line sum above int64": issue(
            lines=[line(units=2, price=1 << 62), line(units=1, price=1, code="PRD-BB")],
            discount=0,
        ),
    }
    for label, body in over.items():
        dispatcher, message = await _serve(ISSUE, body)
        assert dispatcher.calls == 0, f"{label}: dispatched"
        error = from_wire_json(RpcError, message.replies[0])
        assert error.code is Code.validation_failed, label

    # the boundary controls reach the dispatcher (which, here, refuses to run)
    controls = {
        "an orderReference of 20 characters": issue(orderReference="ORD-" + "1" * 16),
        "units == int32 max": issue(lines=[line(units=2_147_483_647, price=0)], discount=0),
        "a sum == int64 max": issue(lines=[line(units=1, price=(1 << 63) - 1)], discount=0),
        "discount == the sum": issue(discount=8465),
    }
    for label, body in controls.items():
        dispatcher = RecordingDispatcher()
        responder = CreditResponder(
            connection=None,  # type: ignore[arg-type]
            dispatcher=dispatcher,  # type: ignore[arg-type]
            scope_factory=lambda: None,  # type: ignore[arg-type,return-value]
            clock=FakeClock(),
            max_concurrent_requests=2,
        )
        message = FakeMessage(enc(body), headers=HEADERS)
        await asyncio.wait_for(responder._serve(ISSUE, message), timeout=5)  # type: ignore[arg-type]
        assert dispatcher.calls == 1, f"control {label}: refused before the dispatcher"
