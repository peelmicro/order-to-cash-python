"""`OutboxRelay.run_once()`: claim, publish, stamp, commit (R14; OI2-5, 8, 13, 14, 17, 18).

One `AsyncSession` and one transaction per cycle, pinned to `READ COMMITTED` (L2: at `REPEATABLE
READ` PostgreSQL raises `40001` on a locking read of a row a concurrent relay stamped and
committed).
The claim is `SELECT ... WHERE published_at IS NULL ORDER BY seq LIMIT :n FOR UPDATE SKIP LOCKED`:
selection by NULLABILITY, never by a stored high-water mark (OI3); `seq` is the only ordering (OI2).

The ONLY commit is the success path. A publication failure or timeout raises the private
`_CycleAborted` inside `session.begin()`, which rolls the transaction back; it is caught OUTSIDE the
block and turned into a result (L6). A cycle that fails after a publish and before the commit is
indistinguishable from "the relay died before stamping", which R14 already accepts as at-least-once.

Nothing here catches `BaseException` or uses a bare handler: `asyncio.CancelledError` is a
`BaseException` and propagates (L8); a deadline of `asyncio.timeout` is a `TimeoutError`.

A row that cannot become a valid envelope is a POISON row (OI18, gate point G1): the clean prefix of
the claim is published and stamped, the poison row and everything after it stay unstamped, one ERROR
line names it, and the cycle returns normally. It is never skipped, parked, deleted or reordered.

Tracing (`R56`, `R57`): for every row whose `trace_parent` is recorded the relay restores that
context, starts an `outbox.publish` PRODUCER span under it (not made current: the relay publishes a
batch), and injects THAT span's context as the record's `traceparent` header, so the consumer's span
is a child of the producer span and the producer span a child of the writer's. The spans end when
the batch is acknowledged or aborted. A row with no recorded trace publishes with no header at all.

Lag (`R59`): at the start of every `run_once` the relay reads the oldest unpublished row's
`occurred_at` (`SELECT min(occurred_at) ... WHERE published_at IS NULL`, its own short session) and
sets `otc_outbox_lag_ms` to `(clock.now() - oldest)` in milliseconds, `0` when nothing is pending.
It is a synchronous `Gauge.set` from this task (ledger L12), so a drained outbox reports `0` on
the NEXT cycle, not mid-cycle.

A deadlock victim (SQLSTATE `40P01`) is retried, whole cycle, up to `DEADLOCK_ATTEMPTS` (OI17). Only
`40P01`: a dropped connection is OI5's, not a retry's.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.contextvars import bound_contextvars

from otc_orders.application.ports.clock import Clock
from otc_orders.infrastructure.observability.metrics import Gauge
from otc_orders.infrastructure.observability.trace_context import (
    NO_TRACER,
    context_from_traceparent,
    kafka_trace_headers,
)
from otc_orders.infrastructure.outbox.publisher import (
    FactPublicationError,
    FactPublisher,
    PublishableFact,
)
from otc_orders.infrastructure.outbox.wire import to_publishable_fact
from otc_orders.infrastructure.persistence.models import Outbox

log = logging.getLogger("otc_orders.outbox.relay")

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
    spans: list[Span]


PUBLISH_SPAN = "outbox.publish"


def build_prefix(rows: Sequence[Outbox], tracer: Tracer = NO_TRACER) -> _Prefix:
    """Convert rows in `seq` order; stop at the first one that cannot become a valid envelope.

    `json.JSONDecodeError`, `pydantic.ValidationError` and `UnicodeEncodeError` are all `ValueError`
    subclasses, so these two exception types cover every reconstruction failure.
    """
    facts: list[PublishableFact] = []
    row_ids: list[UUID] = []
    spans: list[Span] = []
    for row in rows:
        restored = context_from_traceparent(row.trace_parent)
        span: Span | None = None
        headers: tuple[tuple[str, bytes], ...] = ()
        if restored is not None:
            span = tracer.start_span(PUBLISH_SPAN, context=restored, kind=SpanKind.PRODUCER)
            headers = kafka_trace_headers(trace.set_span_in_context(span, restored))
        try:
            facts.append(to_publishable_fact(row, headers))
        except (ValueError, TypeError) as error:
            if span is not None:
                span.end()
            poisoned = PoisonedRow(
                event_id=row.event_id,
                correlation_id=row.correlation_id,
                seq=row.seq,
                reason=f"{type(error).__name__}: {error}",
            )
            return _Prefix(facts, row_ids, poisoned, spans)
        if span is not None:
            spans.append(span)
        row_ids.append(row.id)
    return _Prefix(facts, row_ids, None, spans)


def end_spans(spans: Sequence[Span], error: BaseException | None) -> None:
    """End the batch's producer spans: with an error status when the batch was not acknowledged."""
    for span in spans:
        if error is not None:
            span.set_status(Status(StatusCode.ERROR, repr(error)))
        span.end()


class OutboxRelay:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        publisher: FactPublisher,
        clock: Clock,
        batch_size: int,
        publish_timeout: float,
        tracer: Tracer = NO_TRACER,
        lag: Gauge | None = None,
    ) -> None:
        self._sessions = sessions
        self._publisher = publisher
        self._clock = clock
        self._batch_size = batch_size
        self._publish_timeout = publish_timeout
        self._tracer = tracer
        self._lag = lag

    async def _record_lag(self) -> None:
        """Set the outbox-lag gauge: the oldest unpublished row's age in ms, `0` when none."""
        if self._lag is None:
            return
        async with self._sessions() as session:
            oldest = await session.scalar(
                select(func.min(Outbox.occurred_at)).where(Outbox.published_at.is_(None))
            )
        age = 0.0 if oldest is None else (self._clock.now() - oldest) / timedelta(milliseconds=1)
        self._lag.set(age)

    async def run_once(self) -> RelayResult:
        await self._record_lag()
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
                    prefix = build_prefix(rows, self._tracer)
                    if prefix.facts:
                        try:
                            async with asyncio.timeout(self._publish_timeout):
                                await self._publisher.publish(prefix.facts)
                        except (FactPublicationError, TimeoutError) as error:
                            end_spans(prefix.spans, error)
                            raise _CycleAborted(claimed, error) from error  # rolls back
                        end_spans(prefix.spans, None)
                        await session.execute(
                            update(Outbox)
                            .where(Outbox.id.in_(prefix.row_ids))
                            .values(published_at=self._clock.now())
                            .execution_options(synchronize_session=False)
                        )
            except _CycleAborted as aborted:
                for item in aborted.claimed:
                    with bound_contextvars(correlationId=str(item.correlation_id)):
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
            with bound_contextvars(correlationId=str(prefix.poisoned.correlation_id)):
                log.error(
                    "outbox record cannot become a valid envelope; it blocks its write model's "
                    "outbox",
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
