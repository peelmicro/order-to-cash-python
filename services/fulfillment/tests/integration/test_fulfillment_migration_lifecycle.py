"""Acceptance 1 - the migration lifecycle (unit: the migration history), against postgres:18.6.

upgrade head from empty, downgrade base leaves only `alembic_version` (closed set read from the
catalog), re-upgrade succeeds. The same lifecycle is run by hand against the composed postgres; see
progress/impl_db_fulfillment.md.
"""

from typing import Any

import asyncpg
import pytest

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "alembic_version",
    "despatch_items",
    "despatch_number_sequences",
    "despatches",
    "outbox",
    "processed_events",
    "reservations",
    "stock",
}
# relkind r=table, p=partitioned, v=view, m=matview, S=sequence, f=foreign table, c=composite
RELATIONS = """
SELECT c.relname, c.relkind::text AS relkind
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind::text IN ('r','p','v','m','S','f','c')
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


async def test_upgrade_downgrade_reupgrade_lifecycle(
    fresh_database: Any, alembic_runner: Any
) -> None:
    db = fresh_database
    assert await _relations(db.dsn) == set()
    assert await _namespaces(db.dsn) == {"public"}

    await alembic_runner(db.url, "upgrade", "head")
    after_up = await _relations(db.dsn)
    assert {n for n, k in after_up if k == "r"} == EXPECTED_TABLES
    # the only sequences are the identity sequence of outbox.seq: closed, not "some sequence"
    assert {(n, k) for n, k in after_up if k != "r"} == {("outbox_seq_seq", "S")}
    assert await _namespaces(db.dsn) == {"public"}
    assert await _version(db.dsn) == ["0001"]

    await alembic_runner(db.url, "downgrade", "base")
    after_down = await _relations(db.dsn)
    # closed set: nothing but alembic_version (its empty table; no leftover sequence/view/type)
    assert after_down == {("alembic_version", "r")}
    assert await _namespaces(db.dsn) == {"public"}
    assert await _version(db.dsn) == []

    await alembic_runner(db.url, "upgrade", "head")
    assert await _relations(db.dsn) == after_up
    assert await _namespaces(db.dsn) == {"public"}
    assert await _version(db.dsn) == ["0001"]


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
