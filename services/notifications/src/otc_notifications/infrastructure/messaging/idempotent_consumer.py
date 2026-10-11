"""CANONICAL copy of the idempotent-consumer pattern (R17, R18, OI10, OI12).

Every write model that consumes facts carries a byte-identical copy of this file after this banner
(features 17-24 copy it verbatim). `tests/unit/test_idempotent_consumer_parity.py` (in the Orders
service) proves it mechanically: every copy equals this file outside the banner, this file names no
service and imports only the standard library and `sqlalchemy`, every consumer of facts has a copy,
and a variant for a store that is not relational carries a `Divergence:` line.

How it works. The dedup row is the FIRST statement of the unit of work's transaction, written
with `INSERT ... ON CONFLICT (event_id, consumer) DO NOTHING RETURNING id`. No row back means the
pair was already recorded: the transaction is rolled back (nothing was written, `work` never ran)
and the outcome is `DUPLICATE`. There is no `SELECT` anywhere in the dedup path and no duplicate-key
error to catch: PostgreSQL aborts the whole transaction on ANY error, so a caught unique violation
would leave nothing usable, while `ON CONFLICT DO NOTHING` returns normally. A concurrent second
delivery of the same pair waits on the first transaction's insertion and returns no row once it
commits. `work` runs inside the same transaction, so the dedup row, the state change and every
outbox or command row commit together or not at all.
"""

import enum
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String, Uuid, table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .consumer_name import ConsumerName


class ConsumptionOutcome(enum.Enum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"


class SessionBound(Protocol):
    @property
    def session(self) -> AsyncSession: ...


PROCESSED_EVENTS = table(
    "processed_events",
    Column("id", Uuid),
    Column("event_id", Uuid),
    Column("consumer", String),
    Column("processed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
)


class _Duplicate(Exception):
    """Raised inside the transaction so the unit of work rolls it back."""


class IdempotentConsumer[T: SessionBound]:
    def __init__(
        self,
        *,
        begin: Callable[[], AbstractAsyncContextManager[T]],
        clock: Callable[[], datetime],
    ) -> None:
        self._begin = begin
        self._clock = clock

    async def run_once(
        self,
        event_id: UUID,
        consumer: ConsumerName,
        work: Callable[[T], Awaitable[None]],
    ) -> ConsumptionOutcome:
        try:
            async with self._begin() as transaction:
                now = self._clock()
                inserted = (
                    await transaction.session.execute(
                        pg_insert(PROCESSED_EVENTS)
                        .values(
                            id=uuid4(),
                            event_id=event_id,
                            consumer=consumer.value,
                            processed_at=now,
                            created_at=now,
                        )
                        .on_conflict_do_nothing(index_elements=["event_id", "consumer"])
                        .returning(PROCESSED_EVENTS.c.id)
                    )
                ).first()
                if inserted is None:
                    raise _Duplicate
                await work(transaction)
        except _Duplicate:
            return ConsumptionOutcome.DUPLICATE
        return ConsumptionOutcome.PROCESSED
