"""OI17 (#8 id 87): a deadlock victim inside `run_once` is retried, not leaked (feature 14, 4.19).

The cycle is CONSTRUCTED, so it is deterministic (a change of kind, not of probability):

* relay A claims rows r1 and r2 (`FOR UPDATE SKIP LOCKED`) and its publisher waits;
* C, a raw connection, takes `LOCK TABLE outbox IN SHARE MODE` (compatible with A's `ROW SHARE`);
* A is released: it publishes, and its stamp (`ROW EXCLUSIVE`) blocks on C's table lock. The test
  waits until `pg_locks` shows A's request UNGRANTED (never on a sleep);
* C then asks `SELECT ... WHERE id = r1 FOR UPDATE` and blocks on A's row lock: a cycle.

A waited first, so A's `deadlock_timeout` (1 s, asserted against the fixture server by
`test_fixture_matches_deployed_server.py`) expires first and A is the victim: `40P01`. The case
where PostgreSQL picked C instead would show as C's statement raising, which the tests assert it
does not. Loop scope: default (function); every engine and connection dies in the test's loop.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import asyncpg
import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from otc_orders.infrastructure.outbox import relay as relay_module
from otc_orders.infrastructure.outbox.relay import RelayResult, sqlstate_of

RELAY_LOGGER = "otc_orders.outbox.relay"


class GatedPublisher:
    """Waits for `release` on its FIRST call only; every call is recorded."""

    def __init__(self) -> None:
        self.calls: list[list[uuid.UUID]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def publish(self, facts: Any) -> None:
        self.calls.append([fact.event_id for fact in facts])
        self.started.set()
        if len(self.calls) == 1:
            await self.release.wait()


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[uuid.UUID] = []

    async def publish(self, facts: Any) -> None:
        self.published.extend(fact.event_id for fact in facts)


@dataclass
class Scene:
    first: Any
    second: Any
    gate: GatedPublisher
    task_a: asyncio.Task[RelayResult]
    blocker: asyncpg.Connection[Any]


async def wait_for_ungranted_lock(
    dsn: str, application_name: str, *, watching: asyncio.Task[RelayResult] | None = None
) -> None:
    """Observed, not slept: poll `pg_locks` until the named backend has an UNGRANTED request.

    `watching` is relay A's task: if `run_once` has ENDED while we wait for it to block again, the
    wait cannot succeed, and the reason it ended is the diagnosis (a leaked deadlock victim)."""
    admin = await asyncpg.connect(dsn)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            waiting = await admin.fetchval(
                "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING (pid) "
                "WHERE NOT l.granted AND a.application_name = $1",
                application_name,
            )
            if waiting:
                return
            if watching is not None and watching.done():
                raise AssertionError(
                    "relay A's run_once ended instead of retrying the deadlock victim: "
                    f"{watching.exception()!r}"
                )
            await asyncio.sleep(0.05)
    finally:
        await admin.close()
    raise TimeoutError(f"{application_name} never showed an ungranted lock request in pg_locks")


async def run_the_cycle(row_planter: Any, make_relay: Any, migrated_db: Any) -> tuple[Scene, Any]:
    first = await row_planter.plant()
    second = await row_planter.plant()
    engine_a = create_async_engine(
        migrated_db.url, connect_args={"server_settings": {"application_name": "relay-a"}}
    )
    gate = GatedPublisher()
    relay_a = make_relay(
        gate, batch_size=2, sessions_override=async_sessionmaker(engine_a, expire_on_commit=False)
    )
    task_a: asyncio.Task[RelayResult] = asyncio.create_task(relay_a.run_once())
    await asyncio.wait_for(gate.started.wait(), timeout=10)

    blocker = await asyncpg.connect(migrated_db.dsn)
    await blocker.execute("BEGIN")
    await blocker.execute("LOCK TABLE outbox IN SHARE MODE")
    gate.release.set()
    await wait_for_ungranted_lock(migrated_db.dsn, "relay-a")  # A's stamp waits on C's table lock
    scene = Scene(first, second, gate, task_a, blocker)
    c_statement = asyncio.create_task(
        blocker.fetch("SELECT id FROM outbox WHERE id = $1 FOR UPDATE", first.id)
    )  # blocks on A's row lock: the cycle
    return scene, (engine_a, c_statement)


async def test_oi17_without_the_retry_the_constructed_deadlock_escapes_run_once_as_40p01(
    row_planter: Any,
    make_relay: Any,
    migrated_db: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reproduction, before the fix (#8 id 87, bullet 1): with the retry bound at one attempt
    the deadlock victim's `40P01` escapes `run_once`."""
    monkeypatch.setattr(relay_module, "DEADLOCK_ATTEMPTS", 1)
    scene, (engine_a, c_statement) = await run_the_cycle(row_planter, make_relay, migrated_db)
    try:
        with pytest.raises(DBAPIError) as escaped:
            await asyncio.wait_for(scene.task_a, timeout=20)
        print(f"OI17 reproduced, escaping run_once: {escaped.value!s}")
        assert sqlstate_of(escaped.value) == "40P01"
        assert "deadlock detected" in str(escaped.value)
        rows = await asyncio.wait_for(c_statement, timeout=10)
        assert len(rows) == 1, "C's statement succeeded: A, not C, was the victim"
    finally:
        await scene.blocker.execute("ROLLBACK")
        await scene.blocker.close()
        await engine_a.dispose()


async def test_oi17_run_once_survives_a_constructed_deadlock_victim_and_retries_the_cycle(
    row_planter: Any,
    make_relay: Any,
    migrated_db: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    scene, (engine_a, c_statement) = await run_the_cycle(row_planter, make_relay, migrated_db)
    try:
        with caplog.at_level(logging.DEBUG, logger=RELAY_LOGGER):
            rows = await asyncio.wait_for(c_statement, timeout=20)  # granted once A was aborted
            assert len(rows) == 1, "C's statement succeeded: A, not C, was the victim"
            # A is retrying: its new claim skips r1 (now C's) and its stamp waits on C's table lock
            await wait_for_ungranted_lock(migrated_db.dsn, "relay-a", watching=scene.task_a)
            await scene.blocker.execute("COMMIT")
            result = await asyncio.wait_for(scene.task_a, timeout=20)  # returns, never raises
    finally:
        await scene.blocker.close()
        await engine_a.dispose()

    assert isinstance(result, RelayResult)
    assert (result.claimed, result.published) == (1, 1), "the retried cycle took r2 only"
    warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and r.name == RELAY_LOGGER
    ]
    assert len(warnings) == 1, "exactly one retry was logged"
    assert warnings[0].attempt == 1  # type: ignore[attr-defined]
    assert scene.gate.calls == [
        [scene.first.event_id, scene.second.event_id],
        [scene.second.event_id],
    ]

    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        stamped = {
            row["event_id"]: row["published_at"] is not None
            for row in await conn.fetch("SELECT event_id, published_at FROM outbox")
        }
    finally:
        await conn.close()
    assert stamped == {scene.first.event_id: False, scene.second.event_id: True}

    recovered = RecordingPublisher()
    follow_up = await make_relay(recovered).run_once()
    assert recovered.published == [scene.first.event_id], "r1 is published by the next poll"
    assert follow_up.published == 1
