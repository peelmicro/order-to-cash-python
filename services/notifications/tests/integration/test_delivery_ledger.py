"""The real `SqlAlchemyDeliveryLedger` against PostgreSQL: the durable ledger R17/R18 stand on.

Each test builds its own engines in its own loop and disposes them. A second ledger over a second
engine stands for a process that restarted: it shares nothing with the first but the database.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from otc_notifications.application.ports.delivery_ledger import LedgerOutcome
from otc_notifications.infrastructure.clock import SystemClock
from otc_notifications.infrastructure.persistence.delivery_ledger import SqlAlchemyDeliveryLedger

EVENT = uuid.UUID("0000cafe-0000-4000-8000-00000000cafe")


@pytest_asyncio.fixture(loop_scope="function")
async def second_engine(migrated_db: Any) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_db.url)
    try:
        yield engine
    finally:
        await engine.dispose()


def ledger_over(engine: AsyncEngine) -> SqlAlchemyDeliveryLedger:
    return SqlAlchemyDeliveryLedger(
        async_sessionmaker(engine, expire_on_commit=False), SystemClock()
    )


async def test_r17_the_first_record_is_recorded_and_the_row_is_durable_across_a_new_engine(
    engine: AsyncEngine,
    second_engine: AsyncEngine,
    ledger_rows: Any,
) -> None:
    assert await ledger_over(engine).record(EVENT) is LedgerOutcome.RECORDED

    assert await ledger_over(second_engine).record(EVENT) is LedgerOutcome.DUPLICATE, (
        "a different engine (a restarted process) sees the row"
    )
    assert await ledger_rows() == [(EVENT, "notifications")]


async def test_r18_a_duplicate_writes_nothing_and_changes_no_row(
    engine: AsyncEngine,
    ledger_rows: Any,
) -> None:
    ledger = ledger_over(engine)
    await ledger.record(EVENT)
    before = await ledger_rows()

    for _ in range(3):
        assert await ledger.record(EVENT) is LedgerOutcome.DUPLICATE

    assert await ledger_rows() == before


async def test_forget_removes_exactly_the_pair_and_the_event_can_be_recorded_again(
    engine: AsyncEngine,
    ledger_rows: Any,
) -> None:
    other = uuid.UUID("0000f00d-0000-4000-8000-00000000f00d")
    ledger = ledger_over(engine)
    await ledger.record(EVENT)
    await ledger.record(other)

    await ledger.forget(EVENT)

    assert await ledger_rows() == [(other, "notifications")], "only the forgotten pair is gone"
    assert await ledger.record(EVENT) is LedgerOutcome.RECORDED


async def test_forget_of_an_unknown_event_is_a_no_op(
    engine: AsyncEngine,
    ledger_rows: Any,
) -> None:
    await ledger_over(engine).forget(EVENT)
    assert await ledger_rows() == []


async def test_r18_concurrent_records_of_one_event_id_yield_exactly_one_recorded(
    engine: AsyncEngine,
    second_engine: AsyncEngine,
    ledger_rows: Any,
) -> None:
    ledgers = [ledger_over(engine), ledger_over(second_engine)] * 4
    outcomes = await asyncio.gather(*(ledger.record(EVENT) for ledger in ledgers))

    assert outcomes.count(LedgerOutcome.RECORDED) == 1
    assert outcomes.count(LedgerOutcome.DUPLICATE) == len(ledgers) - 1
    assert await ledger_rows() == [(EVENT, "notifications")]
