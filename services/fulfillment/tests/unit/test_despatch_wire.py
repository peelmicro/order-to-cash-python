"""`fulfillment.despatch.create` on the wire and through the responder, and its row of the error
mapping (`design.md` 8.5; R36, F8; feature 18).

* the request decoder: one case per constraint of `DespatchCreateRequestPayload` -> refused, each
  with an accepted sibling at its boundary; the ids of the command are the HEADERS' (equality with
  the values the test chose);
* the responder: a request that fails validation, or whose headers are absent or malformed, is
  answered `VALIDATION_FAILED` and nothing is dispatched (the control: the same body with valid
  headers IS dispatched);
* the reply: every field from a distinct source value, `created: false` written (never omitted);
* the error table: the despatch refusals and the transient inconsistency, by code AND details.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_contracts import from_wire_json
from otc_contracts.generated import asyncapi
from otc_contracts.generated.asyncapi import Code, RpcError
from otc_fulfillment.application.despatch_creation import NoReservedStockForDespatchError
from otc_fulfillment.application.messages import CreateDespatchCommand, DespatchResult
from otc_fulfillment.application.ports.stock_store import ConcurrentDespatchChangeError
from otc_fulfillment.domain.snapshot import DespatchLineSnapshot, DespatchSnapshot
from otc_fulfillment.presentation import stock_wire
from otc_fulfillment.presentation.stock_headers import RpcCorrelation
from otc_fulfillment.presentation.stock_responder import ROUTES, StockResponder
from otc_fulfillment.presentation.stock_rpc_errors import map_error
from otc_shared_kernel import DespatchReference, UniqueId

CORRELATION_ID = uuid.UUID(int=0xC0)
REQUEST_ID = uuid.UUID(int=0xCA)
CORRELATION = RpcCorrelation(
    correlation_id=UniqueId(CORRELATION_ID), request_id=UniqueId(REQUEST_ID)
)
HEADERS = {"x-correlation-id": str(CORRELATION_ID), "x-request-id": str(REQUEST_ID)}
SUBJECT = "fulfillment.despatch.create"
NOW = datetime(2026, 10, 8, 9, 0, 0, 123000, tzinfo=UTC)
BODY = json.dumps({"orderReference": "ORD-000042"}).encode()


def enc(body: object) -> bytes:
    return json.dumps(body).encode()


# ------------------------------------------------------------------------------- the decoder

REFUSED: list[tuple[str, object]] = [
    ("missing orderReference", {}),
    ("orderReference empty", {"orderReference": ""}),
    ("orderReference without the prefix", {"orderReference": "000042"}),
    ("orderReference with five digits", {"orderReference": "ORD-00042"}),
    ("orderReference lower case", {"orderReference": "ord-000042"}),
    ("orderReference a number", {"orderReference": 42}),
    ("orderReference null", {"orderReference": None}),
    ("orderReference longer than the column", {"orderReference": "ORD-" + "1" * 17}),
]


@pytest.mark.parametrize(("label", "body"), REFUSED, ids=[label for label, _ in REFUSED])
def test_f2_each_constraint_violation_of_the_despatch_request_is_refused_by_the_decoder(
    label: str, body: object
) -> None:
    with pytest.raises(stock_wire.InvalidStockRequestError):
        stock_wire.decode_despatch(enc(body), CORRELATION)


@pytest.mark.parametrize("raw", [b"", b"not json", b"{", b"null", b"[]"])
def test_f2_a_despatch_body_that_is_not_a_json_object_is_refused(raw: bytes) -> None:
    with pytest.raises(stock_wire.InvalidStockRequestError):
        stock_wire.decode_despatch(raw, CORRELATION)


def test_f2_the_boundary_values_of_the_despatch_request_are_accepted() -> None:
    twenty = "ORD-" + "1" * 16
    assert len(twenty) == 20
    assert stock_wire.decode_despatch(enc({"orderReference": twenty}), CORRELATION).order_reference
    usual = stock_wire.decode_despatch(enc({"orderReference": "ORD-000042"}), CORRELATION)
    assert usual.order_reference == "ORD-000042"


def test_fs3_the_despatch_command_carries_the_correlation_and_request_ids_of_the_headers() -> None:
    command = stock_wire.decode_despatch(BODY, CORRELATION)

    assert command == CreateDespatchCommand(
        order_reference="ORD-000042",
        correlation_id=UniqueId(CORRELATION_ID),
        request_id=UniqueId(REQUEST_ID),
    )
    assert command.correlation_id != command.request_id


# ------------------------------------------------------------------------------- the responder


class RecordingDispatcher:
    def __init__(self, result: DespatchResult | None = None) -> None:
        self.commands: list[Any] = []
        self.result = result

    async def send(self, command: Any, scope: Any) -> Any:
        self.commands.append(command)
        return self.result


class FakeMessage:
    def __init__(self, data: bytes, headers: dict[str, str] | None) -> None:
        self.data = data
        self.reply = "_INBOX.x"
        self.headers = headers
        self.replies: list[bytes] = []

    async def respond(self, data: bytes) -> None:
        self.replies.append(data)


class FakeClock:
    def now(self) -> datetime:
        return NOW


def responder(dispatcher: RecordingDispatcher) -> StockResponder:
    return StockResponder(
        connection=None,  # type: ignore[arg-type]
        dispatcher=dispatcher,  # type: ignore[arg-type]
        scope_factory=lambda: None,  # type: ignore[arg-type,return-value]
        clock=FakeClock(),
        max_concurrent_requests=2,
    )


async def serve(dispatcher: RecordingDispatcher, message: FakeMessage) -> bytes:
    await asyncio.wait_for(responder(dispatcher)._serve(SUBJECT, message), timeout=5)  # type: ignore[arg-type]
    [reply] = message.replies
    return reply


def test_the_despatch_subject_is_one_entry_of_the_responders_subject_table() -> None:
    assert SUBJECT in ROUTES
    assert len(ROUTES) == 6


HEADER_FAULTS: dict[str, dict[str, str] | None] = {
    "no headers at all": None,
    "empty headers": {},
    "correlation missing": {"x-request-id": str(REQUEST_ID)},
    "request missing": {"x-correlation-id": str(CORRELATION_ID)},
    "correlation malformed": {"x-correlation-id": "not-a-uuid", "x-request-id": str(REQUEST_ID)},
    "request malformed": {"x-correlation-id": str(CORRELATION_ID), "x-request-id": "1234"},
    "correlation the nil id": {
        "x-correlation-id": str(uuid.UUID(int=0)),
        "x-request-id": str(REQUEST_ID),
    },
}


@pytest.mark.parametrize("fault", sorted(HEADER_FAULTS))
async def test_fs3_despatch_replies_validation_failed_and_dispatches_nothing_when_a_header_is_missing_or_malformed(  # noqa: E501
    fault: str,
) -> None:
    dispatcher = RecordingDispatcher()

    reply = await serve(dispatcher, FakeMessage(BODY, HEADER_FAULTS[fault]))

    assert from_wire_json(RpcError, reply).code is Code.validation_failed
    assert dispatcher.commands == [], "nothing was dispatched"


async def test_fs3_control_the_same_body_with_valid_headers_is_dispatched() -> None:
    dispatcher = RecordingDispatcher(_result(created=True))

    reply = await serve(dispatcher, FakeMessage(BODY, HEADERS))

    assert "code" not in json.loads(reply)
    [command] = dispatcher.commands
    assert command.correlation_id == UniqueId(CORRELATION_ID)
    assert command.request_id == UniqueId(REQUEST_ID)


@pytest.mark.parametrize(("label", "body"), REFUSED, ids=[label for label, _ in REFUSED])
async def test_f2_each_despatch_violation_is_answered_validation_failed_and_nothing_is_dispatched(
    label: str, body: object
) -> None:
    dispatcher = RecordingDispatcher()

    reply = await serve(dispatcher, FakeMessage(enc(body), HEADERS))

    assert from_wire_json(RpcError, reply).code is Code.validation_failed, label
    assert dispatcher.commands == []


async def test_a_despatch_with_an_empty_body_is_answered_validation_failed() -> None:
    dispatcher = RecordingDispatcher()

    reply = await serve(dispatcher, FakeMessage(b"", HEADERS))

    assert from_wire_json(RpcError, reply).code is Code.validation_failed
    assert dispatcher.commands == []


# --------------------------------------------------------------------------------- the reply


def _result(*, created: bool) -> DespatchResult:
    return DespatchResult(
        created=created,
        despatch=DespatchSnapshot(
            id=UniqueId(uuid.UUID(int=0xD1)),
            despatch_reference=DespatchReference("DES-000031"),
            despatch_date=NOW,
            order_reference="ORD-000042",
            company_code="CMP-88",
            retailer_code="RET-77",
            lines=(
                DespatchLineSnapshot(
                    id=UniqueId(uuid.UUID(int=0x11)), product_code="PRD-A1", units=3
                ),
                DespatchLineSnapshot(
                    id=UniqueId(uuid.UUID(int=0x12)), product_code="PRD-B2", units=5
                ),
            ),
        ),
    )


@pytest.mark.parametrize("created", [True, False])
def test_r36_the_despatch_reply_carries_every_field_of_the_advice_and_the_created_flag(
    created: bool,
) -> None:
    raw = stock_wire.encode(stock_wire.despatch_reply(_result(created=created)))

    assert json.loads(raw) == {
        "orderReference": "ORD-000042",
        "despatchReference": "DES-000031",
        "despatchDate": "2026-10-08T09:00:00.123Z",
        "created": created,  # `false` is WRITTEN on the repeat, never omitted
        "lines": [
            {"productCode": "PRD-A1", "units": 3},
            {"productCode": "PRD-B2", "units": 5},
        ],
    }
    assert from_wire_json(asyncapi.DespatchCreateReplyPayload, raw)


# ---------------------------------------------------------------------------- the error table


def test_r36_no_reserved_stock_is_precondition_failed_with_the_order_reference() -> None:
    rpc = map_error(NoReservedStockForDespatchError("ORD-000042"), NOW, UniqueId(CORRELATION_ID))

    assert rpc.code is Code.precondition_failed
    assert rpc.details == {"orderReference": "ORD-000042"}
    assert "ORD-000042" in rpc.message
    assert rpc.correlation_id == CORRELATION_ID
    assert rpc.occurred_at == NOW


def test_f8_consumed_reservations_without_an_advice_are_unavailable_a_transient_answer() -> None:
    rpc = map_error(ConcurrentDespatchChangeError("ORD-000042"), NOW, None)

    assert rpc.code is Code.unavailable
    assert rpc.details is None


def test_f8_a_unique_violation_on_the_order_reference_is_internal_error_a_transient_answer() -> (
    None
):
    # the unique key is F8's last line: if two advices were ever inserted, the second transaction
    # fails with 23505 and is answered INTERNAL_ERROR (retried; the retry takes the fast path)
    from sqlalchemy.exc import IntegrityError

    class Driver(Exception):
        sqlstate = "23505"

    rpc = map_error(IntegrityError("INSERT INTO despatches", {}, Driver()), NOW, None)

    assert rpc.code is Code.internal_error
    assert "despatches" not in rpc.message
