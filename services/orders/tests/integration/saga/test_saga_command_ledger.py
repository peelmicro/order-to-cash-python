# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""The `saga_commands` ledger against PostgreSQL: enqueue, lease, claim, mark, park (SO11; 7.4, 8.2-8.5).

PostgreSQL only: no Kafka, no NATS, no lifespan. The ledger and the queue are the PRODUCTION classes
over a real database; time comes from a fake clock the test advances, so a lease or a park time is
an exact instant, not a sleep.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_orders.application.ports.saga_command_store import EnqueueOutcome, OwedCommand
from otc_orders.application.ports.saga_ignored_facts import IgnoredFactMarker
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
    """`await owe(order_id=None, kind=STOCK_RESERVE, payload=...)`: commit one owed command through
    the real unit of work (so through the real queue), stamped by the fake clock."""
    unit_of_work = SqlAlchemyUnitOfWork(
        sessions=sessions, outbox=OutboxWriter(clock=fake_clock), clock=fake_clock
    )

    async def make(
        order_id: UniqueId | None = None,
        kind: SagaCommandKind = SagaCommandKind.STOCK_RESERVE,
        payload: str = '{"orderReference":"ORD-000001"}',
    ) -> OwedCommand:
        command = OwedCommand(
            order_id=order_id if order_id is not None else UniqueId.new(),
            order_reference="ORD-000001",
            kind=kind,
            payload=payload,
            triggering_event_id=UniqueId.new(),
        )
        async with unit_of_work.begin() as transaction:
            outcome = await transaction.saga_commands.enqueue(command)
        assert outcome is EnqueueOutcome.ENQUEUED
        return command

    return make


async def test_enqueueing_a_command_already_owed_returns_already_owed_leaves_the_row_untouched_and_keeps_the_transaction_usable(
    sessions: async_sessionmaker[AsyncSession], fake_clock: FakeClock, db: Any
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(
        sessions=sessions, outbox=OutboxWriter(clock=fake_clock), clock=fake_clock
    )
    order_id = UniqueId.new()
    first = OwedCommand(
        order_id=order_id,
        order_reference="ORD-000001",
        kind=SagaCommandKind.CREDIT_HOLD,
        payload='{"first":true}',
        triggering_event_id=UniqueId.new(),
    )
    second = OwedCommand(
        order_id=order_id,
        order_reference="ORD-000001",
        kind=SagaCommandKind.CREDIT_HOLD,
        payload='{"second":true}',
        triggering_event_id=UniqueId.new(),
    )
    async with unit_of_work.begin() as transaction:
        assert await transaction.saga_commands.enqueue(first) is EnqueueOutcome.ENQUEUED
    [stored] = await db.command_rows(order_id)

    async with unit_of_work.begin() as transaction:
        assert await transaction.saga_commands.enqueue(second) is EnqueueOutcome.ALREADY_OWED
        # a PostgreSQL transaction is aborted by ANY error: this statement proves it is still usable
        await transaction.ignored_facts.record(
            event_id=UniqueId.new(),
            event_type="stock.reserved.v1",
            correlation_id=order_id,
            order_id=None,
            observed_status=None,
            expected_status=None,
            marker=IgnoredFactMarker.UNKNOWN_ORDER,
        )

    [after] = await db.command_rows(order_id)
    assert (after["id"], after["payload"], after["status"]) == (
        stored["id"],
        '{"first":true}',
        "pending",
    ), "the existing row is untouched"
    assert len(await db.ignored(order_id)) == 1, "the later statement committed"


async def test_so11_a_claimed_row_is_invisible_to_a_concurrent_claim_until_its_lease_elapses(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock
) -> None:
    command = await owe()
    fake_clock.advance(seconds=GRACE_MS // 1000 + 1)  # past the pending grace: due for the sweeper

    first = await ledger.try_claim(command.order_id, command.kind)
    second = await ledger.try_claim(command.order_id, command.kind)
    batch = await ledger.claim_due(10)

    assert first is not None
    assert first.id is not None
    assert second is None, "a leased row cannot be claimed again by the fast path"
    assert batch == [], "nor by the sweeper"
    fake_clock.advance(milliseconds=LEASE_MS - 1)
    assert await ledger.try_claim(command.order_id, command.kind) is None, "one ms before the end"


async def test_so11_a_row_whose_lease_elapsed_is_claimable_again(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock
) -> None:
    command = await owe()
    first = await ledger.try_claim(command.order_id, command.kind)
    assert first is not None

    fake_clock.advance(milliseconds=LEASE_MS)  # the lease ends AT this instant (<=)
    again = await ledger.try_claim(command.order_id, command.kind)
    assert again is not None
    assert again.id == first.id
    assert again.payload == first.payload

    fake_clock.advance(milliseconds=LEASE_MS)
    [swept] = await ledger.claim_due(10)
    assert swept.id == first.id, "the sweeper takes a crashed claimer's row after the lease"


async def test_the_claim_returns_the_stored_payload_text_and_the_rows_identity(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe
) -> None:
    command = await owe(kind=SagaCommandKind.INVOICE_ISSUE, payload='{"b":2,  "a":1}')

    claimed = await ledger.try_claim(command.order_id, command.kind)

    assert claimed is not None
    assert claimed.payload == '{"b":2,  "a":1}', "the committed text, key order and spacing intact"
    assert claimed.order_id == command.order_id
    assert type(claimed.order_id.value) is uuid.UUID
    assert claimed.kind is SagaCommandKind.INVOICE_ISSUE
    assert claimed.order_reference == "ORD-000001"
    assert claimed.attempts == 0
    assert claimed.triggering_event_id == command.triggering_event_id


async def test_a_pending_row_is_not_due_for_the_sweeper_until_the_grace_elapsed(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock
) -> None:
    await owe()

    assert await ledger.claim_due(10) == [], "inside the grace: the fast path owns it"
    fake_clock.advance(milliseconds=GRACE_MS)
    assert len(await ledger.claim_due(10)) == 1


async def test_two_concurrent_sweeper_claims_take_disjoint_batches_without_waiting(
    ledger: SqlAlchemySagaCommandLedger,
    owe: Owe,
    fake_clock: FakeClock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    for _ in range(6):
        await owe()
        fake_clock.advance(milliseconds=5)
    fake_clock.advance(seconds=GRACE_MS // 1000 + 1)

    # claimer A: its sub-select has taken the row locks of the first three rows, and its transaction
    # is PAUSED here (it neither commits nor rolls back)
    async with sessions() as holder, holder.begin():
        locked = (
            await holder.execute(
                text(
                    "SELECT id FROM saga_commands WHERE status = 'pending' "
                    "ORDER BY created_at LIMIT 3 FOR UPDATE SKIP LOCKED"
                )
            )
        ).all()
        assert len(locked) == 3
        try:
            async with asyncio.timeout(3):
                taken = await ledger.claim_due(3)
        except TimeoutError:
            pytest.fail(
                "claimer B is blocked behind claimer A's row locks (a lock wait, not a skip)"
            )
        assert len(taken) == 3, "B gets a non-empty batch"
        assert {row.id for row in taken}.isdisjoint({r[0] for r in locked}), (
            "disjoint from A's rows"
        )


async def test_leases_and_park_times_come_from_the_clock_port(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock, db: Any
) -> None:
    command = await owe()
    fake_clock.advance(seconds=3, milliseconds=7)
    claimed_at = fake_clock.now()

    claimed = await ledger.try_claim(command.order_id, command.kind)

    assert claimed is not None
    [row] = await db.command_rows(command.order_id)
    assert row["next_attempt_at"] == claimed_at + timedelta(milliseconds=LEASE_MS)

    fake_clock.advance(minutes=1, milliseconds=11)
    parked_at = fake_clock.now()
    returned = await ledger.park(
        claimed.id, total_attempts=3, last_error="x", retry_after_ms=61_234
    )

    [row] = await db.command_rows(command.order_id)
    assert row["next_attempt_at"] == parked_at + timedelta(milliseconds=61_234)
    assert returned == row["next_attempt_at"]
    assert row["status"] == "parked"


async def test_marks_are_conditional_and_attempts_accumulate(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock, db: Any
) -> None:
    command = await owe()
    claimed = await ledger.try_claim(command.order_id, command.kind)
    assert claimed is not None

    await ledger.park(claimed.id, total_attempts=3, last_error="first error", retry_after_ms=1000)
    await ledger.park(claimed.id, total_attempts=6, last_error="second error", retry_after_ms=2000)
    [row] = await db.command_rows(command.order_id)
    assert row["attempts"] == 6, "the total the caller accumulated, not the cycle count"
    assert row["last_error"] == "second error"

    fake_clock.advance(seconds=5)
    await ledger.mark_sent(claimed.id)
    [sent] = await db.command_rows(command.order_id)
    assert sent["status"] == "sent"
    assert sent["next_attempt_at"] is None
    sent_at = sent["sent_at"]
    assert sent_at == fake_clock.now()

    fake_clock.advance(seconds=5)
    await ledger.mark_sent(claimed.id)  # a sent row: nothing changes
    await ledger.park(claimed.id, total_attempts=9, last_error="late", retry_after_ms=1000)
    [still] = await db.command_rows(command.order_id)
    assert still["status"] == "sent", "a sent row is never moved back to parked"
    assert still["sent_at"] == sent_at
    assert still["attempts"] == 6
    assert still["last_error"] == "second error"


async def test_so5_a_parked_rows_backoff_is_enforced_on_both_claims_and_ends_exactly_at_next_attempt_at(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock
) -> None:
    retry_after_ms = 61_234
    command = await owe()
    claimed = await ledger.try_claim(command.order_id, command.kind)
    assert claimed is not None
    fake_clock.advance(minutes=3)  # past the lease and the pending grace: only the back-off holds
    await ledger.park(claimed.id, total_attempts=3, last_error="x", retry_after_ms=retry_after_ms)
    parked_at = fake_clock.now()

    fake_clock.advance(milliseconds=retry_after_ms - 1)
    assert fake_clock.now() == parked_at + timedelta(milliseconds=retry_after_ms - 1)
    assert await ledger.try_claim(command.order_id, command.kind) is None, (
        "try_claim: a parked row is not claimable one ms before its back-off ends"
    )
    assert await ledger.claim_due(10) == [], (
        "claim_due: a parked row is not due one ms before its back-off ends"
    )

    fake_clock.advance(milliseconds=1)
    due = await ledger.claim_due(10)
    assert [row.id for row in due] == [claimed.id], (
        "claim_due: the parked row is due exactly at next_attempt_at"
    )


async def test_so5_a_parked_rows_backoff_ends_exactly_at_next_attempt_at_for_the_fast_path_claim(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock
) -> None:
    retry_after_ms = 44_321
    command = await owe(kind=SagaCommandKind.CREDIT_HOLD)
    claimed = await ledger.try_claim(command.order_id, command.kind)
    assert claimed is not None
    await ledger.park(claimed.id, total_attempts=3, last_error="x", retry_after_ms=retry_after_ms)

    fake_clock.advance(milliseconds=retry_after_ms - 1)
    assert await ledger.try_claim(command.order_id, command.kind) is None, (
        "try_claim: a parked row is not claimable one ms before its back-off ends"
    )
    fake_clock.advance(milliseconds=1)
    again = await ledger.try_claim(command.order_id, command.kind)
    assert again is not None, "try_claim: claimable at next_attempt_at"
    assert again.id == claimed.id


async def test_so11_a_sent_row_is_a_no_op_claim_for_both_claims_even_long_after_any_lease(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, fake_clock: FakeClock, db: Any
) -> None:
    command = await owe()
    claimed = await ledger.try_claim(command.order_id, command.kind)
    assert claimed is not None
    await ledger.mark_sent(claimed.id)
    [row] = await db.command_rows(command.order_id)
    assert (row["status"], row["next_attempt_at"]) == ("sent", None)

    fake_clock.advance(milliseconds=LEASE_MS * 10 + GRACE_MS * 10)
    assert await ledger.try_claim(command.order_id, command.kind) is None, (
        "try_claim: a sent row is never claimed again"
    )
    assert await ledger.claim_due(10) == [], "claim_due: a sent row is never due"
    [after] = await db.command_rows(command.order_id)
    assert (after["status"], after["sent_at"]) == ("sent", row["sent_at"])

    # Defence in depth: mark_sent clears next_attempt_at, so a sent row with a due next_attempt_at is
    # an impossible state, planted here by hand so that each claim's own `status` predicate (and not
    # the NULL) is what keeps a sent row out.
    await db.fetch(
        "UPDATE saga_commands SET next_attempt_at = $2 WHERE id = $1 RETURNING id",
        row["id"],
        START,
    )
    assert await ledger.try_claim(command.order_id, command.kind) is None, (
        "try_claim: status, not a NULL next_attempt_at, keeps a sent row out"
    )
    assert await ledger.claim_due(10) == [], (
        "claim_due: status, not a NULL next_attempt_at, keeps a sent row out"
    )


async def test_park_with_an_attempt_count_outside_int32_raises_the_range_guards_domain_error(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe
) -> None:
    command = await owe()
    claimed = await ledger.try_claim(command.order_id, command.kind)
    assert claimed is not None

    with pytest.raises(IntegerOutOfRangeError) as refused:
        await ledger.park(claimed.id, total_attempts=2**31, last_error="x", retry_after_ms=1000)

    assert refused.value.CODE == "storage.integer_out_of_range"
    assert "saga_commands.attempts" in str(refused.value)


async def test_a_long_last_error_is_truncated_to_2000_characters(
    ledger: SqlAlchemySagaCommandLedger, owe: Owe, db: Any
) -> None:
    command = await owe()
    claimed = await ledger.try_claim(command.order_id, command.kind)
    assert claimed is not None

    await ledger.park(claimed.id, total_attempts=3, last_error="e" * 5000, retry_after_ms=1000)

    [row] = await db.command_rows(command.order_id)
    assert row["last_error"] == "e" * 2000
