"""`SqlAlchemySagaCommandLedger`: claim, mark sent, park, reject (`design.md` 9.6; SO11, L11, L13).

Every statement runs in its own short session and transaction, pinned to `READ COMMITTED`, OUTSIDE
any fact transaction. The claim and the lease are ONE statement: `next_attempt_at` carries two
meanings that never collide (when a parked row is next due, and when a claimed row's lease ends), so
a row being dispatched is excluded from every concurrent claim until the lease elapses and becomes
claimable again after it, with no new column.

* `try_claim` (the fast path) takes one named row.
* `claim_due` (the sweeper) takes a batch through a sub-select that locks with `SKIP LOCKED`, so two
  concurrent sweepers take disjoint batches without waiting; the outer predicate is re-evaluated
  under `READ COMMITTED` for a row that changed meanwhile.
* `mark_sent`, `reject` and `park` are conditional on `status IN CLAIMABLE` (feature 42: `park` was
  `status <> 'sent'`, which would have re-parked a `rejected` row): a row another claimer already
  marked `sent`, or resolved `rejected`, is never moved
  (#7 `drizzle-saga-command-store.ts:189-191`).
  `sent` means "a reply was delivered", never "the saga advanced"; `rejected` means "the responder
  gave a terminal business no" and is final (no claim, no sweep, no redrive).
* `park` stores `attempts` as the caller's total (the row's earlier attempts plus this cycle's), so
  the count accumulates across cycles; it is range-checked before the statement runs because an
  ORM-enabled statement bypasses the attribute guard (`range_guards.py`).

Instants come from the clock port, never `datetime.now()` (#7 D2).
Feature 42's `rejected` is terminal: it is in no claim predicate and in no write predicate.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Text, and_, cast, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_orders.application.ports.clock import Clock
from otc_orders.application.ports.saga_command_store import ClaimedCommand
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.infrastructure.persistence.models import SagaCommand
from otc_orders.infrastructure.persistence.range_guards import INT32_MAX, INT32_MIN, ensure_in_range
from otc_shared_kernel import UniqueId

CLAIMABLE = ("pending", "parked")
LAST_ERROR_LIMIT = 2000

_RETURNING = (
    SagaCommand.id,
    SagaCommand.order_id,
    SagaCommand.order_reference,
    SagaCommand.command,
    cast(SagaCommand.payload, Text).label("payload"),
    SagaCommand.attempts,
    SagaCommand.triggering_event_id,
)


def _plain(value: UUID) -> UUID:
    """asyncpg hands back its own `UUID` subclass (`asyncpg.pgproto.pgproto.UUID`), which `UniqueId`
    refuses (`type(...) is uuid.UUID`): rebuilt as the standard-library type."""
    return UUID(int=value.int)


def _claimed(row: Any) -> ClaimedCommand:
    return ClaimedCommand(
        id=_plain(row.id),
        order_id=UniqueId(_plain(row.order_id)),
        order_reference=row.order_reference,
        kind=SagaCommandKind(row.command),
        payload=row.payload,
        attempts=row.attempts,
        triggering_event_id=UniqueId(_plain(row.triggering_event_id)),
    )


class SqlAlchemySagaCommandLedger:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        *,
        lease_ms: int,
        pending_grace_ms: int,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._lease = timedelta(milliseconds=lease_ms)
        self._pending_grace = timedelta(milliseconds=pending_grace_ms)

    async def _execute(self, statement: Any, *, returning: bool = False) -> Sequence[Any]:
        """Run one statement in its own transaction; returns the RETURNING rows (none otherwise)."""
        async with self._sessions() as session, session.begin():
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            result = await session.execute(statement)
            return result.all() if returning else []

    async def try_claim(self, order_id: UniqueId, kind: SagaCommandKind) -> ClaimedCommand | None:
        now = self._clock.now()
        rows = await self._execute(
            update(SagaCommand)
            .where(
                SagaCommand.order_id == order_id.value,
                SagaCommand.command == kind.value,
                SagaCommand.status.in_(CLAIMABLE),
                or_(SagaCommand.next_attempt_at.is_(None), SagaCommand.next_attempt_at <= now),
            )
            .values(next_attempt_at=now + self._lease, updated_at=now)
            .returning(*_RETURNING)
            .execution_options(synchronize_session=False),
            returning=True,
        )
        return _claimed(rows[0]) if rows else None

    async def claim_due(self, batch_limit: int) -> list[ClaimedCommand]:
        now = self._clock.now()
        due = (
            select(SagaCommand.id)
            .where(
                or_(
                    and_(
                        SagaCommand.status == "pending",
                        SagaCommand.created_at <= now - self._pending_grace,
                        or_(
                            SagaCommand.next_attempt_at.is_(None),
                            SagaCommand.next_attempt_at <= now,
                        ),
                    ),
                    and_(SagaCommand.status == "parked", SagaCommand.next_attempt_at <= now),
                )
            )
            .order_by(SagaCommand.created_at)
            .limit(batch_limit)
            .with_for_update(skip_locked=True)
        )
        rows = await self._execute(
            update(SagaCommand)
            .where(SagaCommand.id.in_(due))
            .values(next_attempt_at=now + self._lease, updated_at=now)
            .returning(*_RETURNING)
            .execution_options(synchronize_session=False),
            returning=True,
        )
        return [_claimed(row) for row in rows]

    async def mark_sent(self, row_id: UUID) -> None:
        now = self._clock.now()
        await self._execute(
            update(SagaCommand)
            .where(SagaCommand.id == row_id, SagaCommand.status.in_(CLAIMABLE))
            .values(status="sent", sent_at=now, next_attempt_at=None, updated_at=now)
            .execution_options(synchronize_session=False)
        )

    async def reject(self, row_id: UUID, *, total_attempts: int, last_error: str) -> None:
        ensure_in_range(total_attempts, INT32_MIN, INT32_MAX, "saga_commands.attempts")
        now = self._clock.now()
        await self._execute(
            update(SagaCommand)
            .where(SagaCommand.id == row_id, SagaCommand.status.in_(CLAIMABLE))
            .values(
                status="rejected",
                attempts=total_attempts,
                last_error=last_error[:LAST_ERROR_LIMIT],
                next_attempt_at=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )

    async def park(
        self, row_id: UUID, *, total_attempts: int, last_error: str, retry_after_ms: int
    ) -> datetime:
        ensure_in_range(total_attempts, INT32_MIN, INT32_MAX, "saga_commands.attempts")
        now = self._clock.now()
        next_attempt_at = now + timedelta(milliseconds=retry_after_ms)
        await self._execute(
            update(SagaCommand)
            .where(SagaCommand.id == row_id, SagaCommand.status.in_(CLAIMABLE))
            .values(
                status="parked",
                attempts=total_attempts,
                last_error=last_error[:LAST_ERROR_LIMIT],
                next_attempt_at=next_attempt_at,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        return next_attempt_at
