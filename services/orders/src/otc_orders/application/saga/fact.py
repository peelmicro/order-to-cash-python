"""`SagaFact`: the application's view of one consumed fact (`design.md` 5.5).

Built inside the processing unit from a validated envelope and the fact's own typed payload model:
the ids are `UniqueId` (the nil UUID is refused there, so a fact with a nil `correlationId` raises
and is redelivered, never silently acknowledged), and `occurred_at` is the UTC millisecond the
domain accepts (L22).
"""

from dataclasses import dataclass
from datetime import datetime

from otc_contracts import WireModel
from otc_shared_kernel import UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class SagaFact:
    event_id: UniqueId
    event_type: str
    correlation_id: UniqueId
    occurred_at: datetime
    payload: WireModel
    topic: str
