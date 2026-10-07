"""`SqlAlchemySagaIgnoredFactRecorder`: a durable row for a fact the saga deliberately ignored
(`design.md` 7.4; R25, SO8).

The row goes through the transaction's own session (the ORM unit of work, so the range guard fires),
and so commits with the dedup row: it runs only inside a first-delivery `run_once`, which makes it
idempotent. A row, not a log line, because R25's test must read what was recorded and because "why
did the saga ignore this?" is an operations question.
"""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from otc_orders.application.ports.clock import Clock
from otc_orders.application.ports.saga_ignored_facts import IgnoredFactMarker
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.persistence.models import SagaIgnoredFact
from otc_shared_kernel import UniqueId


class SqlAlchemySagaIgnoredFactRecorder:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    async def record(
        self,
        *,
        event_id: UniqueId,
        event_type: str,
        correlation_id: UniqueId,
        order_id: UniqueId | None,
        observed_status: OrderStatus | None,
        expected_status: OrderStatus | None,
        marker: IgnoredFactMarker,
    ) -> None:
        self._session.add(
            SagaIgnoredFact(
                id=uuid4(),
                event_id=event_id.value,
                event_type=event_type,
                order_id=order_id.value if order_id is not None else None,
                correlation_id=correlation_id.value,
                observed_status=observed_status.value if observed_status is not None else None,
                expected_status=expected_status.value if expected_status is not None else None,
                marker=marker.value,
                recorded_at=self._clock.now(),
            )
        )
        await self._session.flush()
