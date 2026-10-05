"""N1 (round 2): the write path is proved by BEHAVIOUR, not by what the code looks like.

`unit/test_write_path_population.py` matches call names in the AST; an aliased import
(`insert as add_rows`) or a bound method (`run = conn.execute`) hides a write from it (defeat-list
row 11). This test drives one real seed run and measures two independent things:

* the SPY: how many rows `ensure_row_in_range` (the range guard of `postgres.insert_missing`) saw;
* the WIRE: how many rows the engines actually sent in INSERT statements, counted by SQLAlchemy's
  `before_cursor_execute` event, whatever name or alias built the statement;

and a third, the databases themselves: the rows gained. All three must be 541 (78 orders rows, 253
fulfillment, 210 billing), so an INSERT that does not pass the guard makes WIRE exceed SPY and
fails here by name.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy import event

from otc_seed.application import run_seed
from otc_seed.composition import SeedRuntime
from otc_seed.infrastructure.range_check import ensure_row_in_range

pytestmark = pytest.mark.integration

EXPECTED_ROWS = 541  # the dataset's relational rows (see `test_seed_databases.EXPECTED_COUNTS`)


class _Wire:
    """Rows sent in INSERT statements, per engine, from the DBAPI event."""

    def __init__(self) -> None:
        self.rows = 0

    def attach(self, runtime: SeedRuntime) -> None:
        for engine in runtime._engines:  # the test measures the real engines
            event.listen(engine.sync_engine, "before_cursor_execute", self._count)

    def _count(
        self, _conn: Any, _cursor: Any, statement: str, parameters: Any, _ctx: Any, many: bool
    ) -> None:
        if statement.lstrip().upper().startswith("INSERT"):
            self.rows += len(parameters) if many else 1


async def _rows_in(dump: dict[str, list[tuple[str, str]]]) -> int:
    return sum(len(rows) for name, rows in dump.items() if name != "alembic_version")


async def test_every_row_the_engines_insert_passed_the_range_guard(
    runtime: SeedRuntime,
    stack: Any,
    dump_database: Callable[[str], Awaitable[dict[str, list[tuple[str, str]]]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def spy(table: Any, row: Any) -> None:
        seen.append(table.name)
        ensure_row_in_range(table, row)

    # the name `insert_missing` resolves at call time, in its own module
    monkeypatch.setattr("otc_seed.infrastructure.postgres.ensure_row_in_range", spy)
    wire = _Wire()
    wire.attach(runtime)

    await run_seed(runtime.targets)

    gained = 0
    for database in (stack.orders, stack.fulfillment, stack.billing):
        gained += await _rows_in(await dump_database(database.dsn))
    assert gained == EXPECTED_ROWS, "the databases did not gain the dataset's rows"
    assert len(seen) == EXPECTED_ROWS, f"the range guard saw {len(seen)} rows, not {EXPECTED_ROWS}"
    assert wire.rows == len(seen), (
        f"{wire.rows} rows were INSERTed but the range guard saw {len(seen)}: "
        "an INSERT path bypasses ensure_row_in_range"
    )
