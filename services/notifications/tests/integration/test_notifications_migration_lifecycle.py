"""Acceptance 1 and 3 - the migration lifecycle of `otc_notifications` and its closed relation set
(unit: the migration history; the set of relations of the database).

`otc_notifications` contains `processed_events` and NOTHING else (Databases.EN.md section 7). The
claim is a closed-set equality over every relation kind in `pg_class` (tables, partitioned tables,
views, materialized views, sequences, foreign tables, composite types AND indexes) with
`alembic_version` and its own primary-key index named explicitly. A stray table, a view, a sequence
or an index fails it by name. Downgrade leaves exactly `alembic_version` (and its key index).
"""

from typing import Any

import asyncpg
import pytest

pytestmark = pytest.mark.integration

# relkind r=table, i=index, S=sequence, v=view, m=matview, p=partitioned table, I=partitioned index,
# c=composite type, f=foreign table (t, TOAST, lives in pg_toast and is not in `public`).
ALEMBIC_ONLY = {("alembic_version", "r"), ("alembic_version_pkc", "i")}
EXPECTED_AFTER_UPGRADE = ALEMBIC_ONLY | {
    ("processed_events", "r"),
    ("pk_processed_events", "i"),
    ("uq_processed_events_event_id_consumer", "i"),
}
RELATIONS = """
SELECT c.relname, c.relkind::text AS relkind
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public'
"""


async def _relations(dsn: str) -> set[tuple[str, str]]:
    conn = await asyncpg.connect(dsn)
    try:
        return {(r["relname"], r["relkind"]) for r in await conn.fetch(RELATIONS)}
    finally:
        await conn.close()


NAMESPACES = """
SELECT nspname FROM pg_namespace
 WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast')
   AND nspname NOT LIKE 'pg_temp%' AND nspname NOT LIKE 'pg_toast_temp%'
"""


async def _namespaces(dsn: str) -> set[str]:
    """Closed set of non-system schemas: a relation created outside `public` is invisible to the
    public-scoped relation sets, so the schema itself is asserted."""
    conn = await asyncpg.connect(dsn)
    try:
        return {r["nspname"] for r in await conn.fetch(NAMESPACES)}
    finally:
        await conn.close()


async def _version(dsn: str) -> list[str]:
    conn = await asyncpg.connect(dsn)
    try:
        return [
            r["version_num"] for r in await conn.fetch("SELECT version_num FROM alembic_version")
        ]
    finally:
        await conn.close()


def _diagnostic(expected: set[tuple[str, str]], live: set[tuple[str, str]]) -> str:
    return f"missing: {sorted(expected - live)}\nextra: {sorted(live - expected)}"


async def test_upgrade_downgrade_reupgrade_lifecycle(
    fresh_database: Any, alembic_runner: Any
) -> None:
    db = fresh_database
    assert await _relations(db.dsn) == set()
    assert await _namespaces(db.dsn) == {"public"}

    await alembic_runner(db.url, "upgrade", "head")
    after_up = await _relations(db.dsn)
    assert after_up == EXPECTED_AFTER_UPGRADE, _diagnostic(EXPECTED_AFTER_UPGRADE, after_up)
    assert await _namespaces(db.dsn) == {"public"}
    assert await _version(db.dsn) == ["0001"]

    await alembic_runner(db.url, "downgrade", "base")
    after_down = await _relations(db.dsn)
    # closed set: nothing but alembic_version (its empty table and key index)
    assert after_down == ALEMBIC_ONLY, _diagnostic(ALEMBIC_ONLY, after_down)
    assert await _namespaces(db.dsn) == {"public"}
    assert await _version(db.dsn) == []

    await alembic_runner(db.url, "upgrade", "head")
    assert await _relations(db.dsn) == after_up
    assert await _namespaces(db.dsn) == {"public"}
    assert await _version(db.dsn) == ["0001"]


async def test_otc_notifications_contains_processed_events_and_nothing_else(
    migrated_db: Any,
) -> None:
    live = await _relations(migrated_db.dsn)
    assert live == EXPECTED_AFTER_UPGRADE, _diagnostic(EXPECTED_AFTER_UPGRADE, live)
    # the claim in words: the only non-alembic table is processed_events, and there is no sequence,
    # view, matview, foreign table or composite type at all
    assert {n for n, k in live if k == "r"} - {"alembic_version"} == {"processed_events"}
    assert {(n, k) for n, k in live if k not in ("r", "i")} == set()


async def test_no_postgres_enum_types(migrated_db: Any) -> None:
    """The plan's "never a PostgreSQL enum": no enum type exists in the database."""
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        rows = await conn.fetch(
            "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
            "WHERE n.nspname = 'public' AND t.typtype::text = 'e'"
        )
    finally:
        await conn.close()
    assert [r["typname"] for r in rows] == []
