"""Two production relays against one PostgreSQL (feature 14, 4.15-4.18): OI4, OI5, OI13.

BOTH relays are always the production `OutboxRelay` (never a re-implementation of its claim: #8's
first OI13 draft did that and guarded nothing). The publishers are fakes: these tests are about the
claim, so no broker is involved. Loop scope: default (function); every engine is created and
disposed inside the test's own loop.
"""

import asyncio
import time
import uuid
from typing import Any, cast

import asyncpg
import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

from otc_orders.infrastructure.outbox.publisher import PublishableFact
from otc_orders.infrastructure.outbox.writer import OutboxWriter
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork


class RecordingPublisher:
    def __init__(self, *, pause: float = 0.0) -> None:
        self.published: list[uuid.UUID] = []
        self._pause = pause

    async def publish(self, facts: Any) -> None:
        if self._pause:
            await asyncio.sleep(self._pause)  # keep the two relays' claims overlapping in time
        self.published.extend(fact.event_id for fact in facts)


class BlockingPublisher:
    """Records the claim it was handed, signals, then blocks until released."""

    def __init__(self) -> None:
        self.claimed: list[uuid.UUID] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def publish(self, facts: list[PublishableFact]) -> None:
        self.claimed.extend(fact.event_id for fact in facts)
        self.started.set()
        await self.release.wait()


async def drain(relay: Any) -> None:
    while True:
        if (await relay.run_once()).claimed == 0:
            return


async def test_oi4_two_concurrent_relays_take_disjoint_batches_and_publish_every_record_exactly_once(  # noqa: E501
    engine: AsyncEngine, row_planter: Any, make_relay: Any, migrated_db: Any
) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        planted = [await row_planter.plant(connection=conn) for _ in range(200)]
    finally:
        await conn.close()
    second_engine = create_async_engine(migrated_db.url)
    try:
        first, second = RecordingPublisher(pause=0.005), RecordingPublisher(pause=0.005)
        relay_one = make_relay(first, batch_size=30)
        relay_two = make_relay(
            second,
            batch_size=30,
            sessions_override=async_sessionmaker(second_engine, expire_on_commit=False),
        )
        await asyncio.gather(drain(relay_one), drain(relay_two))
    finally:
        await second_engine.dispose()

    assert set(first.published) | set(second.published) == {p.event_id for p in planted}
    assert set(first.published) & set(second.published) == set(), "a record went to both relays"
    assert len(first.published) + len(second.published) == 200, "published more than once"
    assert first.published, "both relays took part (else nothing was tested)"
    assert second.published, "both relays took part (else nothing was tested)"


async def test_oi5_records_claimed_by_a_relay_whose_connection_died_are_claimed_on_the_next_poll_without_a_wait(  # noqa: E501
    row_planter: Any, make_relay: Any, migrated_db: Any
) -> None:
    planted = [await row_planter.plant() for _ in range(3)]
    engine_a = create_async_engine(
        migrated_db.url, connect_args={"server_settings": {"application_name": "relay-a"}}
    )
    blocked = BlockingPublisher()
    relay_a = make_relay(
        blocked,
        batch_size=3,
        sessions_override=async_sessionmaker(engine_a, expire_on_commit=False),
    )
    task_a = asyncio.create_task(relay_a.run_once())
    try:
        await asyncio.wait_for(blocked.started.wait(), timeout=10)
        assert set(blocked.claimed) == {p.event_id for p in planted}, "A claimed all three"

        admin = await asyncpg.connect(migrated_db.dsn)
        try:
            killed = await admin.fetchval(
                "SELECT count(*) FROM (SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE application_name = 'relay-a') AS terminated"
            )
        finally:
            await admin.close()
        assert killed >= 1, "relay A's backend was found and terminated"

        survivor = RecordingPublisher()
        result = await make_relay(survivor).run_once()  # no sleep, no lease wait
        assert result.claimed == 3, "the dead relay's claim must be claimable again at once"
        assert set(survivor.published) == {p.event_id for p in planted}
    finally:
        blocked.release.set()
        outcome = (await asyncio.gather(task_a, return_exceptions=True))[0]
        await engine_a.dispose()
    assert isinstance(outcome, Exception), "relay A could not have stamped over a dead connection"


async def test_oi13_a_claim_skips_rows_another_relay_holds_and_returns_without_waiting(
    engine: AsyncEngine, row_planter: Any, make_relay: Any, migrated_db: Any
) -> None:
    for _ in range(20):
        await row_planter.plant()
    held = BlockingPublisher()
    relay_a = make_relay(held, batch_size=5)
    task_a = asyncio.create_task(relay_a.run_once())
    second_engine = create_async_engine(migrated_db.url)
    try:
        await asyncio.wait_for(held.started.wait(), timeout=10)
        taken = RecordingPublisher()
        relay_b = make_relay(
            taken,
            batch_size=5,
            sessions_override=async_sessionmaker(second_engine, expire_on_commit=False),
        )
        started = time.monotonic()
        try:
            async with asyncio.timeout(3):
                result = await relay_b.run_once()
        except TimeoutError:
            pytest.fail(
                "relay B BLOCKED on rows relay A holds: the claim does not skip locked rows"
            )
        elapsed = time.monotonic() - started
        print(f"OI13 measured: relay B returned in {elapsed:.3f}s while relay A held its claim")
        assert result.claimed == 5
        assert taken.published, "B's batch is non-empty"
        assert set(taken.published).isdisjoint(held.claimed), (
            f"B DUPLICATED A's rows: {set(taken.published) & set(held.claimed)}"
        )
    finally:
        held.release.set()
        await asyncio.gather(task_a)
        await second_engine.dispose()


class IsolationRecordingSyncSession(Session):
    """Records the isolation level of every transaction this session class begins."""


class IsolationRecordingSession(AsyncSession):
    sync_session_class = IsolationRecordingSyncSession


def record_isolation_of(session_class: type[Session]) -> list[str]:
    seen: list[str] = []

    def after_begin(
        session: Session, transaction: SessionTransaction, connection: Connection
    ) -> None:
        # on the TRANSACTION's own connection, after the isolation level was applied to it
        seen.append(str(connection.exec_driver_sql("SHOW transaction_isolation").scalar()))

    event.listen(session_class, "after_begin", after_begin)
    return seen


async def test_oi13_the_claim_runs_at_read_committed_under_an_engine_defaulting_to_repeatable_read(
    row_planter: Any, make_relay: Any, migrated_db: Any
) -> None:
    await row_planter.plant()
    seen = record_isolation_of(IsolationRecordingSyncSession)
    repeatable = create_async_engine(migrated_db.url, isolation_level="REPEATABLE READ")
    try:
        sessions = async_sessionmaker(
            repeatable, class_=IsolationRecordingSession, expire_on_commit=False
        )
        publisher = RecordingPublisher()
        await make_relay(publisher, sessions_override=sessions).run_once()
    finally:
        await repeatable.dispose()
    assert publisher.published, "the cycle ran"
    assert seen == ["read committed"], f"the relay's transaction ran at {seen}"


async def test_the_unit_of_work_runs_at_read_committed_under_an_engine_defaulting_to_repeatable_read(  # noqa: E501
    migrated_db: Any, clock: Any
) -> None:
    seen = record_isolation_of(IsolationRecordingSyncSession)
    repeatable = create_async_engine(migrated_db.url, isolation_level="REPEATABLE READ")
    try:
        sessions = cast(
            "async_sessionmaker[AsyncSession]",
            async_sessionmaker(
                repeatable, class_=IsolationRecordingSession, expire_on_commit=False
            ),
        )
        unit_of_work = SqlAlchemyUnitOfWork(sessions=sessions, outbox=OutboxWriter(clock=clock))
        async with unit_of_work.begin() as tx:
            await tx.session.execute(select(1))  # a real use issues a statement
    finally:
        await repeatable.dispose()
    assert seen == ["read committed"], f"the unit of work's transaction ran at {seen}"
