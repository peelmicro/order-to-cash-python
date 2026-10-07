# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""`SagaCommandDispatcher` with fakes: the retry policy and the claim rules (8.6; SO4, SO6, SO16, R29).

The sleep and the clock are fakes, so the back-off schedule is the list of durations the dispatcher
asked to sleep, and the whole file runs instantly.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from otc_contracts import from_wire_json
from otc_contracts.generated.asyncapi import StockReserveReplyPayload
from otc_orders.application.ports.saga_command_store import ClaimedCommand
from otc_orders.application.ports.saga_commands import (
    SagaCommandBusinessRejectionError,
    SagaCommandMeta,
    SagaCommandRpcError,
    SagaCommandTimeoutError,
    SagaCommandTransportError,
)
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.infrastructure.saga.command_dispatcher import DispatchOutcome, SagaCommandDispatcher
from otc_shared_kernel import UniqueId

ORDER = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000d1"))
ROW_ID = uuid.UUID("00000000-0000-4000-8000-00000000a0a0")
TRIGGER = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000e1"))
NOW = datetime(2026, 10, 7, 12, 0, 0, 500000, tzinfo=UTC)
PAYLOAD = '{"orderReference":"ORD-000007","stored":"as committed"}'


def row(kind: SagaCommandKind = SagaCommandKind.STOCK_RESERVE, attempts: int = 0) -> ClaimedCommand:
    return ClaimedCommand(
        id=ROW_ID,
        order_id=ORDER,
        order_reference="ORD-000007",
        kind=kind,
        payload=PAYLOAD,
        attempts=attempts,
        triggering_event_id=TRIGGER,
    )


@dataclass
class FakeLedger:
    claimable: ClaimedCommand | None
    claims: list[tuple[UniqueId, SagaCommandKind]] = field(default_factory=list)
    sent: list[uuid.UUID] = field(default_factory=list)
    parked: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)

    async def try_claim(self, order_id: UniqueId, kind: SagaCommandKind) -> ClaimedCommand | None:
        self.claims.append((order_id, kind))
        return self.claimable

    async def claim_due(self, batch_limit: int) -> list[ClaimedCommand]:
        raise AssertionError("the dispatcher never claims a batch")

    async def mark_sent(self, row_id: uuid.UUID) -> None:
        self.sent.append(row_id)

    async def reject(self, row_id: uuid.UUID, *, total_attempts: int, last_error: str) -> None:
        self.rejected.append(
            {"row_id": row_id, "total_attempts": total_attempts, "last_error": last_error}
        )

    async def park(
        self, row_id: uuid.UUID, *, total_attempts: int, last_error: str, retry_after_ms: int
    ) -> datetime:
        self.parked.append(
            {
                "row_id": row_id,
                "total_attempts": total_attempts,
                "last_error": last_error,
                "retry_after_ms": retry_after_ms,
            }
        )
        return NOW + timedelta(milliseconds=retry_after_ms)


@dataclass
class FakeCommands:
    """Every method records (method, bytes, meta) and answers from `script` (a reply or an error)."""

    script: list[object]
    calls: list[tuple[str, bytes, SagaCommandMeta]] = field(default_factory=list)

    def _answer(self, method: str, request: bytes, meta: SagaCommandMeta) -> object:
        self.calls.append((method, request, meta))
        outcome = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def reserve_stock(self, request: bytes, meta: SagaCommandMeta) -> object:
        return self._answer("reserve_stock", request, meta)

    async def release_stock(self, request: bytes, meta: SagaCommandMeta) -> object:
        return self._answer("release_stock", request, meta)

    async def create_despatch(self, request: bytes, meta: SagaCommandMeta) -> object:
        return self._answer("create_despatch", request, meta)

    async def hold_credit(self, request: bytes, meta: SagaCommandMeta) -> object:
        return self._answer("hold_credit", request, meta)

    async def issue_invoice(self, request: bytes, meta: SagaCommandMeta) -> object:
        return self._answer("issue_invoice", request, meta)

    async def release_credit(self, request: bytes, meta: SagaCommandMeta) -> object:
        return self._answer("release_credit", request, meta)


class FixedClock:
    def now(self) -> datetime:
        return NOW


@dataclass
class Rig:
    dispatcher: SagaCommandDispatcher
    ledger: FakeLedger
    commands: FakeCommands
    sleeps: list[float]


def rig(script: list[object], claimable: ClaimedCommand | None = None, **overrides: Any) -> Rig:
    ledger = FakeLedger(claimable=claimable if claimable is not None else row())
    commands = FakeCommands(script)
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    dispatcher = SagaCommandDispatcher(
        ledger=ledger,
        commands=commands,  # type: ignore[arg-type]
        clock=FixedClock(),
        max_attempts=overrides.get("max_attempts", 3),
        backoff_ms=overrides.get("backoff_ms", 500),
        park_cap_ms=overrides.get("park_cap_ms", 900_000),
        sleep=sleep,
    )
    return Rig(dispatcher, ledger, commands, sleeps)


REPLY = from_wire_json(
    StockReserveReplyPayload, '{"outcome":"accepted","orderReference":"ORD-000007"}'
)


async def test_so4_retries_a_timed_out_command_up_to_max_attempts_with_the_configured_backoff_schedule() -> (
    None
):
    r = rig([SagaCommandTimeoutError("fulfillment.stock.reserve", "no reply within 5000 ms.")])

    outcome = await r.dispatcher.dispatch(ORDER, SagaCommandKind.STOCK_RESERVE)

    assert outcome is DispatchOutcome.PARKED
    assert len(r.commands.calls) == 3, "exactly MaxAttempts calls"
    assert r.sleeps == [0.5, 1.0], "500 ms then 1 000 ms, none after the last attempt"
    assert r.ledger.sent == []


async def test_a_command_succeeding_on_a_retry_is_marked_sent_after_the_pause_before_it() -> None:
    r = rig([SagaCommandTransportError("s", "no responder"), REPLY])

    outcome = await r.dispatcher.dispatch(ORDER, SagaCommandKind.STOCK_RESERVE)

    assert outcome is DispatchOutcome.SENT
    assert len(r.commands.calls) == 2
    assert r.sleeps == [0.5]
    assert r.ledger.sent == [ROW_ID]
    assert r.ledger.parked == []


async def test_so6_a_business_rejection_is_marked_sent_after_exactly_one_attempt() -> None:
    rejected = from_wire_json(
        StockReserveReplyPayload,
        '{"outcome":"rejected","orderReference":"ORD-000007",'
        '"shortages":[{"productCode":"SKU-A","requested":3,"available":1}]}',
    )
    r = rig([rejected])

    outcome = await r.dispatcher.dispatch(ORDER, SagaCommandKind.STOCK_RESERVE)

    assert outcome is DispatchOutcome.SENT
    assert len(r.commands.calls) == 1, "a rejected reply is a reply: never retried"
    assert r.sleeps == []
    assert r.ledger.sent == [ROW_ID]
    assert r.ledger.parked == []


async def test_feature_42_a_terminal_rejection_is_rejected_on_the_first_attempt_never_retried_parked_or_sent() -> (
    None
):
    r = rig([SagaCommandBusinessRejectionError("s", "STOCK_UNAVAILABLE", "nothing left")])

    outcome = await r.dispatcher.dispatch(ORDER, SagaCommandKind.STOCK_RELEASE)

    assert outcome is DispatchOutcome.REJECTED, "the kind of resolution, not only a count"
    assert len(r.commands.calls) == 1, "one attempt: never retried"
    assert r.sleeps == [], "no back-off pause"
    [rejected] = r.ledger.rejected
    assert rejected["row_id"] == ROW_ID
    assert rejected["total_attempts"] == 1
    assert "STOCK_UNAVAILABLE" in rejected["last_error"]
    assert "nothing left" in rejected["last_error"]
    assert r.ledger.parked == [], "reject is not park"
    assert r.ledger.sent == [], "reject is not sent"


async def test_feature_42_a_rejection_after_transient_failures_counts_the_attempts_made_and_stops() -> (
    None
):
    r = rig(
        [
            SagaCommandTimeoutError("s", "no reply"),
            SagaCommandBusinessRejectionError("s", "CONFLICT", "already consumed"),
            REPLY,
        ],
        claimable=row(attempts=3),
    )

    outcome = await r.dispatcher.dispatch(ORDER, SagaCommandKind.STOCK_RELEASE)

    assert outcome is DispatchOutcome.REJECTED
    assert len(r.commands.calls) == 2, "stops at the rejection; the third script entry is unused"
    assert r.sleeps == [0.5], "one pause: the one after the transient failure"
    [rejected] = r.ledger.rejected
    assert rejected["total_attempts"] == 5, "3 earlier attempts + the 2 made this cycle"
    assert r.ledger.parked == r.ledger.sent == []


async def test_feature_42_a_transient_rpc_error_is_still_retried_and_parked_not_rejected() -> None:
    r = rig([SagaCommandRpcError("s", "INTERNAL_ERROR", "boom")])

    outcome = await r.dispatcher.dispatch(ORDER, SagaCommandKind.STOCK_RESERVE)

    assert outcome is DispatchOutcome.PARKED
    assert len(r.commands.calls) == 3
    assert r.ledger.rejected == []


async def test_exhaustion_parks_with_the_accumulated_attempts_and_the_last_error() -> None:
    errors: list[object] = [
        SagaCommandTimeoutError("s", "first"),
        SagaCommandTransportError("s", "second"),
        SagaCommandRpcError("s", "UNAVAILABLE", "third"),
    ]
    r = rig(errors, claimable=row(attempts=3))

    outcome = await r.dispatcher.dispatch(ORDER, SagaCommandKind.STOCK_RESERVE)

    assert outcome is DispatchOutcome.PARKED
    [parked] = r.ledger.parked
    assert parked["row_id"] == ROW_ID
    assert parked["total_attempts"] == 6, "3 earlier attempts + 3 this cycle, not 3"
    assert "third" in parked["last_error"], "the LAST error, not the first"
    assert "first" not in parked["last_error"]
    assert parked["retry_after_ms"] == 120_000, "the second park: 30 s x 2 ** 2"
    assert r.ledger.sent == []


async def test_a_first_park_waits_sixty_seconds_and_the_cap_applies() -> None:
    r = rig([SagaCommandTimeoutError("s", "x")])
    await r.dispatcher.dispatch(ORDER, SagaCommandKind.STOCK_RESERVE)
    assert r.ledger.parked[0]["retry_after_ms"] == 60_000

    capped = rig(
        [SagaCommandTimeoutError("s", "x")], claimable=row(attempts=30), park_cap_ms=70_000
    )
    await capped.dispatcher.dispatch(ORDER, SagaCommandKind.STOCK_RESERVE)
    assert capped.ledger.parked[0]["retry_after_ms"] == 70_000


async def test_a_claim_that_returns_no_row_dispatches_nothing() -> None:
    r = rig([REPLY])
    r.ledger.claimable = None

    outcome = await r.dispatcher.dispatch(ORDER, SagaCommandKind.STOCK_RESERVE)

    assert outcome is DispatchOutcome.NOOP
    assert r.commands.calls == []
    assert r.ledger.sent == r.ledger.parked == []
    assert r.ledger.claims == [(ORDER, SagaCommandKind.STOCK_RESERVE)]


async def test_dispatch_claimed_never_claims() -> None:
    r = rig([REPLY])

    outcome = await r.dispatcher.dispatch_claimed(row())

    assert outcome is DispatchOutcome.SENT
    assert r.ledger.claims == [], "the sweeper already holds the lease: claiming again excludes it"
    assert len(r.commands.calls) == 1


async def test_every_attempt_sends_the_stored_bytes_and_one_request_id_per_row() -> None:
    r = rig([SagaCommandTimeoutError("s", "x"), SagaCommandTimeoutError("s", "x"), REPLY])

    await r.dispatcher.dispatch_claimed(row())

    assert len(r.commands.calls) == 3
    for _method, request, meta in r.commands.calls:
        assert request == PAYLOAD.encode("utf-8"), "the committed text, never re-serialised"
        assert meta == SagaCommandMeta(correlation_id=ORDER, request_id=ROW_ID)


@pytest.mark.parametrize(
    ("kind", "method"),
    [
        (SagaCommandKind.STOCK_RESERVE, "reserve_stock"),
        (SagaCommandKind.STOCK_RELEASE, "release_stock"),
        (SagaCommandKind.DESPATCH_CREATE, "create_despatch"),
        (SagaCommandKind.CREDIT_HOLD, "hold_credit"),
        (SagaCommandKind.INVOICE_ISSUE, "issue_invoice"),
        (SagaCommandKind.CREDIT_RELEASE, "release_credit"),
    ],
)
async def test_each_kind_is_issued_through_its_own_port_method(
    kind: SagaCommandKind, method: str
) -> None:
    r = rig([REPLY], claimable=row(kind))

    await r.dispatcher.dispatch(ORDER, kind)

    assert [call[0] for call in r.commands.calls] == [method]


async def test_an_unexpected_exception_propagates_and_neither_marks_nor_parks_the_row() -> None:
    r = rig([RuntimeError("a bug, not a transport failure")])

    with pytest.raises(RuntimeError, match="a bug"):
        await r.dispatcher.dispatch_claimed(row())

    assert r.ledger.sent == r.ledger.parked == []


async def test_cancellation_is_never_swallowed_and_leaves_the_row_leased() -> None:
    r = rig([asyncio.CancelledError()])

    with pytest.raises(asyncio.CancelledError):
        await r.dispatcher.dispatch_claimed(row())

    assert r.ledger.sent == r.ledger.parked == []
