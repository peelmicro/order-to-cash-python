"""Backlog 211 across services - the REAL seed job, then each service's counter statements.

WHERE THIS LIVES: `tests/seed_counters/`, a neutral place no service owns (a service's tests must
not import `otc_seed`, and the seed's tests must not import the three services' SQL). It is the one
file that holds both halves of the claim: the seed writes `ORD-000001..006`, `DES-000001..005` and
`INV-000001..005` and no counter row, so the first number each service's counter hands out must be
`ORD-000007`, `DES-000006` and `INV-000006`.

THE SEEDED MAX, DERIVED (never typed in as an answer): the seed's dataset docstring
(`otc_seed/domain/data/sagas.py`) names 6 orders, 5 despatches and 5 invoices, and the test reads
`MAX` of each reference column back from the migrated database after the seed, so a change of the
seeded dataset fails on the stated maxima before it can make the allocation assertion lie.

WHAT RUNS: `run_seed` on private copies of the three migrated templates (and an unused MongoDB
database, the seed's fourth target), then `SEED` + `LOCK` + `ADVANCE` of each service's own
`sequences.py` in one transaction, exactly the allocator's shape. Loop scope: `function`; the
engines are built and closed inside the test's loop by the runtime's `aclose`.

ARMS (recorded in `progress/impl_seed_job.md`, Round 3): a counter seeded `VALUES (1, 1)` hands out
`ORD-000001`; a text MAX is covered by each service's own `above six digits` test.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from otc_billing.infrastructure.persistence.sequences import (
    ADVANCE_INVOICE_SEQUENCE,
    LOCK_INVOICE_SEQUENCE,
    SEED_INVOICE_SEQUENCE,
)
from otc_fulfillment.infrastructure.persistence.sequences import (
    ADVANCE_DESPATCH_SEQUENCE,
    LOCK_DESPATCH_SEQUENCE,
    SEED_DESPATCH_SEQUENCE,
)
from otc_orders.infrastructure.persistence.sequences import (
    ADVANCE_ORDER_SEQUENCE,
    LOCK_ORDER_SEQUENCE,
    SEED_ORDER_SEQUENCE,
)
from otc_seed.application import run_seed
from otc_seed.composition import build_runtime
from otc_seed.infrastructure.settings import SeedSettings

pytestmark = pytest.mark.integration

# (database, reference column, table, seed SQL, lock SQL, advance SQL, seeded MAX, first number)
COUNTERS = [
    (
        "orders",
        "order_reference",
        "orders",
        SEED_ORDER_SEQUENCE,
        LOCK_ORDER_SEQUENCE,
        ADVANCE_ORDER_SEQUENCE,
        6,
        7,
    ),
    (
        "fulfillment",
        "despatch_reference",
        "despatches",
        SEED_DESPATCH_SEQUENCE,
        LOCK_DESPATCH_SEQUENCE,
        ADVANCE_DESPATCH_SEQUENCE,
        5,
        6,
    ),
    (
        "billing",
        "invoice_reference",
        "invoices",
        SEED_INVOICE_SEQUENCE,
        LOCK_INVOICE_SEQUENCE,
        ADVANCE_INVOICE_SEQUENCE,
        5,
        6,
    ),
]
PREFIX = {"orders": "ORD", "fulfillment": "DES", "billing": "INV"}


@pytest_asyncio.fixture(loop_scope="function")
async def seeded(
    migrated_database_from_template: Callable[[str], Awaitable[Any]],
    fresh_mongo_database: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> dict[str, Any]:
    dbs = {
        name: await migrated_database_from_template(name)
        for name in ("orders", "fulfillment", "billing")
    }
    monkeypatch.chdir(tmp_path)  # no developer `.env` can reach the settings
    monkeypatch.setenv("ORDERS_DATABASE_URL", dbs["orders"].url)
    monkeypatch.setenv("FULFILLMENT_DATABASE_URL", dbs["fulfillment"].url)
    monkeypatch.setenv("BILLING_DATABASE_URL", dbs["billing"].url)
    monkeypatch.setenv("MONGO_URI", fresh_mongo_database.uri)
    monkeypatch.setenv("MONGO_DB_READMODEL", fresh_mongo_database.name)
    runtime = build_runtime(SeedSettings(_env_file=None))  # type: ignore[call-arg]
    try:
        await run_seed(runtime.targets)
    finally:
        await runtime.aclose()
    return dbs


@pytest.mark.parametrize(
    ("database", "column", "table", "seed_sql", "lock_sql", "advance_sql", "seeded_max", "first"),
    COUNTERS,
    ids=[c[0] for c in COUNTERS],
)
async def test_the_first_allocation_after_the_seed_job_is_above_the_seeded_references(
    seeded: dict[str, Any],
    database: str,
    column: str,
    table: str,
    seed_sql: str,
    lock_sql: str,
    advance_sql: str,
    seeded_max: int,
    first: int,
) -> None:
    conn = await asyncpg.connect(seeded[database].dsn)
    try:
        # the seeded maximum, read back (the seed wrote references and no counter row)
        suffixes = [
            int(r[0][4:])
            for r in await conn.fetch(f"SELECT {column} FROM {table}")  # noqa: S608
        ]
        assert max(suffixes) == seeded_max, f"{PREFIX[database]} seeded maximum changed"
        counter_table = {
            "orders": "order",
            "fulfillment": "despatch",
            "billing": "invoice",
        }[database] + "_number_sequences"
        assert await conn.fetchval(f"SELECT count(*) FROM {counter_table}") == 0  # noqa: S608
        async with conn.transaction():
            await conn.execute(seed_sql)
            number = await conn.fetchval(lock_sql)
            await conn.execute(advance_sql)
        assert number == first
        reference = f"{PREFIX[database]}-{number:06d}"
        # the allocated reference does not exist yet (it would violate the unique column)
        assert (
            await conn.fetchval(
                f"SELECT count(*) FROM {table} WHERE {column} = $1",  # noqa: S608
                reference,
            )
            == 0
        )
    finally:
        await conn.close()
