"""The outbox relay against a real PostgreSQL and a real Kafka (feature 14, 4.7-4.12).

R14, OI2, OI3, OI8, OI14, OI18. "Published" is always READ FROM THE BROKER where a broker is in
the test (never inferred from a stamped row); a record is SELECTED by its own event id, because the
topic is shared by the whole session. Loop scope: the default (function): the engine, every
session, the producer (started by `kafka_publisher`) and every consumer live and die in the
test's own loop.
"""

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from otc_orders.domain.order import Order
from otc_orders.infrastructure.outbox.publisher import FactPublicationError, PublishableFact
from otc_orders.infrastructure.outbox.relay import RelayResult
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_shared_kernel import UniqueId

INSTANT = datetime(2026, 10, 5, 12, 0, 0, 123000, tzinfo=UTC)
RELAY_LOGGER = "otc_orders.outbox.relay"


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[uuid.UUID] = []

    async def publish(self, facts: Any) -> None:
        self.published.extend(fact.event_id for fact in facts)


class FailsBeforeSending:
    async def publish(self, facts: Any) -> None:
        raise FactPublicationError([fact.event_id for fact in facts], "the broker is down")


class SendsFirstThenFailsSecond:
    def __init__(self) -> None:
        self.sent: list[uuid.UUID] = []

    async def publish(self, facts: list[PublishableFact]) -> None:
        self.sent.append(facts[0].event_id)
        raise FactPublicationError([facts[1].event_id], "the second record was not acknowledged")


class NeverCompletes:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def publish(self, facts: Any) -> None:
        self.started.set()
        await asyncio.Event().wait()


async def published_flags(dsn: str) -> dict[uuid.UUID, bool]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch("SELECT event_id, published_at IS NOT NULL AS stamped FROM outbox")
    finally:
        await conn.close()
    return {row["event_id"]: row["stamped"] for row in rows}


def walk_to_completed(order: Order) -> Order:
    """placed, then confirmed and completed: THREE facts, every transition at one shared instant."""
    order.mark_stock_reserved(occurred_at=INSTANT)
    order.approve_credit(occurred_at=INSTANT)
    order.confirm(occurred_at=INSTANT, causation_id=UniqueId.new())
    order.mark_despatched(occurred_at=INSTANT)
    order.mark_invoiced(occurred_at=INSTANT)
    order.mark_paid(occurred_at=INSTANT)
    order.complete(occurred_at=INSTANT, causation_id=UniqueId.new())
    return order


async def test_r14_stamps_a_record_only_after_the_broker_acknowledgement_and_republishes_an_unstamped_record_on_the_next_poll(  # noqa: E501
    uow: SqlAlchemyUnitOfWork,
    place_order: Any,
    make_relay: Any,
    kafka_publisher: Any,
    read_topic: Any,
    migrated_db: Any,
) -> None:
    order: Order = place_order(occurred_at=INSTANT)
    (event_id,) = [e.event_id.value for e in order.domain_events]  # type: ignore[attr-defined]
    async with uow.begin() as tx:
        await tx.orders.save(order)

    # poll 1: the publisher raises before sending anything
    first = await make_relay(FailsBeforeSending()).run_once()
    assert (first.claimed, first.published) == (1, 0)
    assert (await published_flags(migrated_db.dsn))[event_id] is False, "stamped without an ack"
    assert [r for r in await read_topic() if r.event_id == event_id] == [], "it reached the broker"

    # poll 2: the real producer; the record is republished, acknowledged, and only then stamped
    second = await make_relay(kafka_publisher).run_once()
    assert (second.claimed, second.published) == (1, 1)
    assert (await published_flags(migrated_db.dsn))[event_id] is True
    on_broker = [r for r in await read_topic() if r.event_id == event_id]
    assert len(on_broker) == 1, f"exactly one record on the broker, found {len(on_broker)}"


async def test_oi2_publishes_records_written_by_one_transaction_in_append_order_although_they_share_occurred_at(  # noqa: E501
    uow: SqlAlchemyUnitOfWork, place_order: Any, make_relay: Any
) -> None:
    for run in range(3):  # three repeated runs: one lucky ordering would not survive them
        publisher = RecordingPublisher()
        order = walk_to_completed(
            place_order(order_reference=f"ORD-0000{run + 10}", occurred_at=INSTANT)
        )
        raised = [e.event_id.value for e in order.domain_events]  # type: ignore[attr-defined]
        assert len(raised) == 3
        async with uow.begin() as tx:
            await tx.orders.save(order)
        await make_relay(publisher).run_once()
        assert publisher.published == raised, f"run {run}: published out of append order"


async def test_oi2_orders_the_claim_by_seq_never_by_occurred_at_when_they_disagree(
    row_planter: Any, make_relay: Any
) -> None:
    planted = [
        await row_planter.plant(occurred_at=INSTANT - timedelta(minutes=index))
        for index in range(8)  # occurred_at DEcreases as seq increases
    ]
    assert [p.seq for p in planted] == sorted(p.seq for p in planted)
    publisher = RecordingPublisher()
    await make_relay(publisher).run_once()
    assert publisher.published == [p.event_id for p in planted], "ordered by something but seq"


async def test_oi3_publishes_a_lower_sequence_record_that_committed_after_a_higher_one_was_published(  # noqa: E501
    row_planter: Any, make_relay: Any, migrated_db: Any
) -> None:
    publisher = RecordingPublisher()
    relay = make_relay(publisher)
    slow = await asyncpg.connect(migrated_db.dsn)
    transaction = slow.transaction()
    await transaction.start()
    try:
        lower = await row_planter.plant(connection=slow)  # seq N, not committed yet
        higher = await row_planter.plant()  # seq N+1, committed
        assert lower.seq < higher.seq
        await relay.run_once()
        assert publisher.published == [higher.event_id]
    finally:
        await transaction.commit()
        await slow.close()
    result = await relay.run_once()
    assert publisher.published == [higher.event_id, lower.event_id], "the lower seq was skipped"
    assert result.published == 1


async def test_oi8_leaves_every_record_of_a_rejected_batch_unstamped_logs_each_and_republishes_the_same_records_in_order(  # noqa: E501
    row_planter: Any,
    make_relay: Any,
    migrated_db: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = await row_planter.plant()
    second = await row_planter.plant()
    publisher = SendsFirstThenFailsSecond()
    with caplog.at_level(logging.DEBUG, logger=RELAY_LOGGER):
        result = await make_relay(publisher).run_once()
    assert (result.claimed, result.published) == (2, 0)
    assert result.poisoned is None, "a rejected batch is not a poison row"
    assert publisher.sent == [first.event_id], "the first record WAS sent: this is partial success"
    assert await published_flags(migrated_db.dsn) == {first.event_id: False, second.event_id: False}
    errors = [r for r in caplog.records if r.levelno == logging.ERROR and r.name == RELAY_LOGGER]
    assert len(errors) == 2, "one ERROR record per claimed row"
    assert [(r.eventId, r.correlationId, r.seq) for r in errors] == [  # type: ignore[attr-defined]
        (str(p.event_id), str(p.correlation_id), p.seq) for p in (first, second)
    ]
    assert all(
        "the second record was not acknowledged" in r.error  # type: ignore[attr-defined]
        for r in errors
    ), "each line carries the publication error"

    retry = RecordingPublisher()
    again = await make_relay(retry).run_once()
    assert (again.claimed, again.published) == (2, 2)
    assert retry.published == [first.event_id, second.event_id], "same records, same order"


class RecordingSyncSession(Session):
    """A sync Session subclass whose events are observed: listeners attach to THIS class only."""


class RecordingAsyncSession(AsyncSession):
    sync_session_class = RecordingSyncSession


async def test_oi14_abandons_a_publish_that_exceeds_the_timeout_rolls_the_claim_back_and_republishes_on_the_next_poll(  # noqa: E501
    engine: AsyncEngine, row_planter: Any, make_relay: Any, migrated_db: Any
) -> None:
    observed: list[str] = []
    event.listen(RecordingSyncSession, "after_commit", lambda _: observed.append("commit"))
    event.listen(RecordingSyncSession, "after_rollback", lambda _: observed.append("rollback"))
    sessions = async_sessionmaker(engine, class_=RecordingAsyncSession, expire_on_commit=False)
    planted = await row_planter.plant()
    publisher = NeverCompletes()
    relay = make_relay(publisher, publish_timeout=0.5, sessions_override=sessions)

    started = time.monotonic()
    async with asyncio.timeout(5):  # the test's own bound: it must not be what ends the cycle
        result = await relay.run_once()
    elapsed = time.monotonic() - started

    assert publisher.started.is_set()
    assert elapsed < 2.0, f"run_once took {elapsed:.2f}s with a 0.5s publish timeout"
    assert (result.claimed, result.published) == (1, 0)
    assert "commit" not in observed, f"the claim transaction committed: {observed}"
    assert "rollback" in observed
    assert await published_flags(migrated_db.dsn) == {planted.event_id: False}
    # the rolled-back claim released its lock: another relay takes the same row immediately
    healthy = RecordingPublisher()
    next_poll = await make_relay(healthy).run_once()
    assert healthy.published == [planted.event_id]
    assert next_poll.published == 1


POISON_PAYLOADS: dict[str, tuple[str | None, str, str]] = {
    "payload_not_an_object": ("[1,2,3]", "order.placed.v1", "ValidationError"),
    "event_type_outside_the_pattern": (None, "NOT A VALID TYPE", "event_type"),
    "number_json_loads_turns_into_infinity": (
        '{"total":1e400}',
        "order.placed.v1",
        "JSON compliant",
    ),
}


@pytest.mark.parametrize("kind", sorted(POISON_PAYLOADS))
async def test_oi18_a_poison_row_blocks_at_itself_after_the_clean_prefix_is_published(
    kind: str,
    row_planter: Any,
    make_relay: Any,
    migrated_db: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload, event_type, reason_names = POISON_PAYLOADS[kind]
    before = await row_planter.plant()
    poison = await row_planter.plant(
        **({"payload": payload} if payload else {}), event_type=event_type
    )
    after = await row_planter.plant()
    publisher = RecordingPublisher()
    with caplog.at_level(logging.DEBUG, logger=RELAY_LOGGER):
        result = await make_relay(publisher).run_once()  # raises nothing

    assert isinstance(result, RelayResult)
    assert (result.claimed, result.published) == (3, 1)
    assert result.poisoned is not None
    assert (result.poisoned.event_id, result.poisoned.seq) == (poison.event_id, poison.seq)
    assert result.poisoned.correlation_id == poison.correlation_id
    assert reason_names in result.poisoned.reason, result.poisoned.reason
    assert publisher.published == [before.event_id]
    assert await published_flags(migrated_db.dsn) == {
        before.event_id: True,
        poison.event_id: False,
        after.event_id: False,
    }
    errors = [r for r in caplog.records if r.levelno == logging.ERROR and r.name == RELAY_LOGGER]
    assert len(errors) == 1, "one ERROR record, naming the poison row"
    assert errors[0].eventId == str(poison.event_id)  # type: ignore[attr-defined]
    assert errors[0].seq == poison.seq  # type: ignore[attr-defined]
    assert errors[0].correlationId == str(poison.correlation_id)  # type: ignore[attr-defined]
    assert errors[0].error == result.poisoned.reason  # type: ignore[attr-defined]


async def test_oi18_a_poison_row_at_the_head_publishes_nothing_and_raises_nothing_on_every_poll(
    row_planter: Any, make_relay: Any, migrated_db: Any
) -> None:
    poison = await row_planter.plant(payload="[]")
    clean = await row_planter.plant()
    publisher = RecordingPublisher()
    relay = make_relay(publisher)
    results = [await relay.run_once() for _ in range(3)]
    for result in results:
        assert (result.claimed, result.published) == (2, 0)
        assert result.poisoned is not None
        assert (result.poisoned.event_id, result.poisoned.seq) == (poison.event_id, poison.seq)
    assert publisher.published == [], "the later clean row must never be published past the poison"
    assert await published_flags(migrated_db.dsn) == {poison.event_id: False, clean.event_id: False}
