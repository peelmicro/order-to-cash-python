# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""Feature 42: the terminal `rejected` status and EVERY ledger status predicate, against PostgreSQL.

One test per predicate (`try_claim`, `claim_due`, `mark_sent`, `park`, `reject`), so a mutation of one
predicate fails exactly the test naming it. Each negative assertion has a control row that MUST be
returned or changed, so it is never a vacuous pass on an empty table (#8 probe 3 and note 2).
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_orders.application.ports.saga_command_store import EnqueueOutcome, OwedCommand
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.infrastructure.outbox.writer import OutboxWriter
from otc_orders.infrastructure.persistence.range_guards import IntegerOutOfRangeError
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_orders.infrastructure.saga.command_ledger import SqlAlchemySagaCommandLedger
from otc_shared_kernel import UniqueId

START = datetime(2026, 10, 7, 12, 0, 0, 0, tzinfo=UTC)
LEASE_MS = 60_000
GRACE_MS = 10_000


class FakeClock:
    def __init__(self) -> None:
        self.current = START

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def ledger(
    sessions: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> SqlAlchemySagaCommandLedger:
    return SqlAlchemySagaCommandLedger(
        sessions, fake_clock, lease_ms=LEASE_MS, pending_grace_ms=GRACE_MS
    )


Owe = Callable[..., Awaitable[OwedCommand]]


@pytest.fixture
def owe(sessions: async_sessionmaker[AsyncSession], fake_clock: FakeClock) -> Owe:
    unit_of_work = SqlAlchemyUnitOfWork(
        sessions=sessions, outbox=OutboxWriter(clock=fake_clock), clock=fake_clock
    )

    async def make(
        order_id: UniqueId | None = None,
        kind: SagaCommandKind = SagaCommandKind.STOCK_RESERVE,
    ) -> OwedCommand:
        command = OwedCommand(
            order_id=order_id if order_id is not None else UniqueId.new(),
            order_reference="ORD-000001",
            kind=kind,
            payload='{"orderReference":"ORD-000001"}',
            triggering_event_id=UniqueId.new(),
        )
        async with unit_of_work.begin() as transaction:
            assert await transaction.saga_commands.enqueue(command) is EnqueueOutcome.ENQUEUED
        return command

    return make


async def rejected_row(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, db: Any, **kwargs: Any
) -> tuple[OwedCommand, uuid.UUID, dict[str, Any]]:
    """Owe, claim and reject one command; returns it, its row id and the stored `rejected` row."""
    command = await owe(**kwargs)
    claimed = await ledger.try_claim(command.order_id, command.kind)
    assert claimed is not None
    await ledger.reject(claimed.id, total_attempts=1, last_error="STOCK_UNAVAILABLE: none left")
    [row] = await db.command_rows(command.order_id)
    assert row["status"] == "rejected"
    return command, claimed.id, row


async def test_reject_resolves_a_claimed_row_to_rejected_clearing_the_lease_and_recording_the_attempts_and_the_error(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock, db: Any
) -> None:
    command = await owe()
    claimed = await ledger.try_claim(command.order_id, command.kind)
    assert claimed is not None
    fake_clock.advance(seconds=2)

    await ledger.reject(claimed.id, total_attempts=4, last_error="CONFLICT: " + "e" * 5000)

    [row] = await db.command_rows(command.order_id)
    assert row["status"] == "rejected"
    assert row["next_attempt_at"] is None, "the lease is cleared: a resolved row is never due"
    assert row["attempts"] == 4
    assert row["last_error"] == ("CONFLICT: " + "e" * 5000)[:2000]
    assert row["sent_at"] is None, "rejected is not sent"


async def test_reject_with_an_attempt_count_outside_int32_raises_the_range_guards_domain_error(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, db: Any
) -> None:
    command = await owe()
    claimed = await ledger.try_claim(command.order_id, command.kind)
    assert claimed is not None

    with pytest.raises(IntegerOutOfRangeError) as refused:
        await ledger.reject(claimed.id, total_attempts=2**31, last_error="x")

    assert "saga_commands.attempts" in str(refused.value)
    [row] = await db.command_rows(command.order_id)
    assert row["status"] == "pending", "a refused write changed nothing"


async def test_reject_never_moves_a_sent_row_and_a_rejected_row_is_not_rejected_twice(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock, db: Any
) -> None:
    sent_command = await owe()
    sent = await ledger.try_claim(sent_command.order_id, sent_command.kind)
    assert sent is not None
    await ledger.mark_sent(sent.id)
    control = await owe()  # a claimed row that MUST change: the statement does run
    claimed = await ledger.try_claim(control.order_id, control.kind)
    assert claimed is not None

    await ledger.reject(sent.id, total_attempts=7, last_error="late")
    await ledger.reject(claimed.id, total_attempts=1, last_error="first")
    fake_clock.advance(seconds=5)
    await ledger.reject(claimed.id, total_attempts=9, last_error="second")

    [still_sent] = await db.command_rows(sent_command.order_id)
    assert (still_sent["status"], still_sent["attempts"], still_sent["last_error"]) == (
        "sent",
        0,
        None,
    )
    [once] = await db.command_rows(control.order_id)
    assert (once["status"], once["attempts"], once["last_error"]) == ("rejected", 1, "first")


async def test_try_claim_never_claims_a_rejected_row_while_it_claims_a_pending_sibling(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock, db: Any
) -> None:
    command, _row_id, _row = await rejected_row(ledger, owe, db)
    sibling = await owe(order_id=command.order_id, kind=SagaCommandKind.CREDIT_HOLD)
    fake_clock.advance(milliseconds=LEASE_MS * 10 + GRACE_MS * 10)

    assert await ledger.try_claim(command.order_id, command.kind) is None, (
        "try_claim: status, not the NULL next_attempt_at, keeps a rejected row out"
    )
    control = await ledger.try_claim(sibling.order_id, sibling.kind)
    assert control is not None, "the control: the pending sibling of the same order IS claimed"


async def test_claim_due_never_returns_a_rejected_row_while_it_returns_a_due_pending_control(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock, db: Any
) -> None:
    command, row_id, _row = await rejected_row(ledger, owe, db)
    control = await owe()
    fake_clock.advance(milliseconds=LEASE_MS * 10 + GRACE_MS * 10)
    # Defence in depth: `reject` clears next_attempt_at, so a rejected row with a due one is planted
    # by hand and `created_at` is long past the grace window: only status can keep it out.
    await db.fetch(
        "UPDATE saga_commands SET next_attempt_at = $2 WHERE id = $1 RETURNING id", row_id, START
    )

    due = await ledger.claim_due(10)

    assert [row.order_id for row in due] == [control.order_id], (
        "claim_due: exactly the pending control, never the rejected row"
    )
    assert command.order_id not in {row.order_id for row in due}


async def test_mark_sent_never_moves_a_rejected_row_while_it_marks_a_claimed_control(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, db: Any
) -> None:
    command, row_id, before = await rejected_row(ledger, owe, db)
    control = await owe()
    claimed = await ledger.try_claim(control.order_id, control.kind)
    assert claimed is not None

    await ledger.mark_sent(row_id)
    await ledger.mark_sent(claimed.id)

    [after] = await db.command_rows(command.order_id)
    assert (after["status"], after["sent_at"], after["attempts"]) == (
        "rejected",
        None,
        before["attempts"],
    ), "mark_sent: a rejected row stays rejected"
    [marked] = await db.command_rows(control.order_id)
    assert marked["status"] == "sent", "the control: a claimed row IS marked sent"


async def test_park_never_re_parks_a_rejected_row_while_it_parks_a_claimed_control(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock, db: Any
) -> None:
    command, row_id, before = await rejected_row(ledger, owe, db)
    control = await owe()
    claimed = await ledger.try_claim(control.order_id, control.kind)
    assert claimed is not None
    fake_clock.advance(seconds=3)

    await ledger.park(row_id, total_attempts=9, last_error="late", retry_after_ms=1000)
    await ledger.park(claimed.id, total_attempts=3, last_error="x", retry_after_ms=1000)

    [after] = await db.command_rows(command.order_id)
    assert (after["status"], after["attempts"], after["last_error"], after["next_attempt_at"]) == (
        "rejected",
        before["attempts"],
        before["last_error"],
        None,
    ), "park: a rejected row is not re-parked"
    [parked] = await db.command_rows(control.order_id)
    assert parked["status"] == "parked", "the control: a claimed row IS parked"
