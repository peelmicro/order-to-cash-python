"""`FactConsumption`: the port over the canonical idempotent consumer (R17, R18).

The infrastructure implements it with `IdempotentConsumer.run_once` under the consumer name
`orders.saga`; the application depends on this port because `application` may not import
`infrastructure`. `work` runs inside the dedup transaction, once, never retried.
"""

import enum
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from otc_orders.application.ports.unit_of_work import OrdersTransaction


class ConsumptionResult(enum.Enum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"


class FactConsumption(Protocol):
    async def run_once(
        self, event_id: UUID, work: Callable[[OrdersTransaction], Awaitable[None]]
    ) -> ConsumptionResult: ...
