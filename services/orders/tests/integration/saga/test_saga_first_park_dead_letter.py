# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""`R29`'s dead-letter clause and `OR3` (S4.12, S4.14): the FIRST park of a saga command.

The first park appends ONE `order.saga_failed.v1` (outbox, same transaction as the claim) and dead-
letters the triggering envelope's bytes ONCE; every later park of the same row emits neither. The
dead letters are read from the BROKER, by content, after a decoy published first on the same topic;
every topic is private to the test (item 10).
"""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.saga.command_queue import SqlAlchemySagaCommandQueue
from otc_orders.infrastructure.saga.first_park import SqlAlchemySagaFirstPark

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]

NOW = datetime(2026, 10, 12, 9, 0, 0, 0, tzinfo=UTC)
FAST = {"FACT_RETRY_BACKOFF_MS": "20", "OUTBOX_RELAY_ENABLED": "false"}


class FixedClock:
    def now(self) -> datetime:
        return NOW


class Refusing:
    """A dead-letter producer whose broker never acknowledges."""

    def __init__(self, refused: list[str], **options: Any) -> None:
        self._refused = refused

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_and_wait(self, topic: str, **record: Any) -> None:
        self._refused.append(topic)
        raise ConnectionError("the dead-letter broker did not acknowledge")


def refusing(refused: list[str]) -> Callable[..., Refusing]:
    def factory(**options: Any) -> Refusing:
        return Refusing(refused, **options)

    return factory


def awkward_bytes(
    make_fact_bytes: Callable[..., bytes], order: Order, event_id: uuid.UUID
) -> bytes:
    """The wire bytes of an `order.placed.v1` that no serializer would write: keys reversed, spaces
    in the separators, a top-level field the model does not declare, non-ASCII text."""
    canonical = json.loads(
        make_fact_bytes(
            "order.placed.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
            event_id=event_id,
        )
    )
    canonical["zzUndeclared"] = {"keep": "ñandú 日本"}
    return json.dumps(
        dict(reversed(list(canonical.items()))), separators=(", ", ": "), ensure_ascii=False
    ).encode("utf-8")


def _parse_instant(raw: bytes) -> datetime:
    return datetime.strptime(raw.decode(), "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


async def test_or3_concurrent_claims_of_one_row_have_exactly_one_winner(
    migrated_db: Any, db: Any
) -> None:
    """16 transactions, each on its own connection, are all OPEN before any claims; then all claim
    the same parked row at once. One statement decides: exactly one gets the row back."""
    row_id = uuid.uuid4()
    await db.fetch(
        "INSERT INTO saga_commands (id, order_id, order_reference, command, payload, "
        "triggering_event_id, status, attempts, next_attempt_at, created_at, updated_at, "
        "triggering_event_envelope, triggering_event_topic) "
        "VALUES ($1, $2, 'ORD-000900', 'stock.reserve', '{}', $3, 'parked', 3, now(), now(), now(), $4, $5)",
        row_id,
        uuid.uuid4(),
        uuid.uuid4(),
        b'{"stored":"bytes"}',
        "otc.orders.facts.v1",
    )
    contenders = 16
    engine = create_async_engine(migrated_db.url, pool_size=contenders + 2)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    gate = asyncio.Barrier(contenders)

    async def contend() -> bytes | None:
        async with sessions() as session, session.begin():
            await session.execute(
                text("SELECT 1")
            )  # the transaction is open and holds a connection
            await gate.wait()
            claim = await SqlAlchemySagaCommandQueue(session, FixedClock()).claim_first_park(
                row_id, at=NOW
            )
            return None if claim is None else claim.envelope

    try:
        answers = await asyncio.gather(*(contend() for _ in range(contenders)))
    finally:
        await engine.dispose()

    winners = [answer for answer in answers if answer is not None]
    assert len(winners) == 1, f"{len(winners)} of {contenders} claims returned the row"
    assert winners == [b'{"stored":"bytes"}']
    [stored] = await db.fetch("SELECT dead_lettered_at FROM saga_commands WHERE id = $1", row_id)
    assert stored["dead_lettered_at"] == NOW


async def test_or3_claim_first_park_answers_none_and_leaves_the_marker_null_for_a_row_that_is_not_parked(
    migrated_db: Any, db: Any
) -> None:
    """The `status = 'parked'` predicate of the claim, alone: a `rejected` row and a `sent` row each
    carry an envelope and no marker, so only the status keeps them from being claimed. A claim
    without the predicate returns the envelope and stamps `dead_lettered_at`."""
    engine = create_async_engine(migrated_db.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ids = {"rejected": uuid.uuid4(), "sent": uuid.uuid4()}
    try:
        for status, row_id in ids.items():
            await db.fetch(
                "INSERT INTO saga_commands (id, order_id, order_reference, command, payload, "
                "triggering_event_id, status, attempts, created_at, updated_at, "
                "triggering_event_envelope, triggering_event_topic, first_failed_at) "
                "VALUES ($1, $2, 'ORD-000901', 'stock.reserve', '{}', $3, $4, 1, now(), now(), $5, $6, now())",
                row_id,
                uuid.uuid4(),
                uuid.uuid4(),
                status,
                b'{"stored":"bytes"}',
                "otc.orders.facts.v1",
            )
        for status, row_id in ids.items():
            async with sessions() as session, session.begin():
                claim = await SqlAlchemySagaCommandQueue(session, FixedClock()).claim_first_park(
                    row_id, at=NOW
                )
            assert claim is None, f"a {status} row is not parked: nothing to claim"
            [stored] = await db.fetch(
                "SELECT dead_lettered_at FROM saga_commands WHERE id = $1", row_id
            )
            assert stored["dead_lettered_at"] is None, f"a {status} row is never marked"
    finally:
        await engine.dispose()


async def test_r29_the_first_park_appends_one_order_saga_failed_and_dead_letters_the_triggering_envelope_once_and_a_second_park_emits_neither(
    saga_harness: Any,
    private_topics: Any,
    dl_support: ModuleType,
    kafka_server: Any,
    order_at: OrderAt,
    make_fact_bytes: Callable[..., bytes],
    waits: Waits,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The hook runs AFTER the park is committed, so "the row is parked again" is not evidence that
    # the second park's hook has finished. This wrapper runs the production hook unchanged and
    # counts its completions, so "emits neither" is asserted after the second hook returned.
    completions: list[uuid.UUID] = []
    original = SqlAlchemySagaFirstPark.on_parked

    async def counted(self: SqlAlchemySagaFirstPark, row: Any, **kwargs: Any) -> None:
        await original(self, row, **kwargs)
        completions.append(row.id)

    monkeypatch.setattr(SqlAlchemySagaFirstPark, "on_parked", counted)
    order = await order_at(OrderStatus.PLACED)
    event_id, decoy_id = uuid.uuid4(), uuid.uuid4()
    produced = awkward_bytes(make_fact_bytes, order, event_id)
    source = private_topics.orders
    letters = private_topics.dead_letter_of(source)
    servers = kafka_server.bootstrap_servers
    # A decoy dead letter first, on the very topic the test reads: selection is by content.
    decoy = make_fact_bytes(
        "order.placed.v1",
        correlation_id=uuid.uuid4(),
        reference="ORD-000999",
        event_id=decoy_id,
    )
    await dl_support.produce(servers, letters, key=b"decoy", value=decoy)

    async with saga_harness(topics=private_topics, **FAST) as saga:
        stand_in = saga.stand_in(SagaCommandKind.STOCK_RESERVE)
        # The test's own observation of the first attempt: the instant each request ARRIVED. The
        # responder never answers, so each attempt fails only after its timeout: attempt 1 fails
        # between arrival 1 and arrival 2 (which waits for the back-off after that failure).
        arrivals: list[datetime] = []

        def silent_noting_the_arrival(recorded: Any) -> None:
            arrivals.append(datetime.now(UTC))
            return saga.behaviours["silent"](recorded)  # type: ignore[no-any-return]

        stand_in.behaviour = silent_noting_the_arrival
        await dl_support.produce(servers, source, key=str(order.id.value).encode(), value=produced)

        async def first_park_done() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            return row is not None and row["dead_lettered_at"] is not None

        await waits(first_park_done, "the stock.reserve row is parked and its first park claimed")

        async def own_letters() -> list[Any]:
            return [
                record
                for record in await dl_support.read_records(servers, letters)
                if record.event_id == str(event_id)
            ]

        async def one_letter() -> bool:
            return len(await own_letters()) == 1

        await waits(one_letter, "the dead letter of the triggering envelope is on the .dlq")
        [letter] = await own_letters()
        first = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
        assert first is not None
        assert letter.value == produced, "the ORIGINAL bytes, not a re-serialisation"
        assert letter.key == str(order.id.value).encode()
        assert letter.headers["x-failed-consumer"] == b"orders.saga"
        assert letter.headers["x-original-topic"] == source.encode()
        assert letter.headers["x-event-type"] == b"order.placed.v1"
        assert letter.headers["content-type"] == b"application/json"
        outbox = await saga.db.fetch(
            "SELECT event_type, payload::text AS payload, correlation_id, causation_id "
            "FROM outbox WHERE aggregate_id = $1 ORDER BY seq",
            order.id.value,
        )
        assert [row["event_type"] for row in outbox] == ["order.saga_failed.v1"]
        fact = json.loads(outbox[0]["payload"])
        assert fact["command"] == "stock.reserve"
        assert fact["orderReference"] == order.order_reference.value
        assert fact["attempts"] == first["attempts"] == 3
        assert fact["lastError"] == first["last_error"]
        assert outbox[0]["correlation_id"] == order.id.value
        assert outbox[0]["causation_id"] == first["triggering_event_id"]
        assert letter.headers["x-attempts"] == str(fact["attempts"]).encode()
        assert letter.headers["x-error"] == fact["lastError"].encode()
        assert letter.headers["x-failed-at"] == fact["failedAt"].encode()
        # SA-3: with `x-attempts` 3 the two instants are NOT equal. The first is the instant the
        # first attempt failed, bracketed by what the test itself observed: after the first request
        # arrived and before the second one did (the second waits for the back-off after it).
        first_failed_at = _parse_instant(letter.headers["x-first-failed-at"])
        failed_at = _parse_instant(letter.headers["x-failed-at"])
        assert len(arrivals) >= 3, "three in-line attempts reached the responder"
        assert (
            arrivals[0].replace(microsecond=arrivals[0].microsecond // 1000 * 1000)
            <= first_failed_at
            < arrivals[1]
        ), (
            f"SA-3: x-first-failed-at is the first attempt's failure; observed arrivals {arrivals[:2]}"
        )
        assert first_failed_at < failed_at, (
            "SA-3: x-first-failed-at equals x-failed-at only when a single attempt was made, "
            f"and x-attempts is {letter.headers['x-attempts']!r}"
        )
        assert first["first_failed_at"] == first_failed_at, "the header is the stored instant"
        claimed_at = first["dead_lettered_at"]

        # A SECOND park of the same row: the sweeper reattempts the parked row (the responder is
        # still silent) and the accumulated attempts reach 6.
        async def second_hook_finished() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            return (
                row is not None
                and row["attempts"] >= 6
                and len([r for r in completions if r == row["id"]]) >= 2
            )

        await waits(
            second_hook_finished,
            "the sweeper re-parked the row (attempts 6) and the second park's hook returned",
        )
        again = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
        assert again is not None
        assert again["dead_lettered_at"] == claimed_at, "the claim is made once and never rewritten"
        assert again["next_attempt_at"] is not None, "SO5: the second park still schedules a retry"
        assert [
            r["event_type"]
            for r in await saga.db.fetch(
                "SELECT event_type FROM outbox WHERE aggregate_id = $1", order.id.value
            )
        ] == ["order.saga_failed.v1"], "the second park appended no second fact"
        assert len(await own_letters()) == 1, "and published no second dead letter"


async def test_r29_a_dead_letter_that_cannot_be_published_leaves_the_fact_and_the_claim_committed_and_the_envelope_in_the_row(
    saga_harness: Any,
    private_topics: Any,
    kafka_server: Any,
    dl_support: ModuleType,
    order_at: OrderAt,
    make_fact_bytes: Callable[..., bytes],
    waits: Waits,
) -> None:
    """G4: the outbox row commits WITH the claim, and the publication follows the commit. A
    publication that fails is only logged; the bytes stay in the row for a manual republish."""
    order = await order_at(OrderStatus.PLACED)
    produced = awkward_bytes(make_fact_bytes, order, uuid.uuid4())
    refused: list[str] = []
    async with saga_harness(
        topics=private_topics,
        dead_letter_producer_factory=refusing(refused),
        SAGA_SWEEPER_ENABLED="false",
        **FAST,
    ) as saga:
        saga.stand_in(SagaCommandKind.STOCK_RESERVE).behaviour = saga.behaviours["silent"]
        await dl_support.produce(
            kafka_server.bootstrap_servers,
            private_topics.orders,
            key=str(order.id.value).encode(),
            value=produced,
        )

        async def refused_once() -> bool:
            return any(topic == f"{private_topics.orders}.dlq" for topic in refused)

        await waits(refused_once, "the dead-letter publication was attempted and refused")

        async def claimed() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            return row is not None and row["dead_lettered_at"] is not None

        await waits(claimed, "the claim is committed although the publication failed")
        row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
        assert row is not None
        assert bytes(row["triggering_event_envelope"]) == produced, "the bytes stay in the row"
        assert [
            r["event_type"]
            for r in await saga.db.fetch(
                "SELECT event_type FROM outbox WHERE aggregate_id = $1", order.id.value
            )
        ] == ["order.saga_failed.v1"], "the fact is durable although the publication failed"
