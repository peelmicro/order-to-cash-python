"""Acceptance 4b - counter seeding, #8 id 45 (unit: concurrent first callers).

N = 16 callers, each on its own connection, released together by a barrier, run the seed against a
never-seeded `order_number_sequences`, then lock-and-advance. All must succeed and receive N
distinct contiguous numbers. A sentinel runs #8's check-then-insert shape through the same harness
and must LOSE the race, so a harness that cannot see the race cannot pass this file.

Backlog 211 (counters start above the seeded references) and #8 id 47 (the MAX scan must not run
on the steady-state path) are proved below: `test_a_seeded_database_allocates_the_next_number`,
`test_a_reference_above_six_digits_starts_the_counter_numerically` and
`test_the_max_scan_never_runs_when_the_counter_row_exists` (with its sentinel).
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest

from otc_orders.infrastructure.persistence.sequences import (
    ADVANCE_ORDER_SEQUENCE,
    LOCK_ORDER_SEQUENCE,
    SEED_ORDER_SEQUENCE,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 5, 12, 0, 0, 123000, tzinfo=UTC)

CALLERS = 16

# #8 id 45's shape rendered for PostgreSQL: an unlocked existence check, then an insert (two
# statements). Under READ COMMITTED two callers can both see "not exists". The check-to-insert
# window is WIDENED inside the statement (`pg_sleep(0.5)`): a caller that passed
# the check holds the window open for half a second, so every caller the harness really released
# together has also passed the check before the first insert lands. That makes the loss
# deterministic in ONE round (a change of kind, not of probability: ten rounds of an unwidened
# window gave a chance, this gives a mechanism), and it is why a harness that SERIALISED the
# callers fails the sentinel: the first caller would commit its row before the second one checks,
# and nobody would lose.
RACY_SEED = (
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM order_number_sequences WHERE id = 1) THEN "
    "PERFORM pg_sleep(0.5); "
    "INSERT INTO order_number_sequences (id, next_value) VALUES (1, 1); END IF; END $$"
)


async def _first_callers(dsn: str, seed_sql: str) -> list[int | BaseException]:
    connections = [await asyncpg.connect(dsn) for _ in range(CALLERS)]
    barrier = asyncio.Barrier(CALLERS)

    async def caller(conn: asyncpg.Connection) -> int:
        await barrier.wait()
        async with conn.transaction():
            await conn.execute(seed_sql)
            number = await conn.fetchval(LOCK_ORDER_SEQUENCE)
            await conn.execute(ADVANCE_ORDER_SEQUENCE)
        return int(number)

    try:
        return await asyncio.gather(*(caller(c) for c in connections), return_exceptions=True)
    finally:
        for conn in connections:
            await conn.close()


async def test_sixteen_concurrent_first_callers_get_distinct_contiguous_numbers(
    migrated_db: Any,
) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM order_number_sequences") == 0
    finally:
        await conn.close()

    results = await _first_callers(migrated_db.dsn, SEED_ORDER_SEQUENCE)

    errors = [r for r in results if isinstance(r, BaseException)]
    assert errors == []
    assert sorted(r for r in results if isinstance(r, int)) == list(range(1, CALLERS + 1))
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        assert await conn.fetchval(
            "SELECT next_value FROM order_number_sequences WHERE id = 1"
        ) == (CALLERS + 1)
    finally:
        await conn.close()


async def test_sentinel_check_then_insert_seed_loses_the_race(migrated_db: Any) -> None:
    # ONE round, deterministic by construction (see RACY_SEED): of CALLERS callers released
    # together, exactly one insert wins and every other one loses to the unique key.
    results = await _first_callers(migrated_db.dsn, RACY_SEED)
    lost = [r for r in results if isinstance(r, asyncpg.UniqueViolationError)]
    assert len(lost) == CALLERS - 1, (
        f"the racy seed lost {len(lost)} of {CALLERS} callers, expected {CALLERS - 1}: the harness "
        "did not release the callers together, so it cannot prove the ON CONFLICT seed"
    )


async def _insert_reference(conn: asyncpg.Connection, reference: str, parents: Any) -> None:
    await conn.execute(
        "INSERT INTO orders (id, order_reference, order_date, company_id, retailer_id, "
        "currency_id, initial_amount, initial_discount, total_amount, status, created_at, "
        "updated_at) VALUES ($1, $2, $3, $4, $5, $6, 0, 0, 0, 'Completed', $3, $3)",
        uuid.uuid4(),
        reference,
        NOW,
        parents.company,
        parents.retailer,
        parents.currency,
    )


async def _allocate(conn: asyncpg.Connection) -> int:
    async with conn.transaction():
        await conn.execute(SEED_ORDER_SEQUENCE)
        number = await conn.fetchval(LOCK_ORDER_SEQUENCE)
        await conn.execute(ADVANCE_ORDER_SEQUENCE)
    return int(number)


async def test_a_seeded_database_allocates_the_next_number(migrated_db: Any, parents: Any) -> None:
    # ORD-000006 is the highest reference, so the first allocation must be 7, the next
    # 8 (an unseeded counter would hand out 1 and collide with ORD-000001 on the unique column).
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        for n in range(1, 7):
            ref = f"ORD-{n:06d}"
            await _insert_reference(conn, ref, parents)
        assert [await _allocate(conn), await _allocate(conn)] == [7, 8]
    finally:
        await conn.close()


async def test_a_reference_above_six_digits_starts_the_counter_numerically(
    migrated_db: Any, parents: Any
) -> None:
    # A text MAX ranks '999999' above '1000000' and would start the counter at 1000000, which
    # collides with ORD-1000000.
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        for ref in ("ORD-999999", "ORD-1000000"):
            await _insert_reference(conn, ref, parents)
        assert await _allocate(conn) == 1000001
    finally:
        await conn.close()


# The shape #8 id 47 had to retire: an aggregate over the table with nothing to skip it, so the
# scan runs on every call and the counter row only decides whether the insert conflicts. (Measured
# on postgres:18.6: `SELECT MAX(...) FROM t WHERE NOT EXISTS (...)` ALSO skips the scan, through a
# one-time filter, but still emits a row and attempts a conflicting insert; the select-list
# subquery shape of the real statement emits nothing, so it is the one used.)
SCANS_EVERY_TIME = (
    "INSERT INTO order_number_sequences (id, next_value) "
    "SELECT 1, COALESCE(MAX(CAST(substring(order_reference FROM 5) AS bigint)), 0) + 1 "
    "FROM orders "
    "ON CONFLICT (id) DO NOTHING"
)


async def _scan_lines(conn: asyncpg.Connection, seed_sql: str) -> list[str]:
    """The plan lines naming the table the MAX reads, from `EXPLAIN (ANALYZE)` of a real run."""
    rows = await conn.fetch("EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF) " + seed_sql)
    lines = [
        str(r[0]) for r in rows if " on orders " in str(r[0]) or str(r[0]).endswith(" on orders")
    ]
    assert lines, "no scan of orders in the plan: the probe cannot tell scanned from skipped"
    return lines


async def _scan_runs(conn: asyncpg.Connection, seed_sql: str) -> bool:
    return not all("never executed" in line for line in await _scan_lines(conn, seed_sql))


async def test_the_max_scan_never_runs_when_the_counter_row_exists(
    migrated_db: Any, parents: Any
) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        for n in range(1, 7):
            ref = f"ORD-{n:06d}"
            await _insert_reference(conn, ref, parents)
        # sentinel: the aggregate shape scans every time, even with the counter row present
        await conn.execute("INSERT INTO order_number_sequences VALUES (1, 99)")
        assert await _scan_runs(conn, SCANS_EVERY_TIME), "the sentinel shape did not scan"
        # the real statement, counter row present: the scan is never executed
        assert not await _scan_runs(conn, SEED_ORDER_SEQUENCE), "the steady-state path scans orders"
        # and the same statement does scan when it has to seed (the probe can see a scan)
        await conn.execute("DELETE FROM order_number_sequences")
        assert await _scan_runs(conn, SEED_ORDER_SEQUENCE), "the seeding path did not scan"
    finally:
        await conn.close()
