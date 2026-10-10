"""One case per constraint of each request schema -> `VALIDATION_FAILED`, nothing dispatched
(task E3). The generated models are the validator (strict integers, lengths, patterns, `pageSize`
at most 200); the two checks the schema cannot express are `orderReference` longer than the
`varchar(20)` column and a negative hold amount (BC33; zero is allowed, BC38). The headers (BC1)
are proven in `test_credit_responder.py`.

Loop scope: function (pytest-asyncio default); only in-memory fakes are awaited.
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_billing.presentation import credit_wire
from otc_billing.presentation.credit_headers import RpcCorrelation
from otc_billing.presentation.credit_responder import CreditResponder
from otc_contracts import from_wire_json
from otc_contracts.generated.asyncapi import Code, CreditHoldRequestPayload, RpcError
from otc_shared_kernel import UniqueId

CORRELATION = RpcCorrelation(
    correlation_id=UniqueId(uuid.UUID(int=0xC0)), request_id=UniqueId(uuid.UUID(int=0xCA))
)
HEADERS = {"x-correlation-id": str(uuid.UUID(int=0xC0)), "x-request-id": str(uuid.UUID(int=0xCA))}
REF = "ORD-000101"
AMOUNT = {"amount": 250, "currency": "EUR"}
SUBJECT = {
    "hold": "billing.credit.hold",
    "release": "billing.credit.release",
    "list": "billing.credit.list",
}


def hold(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "orderReference": REF,
        "retailerCode": "RETAIL-77",
        "companyCode": "SUPPLY-CO",
        "amount": AMOUNT,
    }
    return {k: v for k, v in (base | changes).items() if v is not ...}


def release(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "orderReference": REF,
        "retailerCode": "RETAIL-77",
        "companyCode": "SUPPLY-CO",
    }
    return {k: v for k, v in (base | changes).items() if v is not ...}


# (kind, label, body): each ONE constraint broken; `...` removes a field
CASES: list[tuple[str, str, Any]] = [
    ("hold", "missing orderReference", hold(orderReference=...)),
    ("hold", "orderReference without the prefix", hold(orderReference="000101")),
    ("hold", "orderReference lower case", hold(orderReference="ord-000101")),
    ("hold", "orderReference too few digits", hold(orderReference="ORD-12345")),
    ("hold", "missing retailerCode", hold(retailerCode=...)),
    ("hold", "retailerCode empty", hold(retailerCode="")),
    ("hold", "retailerCode over 20", hold(retailerCode="R" * 21)),
    ("hold", "missing companyCode", hold(companyCode=...)),
    ("hold", "companyCode over 20", hold(companyCode="C" * 21)),
    ("hold", "missing amount", hold(amount=...)),
    ("hold", "amount not an object", hold(amount=250)),
    ("hold", "amount.amount as a string", hold(amount={"amount": "250", "currency": "EUR"})),
    ("hold", "amount.amount 250.0", hold(amount={"amount": 250.0, "currency": "EUR"})),
    ("hold", "amount.amount true", hold(amount={"amount": True, "currency": "EUR"})),
    ("hold", "amount.amount above int64", hold(amount={"amount": 2**63, "currency": "EUR"})),
    ("hold", "amount.currency lower case", hold(amount={"amount": 250, "currency": "eur"})),
    ("hold", "amount.currency four letters", hold(amount={"amount": 250, "currency": "EURO"})),
    ("hold", "amount.currency missing", hold(amount={"amount": 250})),
    ("hold", "BC33: 21 characters, pattern-valid", hold(orderReference="ORD-" + "1" * 17)),
    ("hold", "BC33: a negative amount", hold(amount={"amount": -1, "currency": "EUR"})),
    ("hold", "not an object", []),
    ("release", "missing orderReference", release(orderReference=...)),
    ("release", "orderReference lower case", release(orderReference="ord-000101")),
    ("release", "missing retailerCode", release(retailerCode=...)),
    ("release", "retailerCode over 20", release(retailerCode="R" * 21)),
    ("release", "missing companyCode", release(companyCode=...)),
    ("release", "companyCode empty", release(companyCode="")),
    ("release", "BC33: 21 characters, pattern-valid", release(orderReference="ORD-" + "1" * 17)),
    ("list", "pageSize 201", {"pageSize": 201}),
    ("list", "pageSize zero", {"pageSize": 0}),
    ("list", "page zero", {"page": 0}),
    ("list", "page as a string", {"page": "1"}),
    ("list", "retailerCode empty", {"retailerCode": ""}),
    ("list", "companyCode over 20", {"companyCode": "C" * 21}),
]
DECODERS: dict[str, Callable[[bytes], object]] = {
    "hold": lambda body: credit_wire.decode_hold(body, CORRELATION),
    "release": lambda body: credit_wire.decode_release(body, CORRELATION),
    "list": credit_wire.decode_list,
}


def enc(body: object) -> bytes:
    return json.dumps(body).encode()


@pytest.mark.parametrize(("kind", "label", "body"), CASES, ids=[f"{k}:{c}" for k, c, _ in CASES])
def test_each_constraint_violation_is_refused_by_the_decoder(
    kind: str, label: str, body: Any
) -> None:
    try:
        decoded = DECODERS[kind](enc(body))
    except credit_wire.InvalidCreditRequestError:
        return
    pytest.fail(f"the {kind} decoder accepted a request with {label}: {decoded}")


@pytest.mark.parametrize("raw", [b"", b"not json", b"{", b"null"])
def test_a_body_that_is_not_a_json_object_is_refused(raw: bytes) -> None:
    for kind, decode in DECODERS.items():
        with pytest.raises(credit_wire.InvalidCreditRequestError):
            decode(raw)
        assert kind in DECODERS


def test_the_boundary_values_the_schema_allows_are_accepted() -> None:
    # controls: each refused case above has an accepted sibling at its boundary
    assert credit_wire.decode_list(enc({"pageSize": 200})).page_size == 200
    assert credit_wire.decode_list(b"{}").page_size == 25
    assert credit_wire.decode_list(b"{}").page == 1
    twenty = "ORD-" + "1" * 16
    assert len(twenty) == 20
    assert (
        credit_wire.decode_hold(enc(hold(orderReference=twenty)), CORRELATION).order_reference
        == twenty
    )
    assert credit_wire.decode_release(enc(release(orderReference=twenty)), CORRELATION)
    command = credit_wire.decode_hold(enc(hold()), CORRELATION)
    assert (command.amount.amount, command.amount.currency) == (250, "EUR")
    assert (command.retailer_code, command.company_code) == ("RETAIL-77", "SUPPLY-CO")
    assert (command.correlation_id, command.request_id) == (
        CORRELATION.correlation_id,
        CORRELATION.request_id,
    )


def _refused(decode: Callable[[], object], what: str, match: str) -> None:
    try:
        accepted = decode()
    except credit_wire.InvalidCreditRequestError as error:
        message = str(error)
    else:
        pytest.fail(f"BC33: {what} was accepted: {accepted}")
    assert match in message, what


def test_bc33_an_order_reference_over_twenty_characters_is_validation_failed() -> None:
    twenty_one = "ORD-" + "1" * 17
    assert len(twenty_one) == 21
    _refused(
        lambda: credit_wire.decode_hold(enc(hold(orderReference=twenty_one)), CORRELATION),
        "a 21-character orderReference on credit.hold",
        "20 characters",
    )
    _refused(
        lambda: credit_wire.decode_release(enc(release(orderReference=twenty_one)), CORRELATION),
        "a 21-character orderReference on credit.release",
        "20 characters",
    )
    # the pattern alone accepts it: this is the schema's gap the edge check closes
    assert from_wire_json(CreditHoldRequestPayload, enc(hold(orderReference=twenty_one)))


def test_bc33_a_negative_hold_amount_is_validation_failed() -> None:
    negative = enc(hold(amount={"amount": -1, "currency": "EUR"}))
    # the schema alone accepts it (the shared Money admits a negative amount)
    assert from_wire_json(CreditHoldRequestPayload, negative)
    _refused(
        lambda: credit_wire.decode_hold(negative, CORRELATION), "a negative hold amount", "negative"
    )
    # zero is allowed (BC38, gate point G1 as recommended)
    zero = credit_wire.decode_hold(enc(hold(amount={"amount": 0, "currency": "EUR"})), CORRELATION)
    assert zero.amount.amount == 0


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
        return datetime(2026, 10, 8, tzinfo=UTC)


@pytest.mark.parametrize(("kind", "label", "body"), CASES, ids=[f"{k}:{c}" for k, c, _ in CASES])
async def test_each_violation_is_answered_validation_failed_and_nothing_is_dispatched(
    kind: str, label: str, body: Any
) -> None:
    dispatcher = RecordingDispatcher()
    responder = CreditResponder(
        connection=None,  # type: ignore[arg-type]
        dispatcher=dispatcher,  # type: ignore[arg-type]
        scope_factory=lambda: None,  # type: ignore[arg-type,return-value]
        clock=FakeClock(),
        max_concurrent_requests=2,
    )
    message = FakeMessage(enc(body), headers=HEADERS)

    await asyncio.wait_for(responder._serve(SUBJECT[kind], message), timeout=5)  # type: ignore[arg-type]

    assert dispatcher.calls == 0, f"{label}: the request was dispatched"
    [reply] = message.replies
    error = from_wire_json(RpcError, reply)
    assert error.code is Code.validation_failed, (label, error)
