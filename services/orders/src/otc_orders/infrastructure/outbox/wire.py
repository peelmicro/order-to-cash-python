"""An outbox row -> the bytes the relay publishes (OI1, OI15, R11 at the producer).

Reads the ROW only: no clock, no `uuid4`, no default. The stored payload TEXT is parsed and the
whole envelope is written through the one serializer (`to_wire_json`); splicing the stored text into
a hand-assembled envelope would be a second serializer. For text the writer produced, and for #7's
golden bytes, parse-and-rewrite is a fixed point (proved by the byte-exact wire test).

No `traceparent` header and `trace_parent` stays NULL until feature 27 owns R56/R57: publishing
without the header `FactHeaders` marks required is the documented gap #7 and #8 both shipped; a
fabricated header would be worse.

A row that cannot become a valid envelope raises `ValueError` (pydantic's `ValidationError` and
`json.JSONDecodeError` are both `ValueError`) or `TypeError`: the relay treats it as poison (OI18).
"""

import json
from typing import Any

from otc_contracts import Envelope, to_wire_json
from otc_orders.infrastructure.outbox.publisher import PublishableFact
from otc_orders.infrastructure.persistence.models import Outbox


def to_publishable_fact(row: Outbox) -> PublishableFact:
    envelope = Envelope[dict[str, Any]](
        event_id=row.event_id,
        event_type=row.event_type,
        aggregate_id=row.aggregate_id,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        occurred_at=row.occurred_at,
        payload=json.loads(row.payload),
    )
    return PublishableFact(
        event_id=row.event_id,
        key=str(row.correlation_id).encode("utf-8"),
        value=to_wire_json(envelope).encode("utf-8"),
        headers=(
            ("x-event-type", row.event_type.encode("utf-8")),
            ("content-type", b"application/json"),
        ),
    )
