"""`CompensationStep`: one release the saga performed before an order was cancelled.

Shape of `asyncapi.yaml`'s `CompensationStep`: `step`, `eventType` and `occurredAt` are required,
`eventId` and `summary` are optional.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from otc_orders.domain.instants import require_utc
from otc_shared_kernel import UniqueId


class CompensationStepKind(Enum):
    STOCK_RELEASED = "stock_released"
    CREDIT_RELEASED = "credit_released"


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationStep:
    step: CompensationStepKind
    event_id: UniqueId | None
    event_type: str
    occurred_at: datetime
    summary: str | None = None

    def __post_init__(self) -> None:
        require_utc(self.occurred_at, field="occurred_at")
