"""Fulfillment's COPY of Orders' `infrastructure/outbox/relay.py` (the canonical).

The canonical: `services/orders/src/otc_orders/infrastructure/outbox/relay.py`.
After this docstring the copy equals it, modulo the token map `otc_orders` ->
`otc_fulfillment` and `ORDERS_FACTS_TOPIC` -> `FULFILLMENT_FACTS_TOPIC`, and modulo the
formatter's line reflow of the longer names. Any other difference fails
`tests/architecture/test_outbox_copy_parity.py`. Change the canonical, never this copy.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_fulfillment.application.ports.clock import Clock
from otc_fulfillment.infrastructure.outbox.publisher import (
    FactPublicationError,
    FactPublisher,
    PublishableFact,
)
from otc_fulfillment.infrastructure.outbox.wire import to_publishable_fact
from otc_fulfillment.infrastructure.persistence.models import Outbox

log = logging.getLogger("otc_fulfillment.outbox.relay")

DEADLOCK_DETECTED = "40P01"
DEADLOCK_ATTEMPTS = 3
DEADLOCK_BACKOFF_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class PoisonedRow:
    event_id: UUID
    correlation_id: UUID
    seq: int
    reason: str


@dataclass(frozen=True, slots=True)
class RelayResult:
    claimed: int
    published: int
    poisoned: PoisonedRow | None


@dataclass(frozen=True, slots=True)
class _Claimed:
    """What the log lines need, captured BEFORE the transaction ends (an ORM row is expired by a
    rollback and must not be touched afterwards)."""

    event_id: UUID
    correlation_id: UUID
    seq: int


class _CycleAborted(Exception):
    def __init__(self, claimed: Sequence[_Claimed], error: BaseException) -> None:
        super().__init__(repr(error))
        self.claimed = tuple(claimed)
        self.error = error


def sqlstate_of(error: BaseException) -> str | None:
    """The SQLSTATE of a `DBAPIError`, or None for anything else (or an error carrying none)."""
    if not isinstance(error, DBAPIError):
        return None
    state = getattr(error.orig, "sqlstate", None)
    return state if isinstance(state, str) else None


@dataclass(frozen=True, slots=True)
class _Prefix:
    facts: list[PublishableFact]
    row_ids: list[UUID]
    poisoned: PoisonedRow | None


def build_prefix(rows: Sequence[Outbox]) -> _Prefix:
    """Convert rows in `seq` order; stop at the first one that cannot become a valid envelope.

    `json.JSONDecodeError`, `pydantic.ValidationError` and `UnicodeEncodeError` are all `ValueError`
    subclasses, so these two exception types cover every reconstruction failure.
    """
    facts: list[PublishableFact] = []
    row_ids: list[UUID] = []
    for row in rows:
        try:
            facts.append(to_publishable_fact(row))
        except (ValueError, TypeError) as error:
            poisoned = PoisonedRow(
                event_id=row.event_id,
                correlation_id=row.correlation_id,
                seq=row.seq,
                reason=f"{type(error).__name__}: {error}",
            )
            return _Prefix(facts, row_ids, poisoned)
        row_ids.append(row.id)
    return _Prefix(facts, row_ids, None)


class OutboxRelay:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        publisher: FactPublisher,
        clock: Clock,
        batch_size: int,
        publish_timeout: float,
    ) -> None:
        self._sessions = sessions
        self._publisher = publisher
        self._clock = clock
        self._batch_size = batch_size
        self._publish_timeout = publish_timeout

    async def run_once(self) -> RelayResult:
        attempt = 1
        while True:
            try:
                return await self._cycle()
            except DBAPIError as error:
                if sqlstate_of(error) != DEADLOCK_DETECTED or attempt == DEADLOCK_ATTEMPTS:
                    raise
                log.warning(
                    "outbox relay cycle was a deadlock victim; retrying",
                    extra={"attempt": attempt},
                )
                attempt += 1
                await asyncio.sleep(DEADLOCK_BACKOFF_SECONDS)

    async def _cycle(self) -> RelayResult:
        async with self._sessions() as session:
            try:
                async with session.begin():
                    await session.connection(
                        execution_options={"isolation_level": "READ COMMITTED"}
                    )
                    rows = (
                        await session.scalars(
                            select(Outbox)
                            .where(Outbox.published_at.is_(None))
                            .order_by(Outbox.seq)
                            .limit(self._batch_size)
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                    claimed = [_Claimed(row.event_id, row.correlation_id, row.seq) for row in rows]
                    prefix = build_prefix(rows)
                    if prefix.facts:
                        try:
                            async with asyncio.timeout(self._publish_timeout):
                                await self._publisher.publish(prefix.facts)
                        except (FactPublicationError, TimeoutError) as error:
                            raise _CycleAborted(claimed, error) from error  # rolls back
                        await session.execute(
                            update(Outbox)
                            .where(Outbox.id.in_(prefix.row_ids))
                            .values(published_at=self._clock.now())
                            .execution_options(synchronize_session=False)
                        )
            except _CycleAborted as aborted:
                for item in aborted.claimed:
                    log.error(
                        "outbox record not published; its claim was rolled back",
                        extra={
                            "correlationId": str(item.correlation_id),
                            "eventId": str(item.event_id),
                            "seq": item.seq,
                            "error": repr(aborted.error),
                        },
                    )
                return RelayResult(claimed=len(aborted.claimed), published=0, poisoned=None)
        if prefix.poisoned is not None:
            log.error(
                "outbox record cannot become a valid envelope; it blocks its write model's outbox",
                extra={
                    "correlationId": str(prefix.poisoned.correlation_id),
                    "eventId": str(prefix.poisoned.event_id),
                    "seq": prefix.poisoned.seq,
                    "error": prefix.poisoned.reason,
                },
            )
        return RelayResult(
            claimed=len(claimed), published=len(prefix.facts), poisoned=prefix.poisoned
        )
