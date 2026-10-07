"""`SqlAlchemyFactConsumption`: the canonical `IdempotentConsumer`, bound to the consumer name
`orders.saga` (R17, R18).

A thin adapter: the canonical consumer (`messaging/idempotent_consumer.py`, parity-guarded) is used
UNMODIFIED. The dedup row is its first statement, `work` runs in the same transaction, and a
duplicate returns with nothing written.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from otc_orders.application.ports.clock import Clock
from otc_orders.application.ports.unit_of_work import OrdersTransaction
from otc_orders.application.saga.fact_consumption import ConsumptionResult
from otc_orders.infrastructure.messaging.consumer_name import ConsumerName
from otc_orders.infrastructure.messaging.idempotent_consumer import (
    ConsumptionOutcome,
    IdempotentConsumer,
)
from otc_orders.infrastructure.persistence.unit_of_work import (
    SqlAlchemyOrdersTransaction,
    SqlAlchemyUnitOfWork,
)


class SqlAlchemyFactConsumption:
    def __init__(self, unit_of_work: SqlAlchemyUnitOfWork, clock: Clock) -> None:
        self._consumer = IdempotentConsumer[SqlAlchemyOrdersTransaction](
            begin=unit_of_work.begin, clock=clock.now
        )

    async def run_once(
        self, event_id: UUID, work: Callable[[OrdersTransaction], Awaitable[None]]
    ) -> ConsumptionResult:
        outcome = await self._consumer.run_once(event_id, ConsumerName.ORDERS_SAGA, work)
        if outcome is ConsumptionOutcome.DUPLICATE:
            return ConsumptionResult.DUPLICATE
        return ConsumptionResult.PROCESSED
