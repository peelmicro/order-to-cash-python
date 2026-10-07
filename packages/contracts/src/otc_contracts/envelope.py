"""The generic fact envelope, `Envelope[P]` (OI20, backlog 203 item 2).

Hand-written, not generated: `generated/asyncapi.py` stays the drift reference (its non-generic
`Envelope` carries `payload: dict[str, Any]`), and a test asserts this class has the generated
class's fields, aliases, order and `eventType` pattern. The writer uses `Envelope[<payload model>]`
(typed, validated); the relay uses `Envelope[dict[str, Any]]` (a pass-through of the stored
payload). One class, one field order (`specs/shared/asyncapi.yaml` `Envelope`).

It is a `WireModel`, so every JSON path (`model_dump_json`, `model_dump(mode="json")`,
`to_wire_json`) writes `.mmmZ` instants wherever they sit and refuses an instance that skipped
validation (`model_copy(update=...)`).
"""

from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field

from otc_contracts.wire import WireModel


class Envelope[P](WireModel):
    event_id: UUID
    event_type: Annotated[str, Field(pattern="^[a-z]+\\.[a-z_]+\\.v[0-9]+$")]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: P
