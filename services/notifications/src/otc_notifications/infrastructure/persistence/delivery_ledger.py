"""`SqlAlchemyDeliveryLedger`: the durable `processed_events` ledger behind `DeliveryLedger`.

`record` composes the canonical `IdempotentConsumer` UNMODIFIED (byte-identical to Orders', guarded
by `test_idempotent_consumer_parity.py` case 1) under the consumer name `notifications`, with a
no-op `work`: the dedup INSERT is the whole effect, committed on its own (see `dispatch.py` for why
an e-mail cannot share that transaction). `forget` is this service's OWN code, in this file, so it
carries no obligation toward the parity guard: one `DELETE` of the pair, in its own transaction.
Each call opens its own `AsyncSession` and closes it (a session belongs to one inbound message).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from opentelemetry.trace import SpanKind, Tracer
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_notifications.application.ports.clock import Clock
from otc_notifications.application.ports.delivery_ledger import LedgerOutcome
from otc_notifications.infrastructure.messaging.consumer_name import ConsumerName
from otc_notifications.infrastructure.messaging.idempotent_consumer import (
    ConsumptionOutcome,
    IdempotentConsumer,
)
from otc_notifications.infrastructure.observability.trace_context import (
    NO_TRACER,
    TRANSACTION_SPAN,
)
from otc_notifications.infrastructure.persistence.models import ProcessedEvent

CONSUMER = ConsumerName.NOTIFICATIONS


class LedgerTransaction:
    """Satisfies the idempotent consumer's `SessionBound`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session


class SqlAlchemyDeliveryLedger:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        tracer: Tracer = NO_TRACER,
    ) -> None:
        self._sessions = sessions
        self._tracer = tracer
        self._consumer = IdempotentConsumer[LedgerTransaction](begin=self._begin, clock=clock.now)

    @asynccontextmanager
    async def _begin(self) -> AsyncIterator[LedgerTransaction]:
        with self._tracer.start_as_current_span(TRANSACTION_SPAN, kind=SpanKind.INTERNAL):
            async with self._sessions() as session, session.begin():
                await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
                yield LedgerTransaction(session)

    async def record(self, event_id: UUID) -> LedgerOutcome:
        async def nothing_else(_transaction: LedgerTransaction) -> None:
            return None

        outcome = await self._consumer.run_once(event_id, CONSUMER, nothing_else)
        if outcome is ConsumptionOutcome.DUPLICATE:
            return LedgerOutcome.DUPLICATE
        return LedgerOutcome.RECORDED

    async def forget(self, event_id: UUID) -> None:
        with self._tracer.start_as_current_span(TRANSACTION_SPAN, kind=SpanKind.INTERNAL):
            async with self._sessions() as session, session.begin():
                await session.execute(
                    delete(ProcessedEvent).where(
                        ProcessedEvent.event_id == event_id,
                        ProcessedEvent.consumer == CONSUMER.value,
                    )
                )
