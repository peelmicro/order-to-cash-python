"""`python -m otc_seed`, end to end against real containers (this replaces the stub that asserted
`main() == 0` with no work behind it).

R-map (feature_list.json id 12): acceptance 4 through the real entry point (a second invocation
prints zeros), plus the exit codes the CLI documents: 0 seeded, 1 a store refused (here: a database
not migrated to head, named in the message), 2 no credential configured.
"""

import json
from typing import Any

import pytest

from otc_seed.presentation.cli import run

pytestmark = pytest.mark.integration


async def test_the_cli_seeds_the_stack_then_a_second_run_adds_nothing(
    settings: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run() == 0
    first = json.loads(capsys.readouterr().out)
    assert (
        first["totalAdded"]
        == 50 + 3 + 12 + 7 + 22 + 6 + 11 + 215 + 11 + 5 + 10 + 154 + 15 + 5 + 10 + 5 + 6
    )
    assert first["added"]["mongo"] == {"order_timeline": 6}

    assert await run() == 0
    second = json.loads(capsys.readouterr().out)
    assert second["totalAdded"] == 0


async def test_a_database_not_migrated_to_head_exits_1_naming_the_table_and_writes_nothing(
    stack: Any,
    fresh_database: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    env = {**stack.env(), "FULFILLMENT_DATABASE_URL": fresh_database.url}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert await run() == 1
    captured = capsys.readouterr()
    assert "fulfillment" in captured.err
    assert "table stock does not exist" in captured.err
    # verification of every target precedes every write: orders was healthy and is still empty
    import asyncpg

    conn = await asyncpg.connect(stack.orders.dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM currencies") == 0
    finally:
        await conn.close()


async def test_no_credential_exits_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)  # no `.env` here
    for name in (
        "POSTGRES_APP_PASSWORD",
        "MONGO_INITDB_ROOT_PASSWORD",
        "ORDERS_DATABASE_URL",
        "FULFILLMENT_DATABASE_URL",
        "BILLING_DATABASE_URL",
        "MONGO_URI",
    ):
        monkeypatch.delenv(name, raising=False)
    assert await run() == 2
    assert "no PostgreSQL credential" in capsys.readouterr().err
