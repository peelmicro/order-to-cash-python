"""Acceptance 4 (counter test) - counter seeding, #8 id 45 (unit: concurrent first callers).

N = 16 callers, each on its own connection, released together by a barrier, run the seed against a
never-seeded `invoice_number_sequences`, then lock-and-advance. All must succeed and receive N
distinct contiguous numbers. A sentinel runs #8's check-then-insert shape through the same harness
and must LOSE the race, so a harness that cannot see the race cannot pass this file.
"""

import asyncio
from typing import Any

import asyncpg
import pytest

from otc_billing.infrastructure.persistence.sequences import (
    ADVANCE_INVOICE_SEQUENCE,
    LOCK_INVOICE_SEQUENCE,
    SEED_INVOICE_SEQUENCE,
)

pytestmark = pytest.mark.integration

CALLERS = 16

# #8 id 45's shape rendered for PostgreSQL: an unlocked existence check, then an insert (two
# statements). Under READ COMMITTED two callers can both see "not exists".
RACY_SEED = (
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM invoice_number_sequences WHERE id = 1) THEN "
    "INSERT INTO invoice_number_sequences (id, next_value) VALUES (1, 1); END IF; END $$"
)


async def _first_callers(dsn: str, seed_sql: str) -> list[int | BaseException]:
    connections = [await asyncpg.connect(dsn) for _ in range(CALLERS)]
    barrier = asyncio.Barrier(CALLERS)

    async def caller(conn: asyncpg.Connection) -> int:
        await barrier.wait()
        async with conn.transaction():
            await conn.execute(seed_sql)
            number = await conn.fetchval(LOCK_INVOICE_SEQUENCE)
            await conn.execute(ADVANCE_INVOICE_SEQUENCE)
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
        assert await conn.fetchval("SELECT count(*) FROM invoice_number_sequences") == 0
    finally:
        await conn.close()

    results = await _first_callers(migrated_db.dsn, SEED_INVOICE_SEQUENCE)

    errors = [r for r in results if isinstance(r, BaseException)]
    assert errors == []
    assert sorted(r for r in results if isinstance(r, int)) == list(range(1, CALLERS + 1))
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        assert await conn.fetchval(
            "SELECT next_value FROM invoice_number_sequences WHERE id = 1"
        ) == (CALLERS + 1)
    finally:
        await conn.close()


async def test_sentinel_check_then_insert_seed_loses_the_race(migrated_db: Any) -> None:
    rounds, failed_rounds = 10, 0
    for _ in range(rounds):
        conn = await asyncpg.connect(migrated_db.dsn)
        try:
            await conn.execute("DELETE FROM invoice_number_sequences")
        finally:
            await conn.close()
        results = await _first_callers(migrated_db.dsn, RACY_SEED)
        if any(isinstance(r, asyncpg.UniqueViolationError) for r in results):
            failed_rounds += 1
    print(f"racy seed lost the race in {failed_rounds} of {rounds} rounds")
    assert failed_rounds > 0, "the harness never saw the race: it cannot prove the ON CONFLICT seed"
