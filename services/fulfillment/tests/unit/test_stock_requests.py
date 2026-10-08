"""F2 / FS28: one case per constraint of each request schema -> `VALIDATION_FAILED`, nothing
dispatched. The generated models are the validator (strict integers, lengths, patterns, enums,
`minItems`); the two checks the schema cannot express are the headers (F3) and `orderReference`
longer than the `varchar(20)` column (FS28).
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_contracts import from_wire_json
from otc_contracts.generated.asyncapi import Code, RpcError, StockReserveRequestPayload
from otc_fulfillment.presentation import stock_wire
from otc_fulfillment.presentation.stock_headers import RpcCorrelation
from otc_fulfillment.presentation.stock_responder import StockResponder
from otc_shared_kernel import UniqueId

CORRELATION = RpcCorrelation(
    correlation_id=UniqueId(uuid.UUID(int=0xC0)), request_id=UniqueId(uuid.UUID(int=0xCA))
)
HEADERS = {"x-correlation-id": str(uuid.UUID(int=0xC0)), "x-request-id": str(uuid.UUID(int=0xCA))}
LINE = {"productCode": "PRD-A1", "units": 3}
CHECK_LINE = {"productCode": "PRD-A1", "quantity": 3}
REF = "ORD-000042"
SUBJECT = {
    "check": "fulfillment.stock.check",
    "reserve": "fulfillment.stock.reserve",
    "release": "fulfillment.stock.release",
    "list": "fulfillment.stock.list",
    "replenish": "fulfillment.stock.replenish",
}


def reserve(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "orderReference": REF,
        "retailerCode": "RET-9",
        "companyCode": "ACME-CO",
        "lines": [LINE],
    }
    return {k: v for k, v in (base | changes).items() if v is not ...}


def check(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"companyCode": "ACME-CO", "lines": [CHECK_LINE]}
    return {k: v for k, v in (base | changes).items() if v is not ...}


def release(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"orderReference": REF, "reason": "order_cancelled"}
    return {k: v for k, v in (base | changes).items() if v is not ...}


def replenish(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"companyCode": "ACME-CO", "lines": [LINE]}
    return {k: v for k, v in (base | changes).items() if v is not ...}


# (kind, label, body): each ONE constraint broken; `...` removes a field
CASES: list[tuple[str, str, Any]] = [
    ("check", "missing companyCode", check(companyCode=...)),
    ("check", "companyCode not a string", check(companyCode=5)),
    ("check", "companyCode empty", check(companyCode="")),
    ("check", "companyCode over 20", check(companyCode="C" * 21)),
    ("check", "missing lines", check(lines=...)),
    ("check", "empty lines", check(lines=[])),
    ("check", "quantity as a string", check(lines=[{**CHECK_LINE, "quantity": "5"}])),
    ("check", "quantity 5.0", check(lines=[{**CHECK_LINE, "quantity": 5.0}])),
    ("check", "quantity true", check(lines=[{**CHECK_LINE, "quantity": True}])),
    ("check", "quantity zero", check(lines=[{**CHECK_LINE, "quantity": 0}])),
    ("check", "quantity negative", check(lines=[{**CHECK_LINE, "quantity": -1}])),
    ("check", "productCode over 30", check(lines=[{**CHECK_LINE, "productCode": "P" * 31}])),
    ("check", "not an object", []),
    ("reserve", "missing orderReference", reserve(orderReference=...)),
    ("reserve", "orderReference without the prefix", reserve(orderReference="000042")),
    ("reserve", "orderReference lower case", reserve(orderReference="ord-000042")),
    ("reserve", "orderReference too few digits", reserve(orderReference="ORD-12345")),
    ("reserve", "missing retailerCode", reserve(retailerCode=...)),
    ("reserve", "retailerCode over 20", reserve(retailerCode="R" * 21)),
    ("reserve", "missing companyCode", reserve(companyCode=...)),
    ("reserve", "empty lines", reserve(lines=[])),
    ("reserve", "units as a string", reserve(lines=[{**LINE, "units": "5"}])),
    ("reserve", "units 5.0", reserve(lines=[{**LINE, "units": 5.0}])),
    ("reserve", "units true", reserve(lines=[{**LINE, "units": True}])),
    ("reserve", "units zero", reserve(lines=[{**LINE, "units": 0}])),
    ("reserve", "units negative", reserve(lines=[{**LINE, "units": -3}])),
    ("reserve", "FS28: 21 characters, pattern-valid", reserve(orderReference="ORD-" + "1" * 17)),
    ("release", "missing orderReference", release(orderReference=...)),
    ("release", "missing reason", release(reason=...)),
    ("release", "unknown reason", release(reason="customer_changed_mind")),
    ("release", "reason of another vocabulary", release(reason="stock_rejected")),
    ("release", "FS28: 21 characters, pattern-valid", release(orderReference="ORD-" + "1" * 17)),
    ("list", "pageSize 201", {"pageSize": 201}),
    ("list", "pageSize zero", {"pageSize": 0}),
    ("list", "page zero", {"page": 0}),
    ("list", "page as a string", {"page": "1"}),
    ("list", "belowThreshold as a string", {"belowThreshold": "yes"}),
    ("list", "companyCode empty", {"companyCode": ""}),
    ("replenish", "missing companyCode", replenish(companyCode=...)),
    ("replenish", "empty lines", replenish(lines=[])),
    ("replenish", "units zero", replenish(lines=[{**LINE, "units": 0}])),
    ("replenish", "units 5.0", replenish(lines=[{**LINE, "units": 5.0}])),
]
DECODERS: dict[str, Callable[[bytes], object]] = {
    "check": stock_wire.decode_check,
    "reserve": lambda body: stock_wire.decode_reserve(body, CORRELATION),
    "release": lambda body: stock_wire.decode_release(body, CORRELATION),
    "list": stock_wire.decode_list,
    "replenish": stock_wire.decode_replenish,
}


@pytest.mark.parametrize(("kind", "label", "body"), CASES, ids=[f"{k}:{c}" for k, c, _ in CASES])
def test_f2_each_constraint_violation_is_refused_by_the_decoder(
    kind: str, label: str, body: Any
) -> None:
    with pytest.raises(stock_wire.InvalidStockRequestError):
        DECODERS[kind](json.dumps(body).encode())


@pytest.mark.parametrize("raw", [b"", b"not json", b"{", b"null"])
def test_f2_a_body_that_is_not_a_json_object_is_refused(raw: bytes) -> None:
    for decode in DECODERS.values():
        with pytest.raises(stock_wire.InvalidStockRequestError):
            decode(raw)


def enc(body: object) -> bytes:
    return json.dumps(body).encode()


def test_f2_the_boundary_values_the_schema_allows_are_accepted() -> None:
    # controls: each refused case above has an accepted sibling at its boundary
    assert stock_wire.decode_list(b'{"pageSize":200}').page_size == 200
    assert stock_wire.decode_list(b"{}").page_size == 25
    assert stock_wire.decode_list(b"{}").page == 1
    twenty = "ORD-" + "1" * 16
    assert len(twenty) == 20
    command = stock_wire.decode_reserve(enc(reserve(orderReference=twenty)), CORRELATION)
    assert command.order_reference == twenty
    assert stock_wire.decode_check(enc(check(companyCode="C" * 20))).company_code == "C" * 20
    release_command = stock_wire.decode_release(enc(release()), CORRELATION)
    assert release_command.reason.value == "order_cancelled"
    assert stock_wire.decode_replenish(enc(replenish())).lines[0].units.value == 3


def test_fs28_a_reference_longer_than_the_column_is_refused_as_validation_failed() -> None:
    twenty_one = "ORD-" + "1" * 17
    assert len(twenty_one) == 21

    with pytest.raises(stock_wire.InvalidStockRequestError, match="20 characters"):
        stock_wire.decode_reserve(enc(reserve(orderReference=twenty_one)), CORRELATION)
    with pytest.raises(stock_wire.InvalidStockRequestError, match="20 characters"):
        stock_wire.decode_release(enc(release(orderReference=twenty_one)), CORRELATION)
    # the pattern alone accepts it: this is the schema's gap the edge check closes
    assert from_wire_json(StockReserveRequestPayload, enc(reserve(orderReference=twenty_one)))


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
async def test_f2_each_violation_is_answered_validation_failed_and_nothing_is_dispatched(
    kind: str, label: str, body: Any
) -> None:
    dispatcher = RecordingDispatcher()
    responder = StockResponder(
        connection=None,  # type: ignore[arg-type]
        dispatcher=dispatcher,  # type: ignore[arg-type]
        scope_factory=lambda: None,  # type: ignore[arg-type,return-value]
        clock=FakeClock(),
        max_concurrent_requests=2,
    )
    message = FakeMessage(json.dumps(body).encode(), headers=HEADERS)

    await asyncio.wait_for(responder._serve(SUBJECT[kind], message), timeout=5)  # type: ignore[arg-type]

    assert dispatcher.calls == 0
    [reply] = message.replies
    error = from_wire_json(RpcError, reply)
    assert error.code is Code.validation_failed, (label, error)
