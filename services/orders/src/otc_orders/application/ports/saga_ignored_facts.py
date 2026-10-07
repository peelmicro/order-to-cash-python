"""`SagaIgnoredFactRecorder`: the durable "the saga deliberately did nothing with this fact" (R25,
SO8).

Obtained only through the unit of work's transaction, so the record commits with the dedup row.
"""

import enum
from typing import Protocol

from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import UniqueId


class IgnoredFactMarker(enum.Enum):
    PRECONDITION_UNMET = "precondition_unmet"  # 18 characters, a varchar(20)
    UNKNOWN_ORDER = "unknown_order"


class SagaIgnoredFactRecorder(Protocol):
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
    ) -> None: ...
