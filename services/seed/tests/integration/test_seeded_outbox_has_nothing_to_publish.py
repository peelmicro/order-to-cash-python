"""A relay over the SEEDED `otc_orders` finds nothing to publish (feature 14, 4.20; #8's seed test).

The seed writes every outbox row already published (`published_at` set), so a relay that starts on a
freshly seeded database must claim nothing and publish nothing. The instrument is the PRODUCTION
`OutboxRelay` over the seed suite's own database, with a recording fake publisher; the sentinel
inserts one UNPUBLISHED row and requires the very same assertions to fail (claimed 1, publisher
called), so "claimed == 0" cannot be a vacuous pass. (Test code may import `otc_orders`: the
service-independence contract covers `src` only.) Loop scope: `function`, as the suite's fixtures.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from otc_orders.infrastructure.clock import SystemClock
from otc_orders.infrastructure.outbox.relay import OutboxRelay, RelayResult
from otc_seed.application import run_seed
from otc_seed.composition import SeedRuntime

pytestmark = pytest.mark.integration

GOLDEN_PLACED_PAYLOAD = json.dumps(
    {"orderReference": "ORD-000099", "currency": "EUR", "totalAmount": 1},
    separators=(",", ":"),
)


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls = 0
        self.published: list[uuid.UUID] = []

    async def publish(self, facts: Any) -> None:
        self.calls += 1
        self.published.extend(fact.event_id for fact in facts)


async def relay_once(url: str, publisher: RecordingPublisher) -> RelayResult:
    engine = create_async_engine(url)
    try:
        relay = OutboxRelay(
            sessions=async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
            publisher=publisher,
            clock=SystemClock(),
            batch_size=100,
            publish_timeout=5.0,
        )
        return await relay.run_once()
    finally:
        await engine.dispose()


async def outbox_counts(dsn: str) -> tuple[int, int]:
    conn = await asyncpg.connect(dsn)
    try:
        total = await conn.fetchval("SELECT count(*) FROM outbox")
        unpublished = await conn.fetchval("SELECT count(*) FROM outbox WHERE published_at IS NULL")
    finally:
        await conn.close()
    return int(total), int(unpublished)


async def test_a_relay_over_the_seeded_orders_database_claims_nothing_and_publishes_nothing(
    runtime: SeedRuntime, stack: Any
) -> None:
    await run_seed(runtime.targets)
    total, unpublished = await outbox_counts(stack.orders.dsn)
    assert total == 17, "the premise: the seed wrote its 17 orders outbox rows"
    assert unpublished == 0, "the premise: every seeded row is already published"

    publisher = RecordingPublisher()
    result = await relay_once(stack.orders.url, publisher)

    assert result.claimed == 0, f"the relay claimed {result.claimed} seeded rows"
    assert result.published == 0
    assert publisher.calls == 0, "the publisher must never be called for a seeded database"


async def test_the_sentinel_one_unpublished_row_in_the_seeded_database_is_claimed_and_published(
    runtime: SeedRuntime, stack: Any
) -> None:
    """Sentinel: the assertions of the test above FAIL for a database with one row to publish."""
    await run_seed(runtime.targets)
    sentinel = uuid.uuid4()
    conn = await asyncpg.connect(stack.orders.dsn)
    try:
        await conn.execute(
            "INSERT INTO outbox (id, event_id, event_type, aggregate_id, correlation_id, "
            "causation_id, payload, occurred_at, published_at, created_at, trace_parent) "
            "VALUES ($1, $2, 'order.placed.v1', $3, $3, $4, $5::json, $6, NULL, $6, NULL)",
            uuid.uuid4(),
            sentinel,
            uuid.uuid4(),
            uuid.uuid4(),
            GOLDEN_PLACED_PAYLOAD,
            datetime(2026, 10, 6, 9, 0, 0, tzinfo=UTC),
        )
    finally:
        await conn.close()

    publisher = RecordingPublisher()
    result = await relay_once(stack.orders.url, publisher)

    assert result.claimed == 1
    assert publisher.published == [sentinel]
    assert publisher.calls == 1
