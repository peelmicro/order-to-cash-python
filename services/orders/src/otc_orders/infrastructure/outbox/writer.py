"""`OutboxWriter`: domain events -> outbox rows, in the caller's transaction (R12, R13, OI1, OI19).

For each event, in raise order: narrow (an unknown class is refused), the `R11` guard over the six
scalar values (before anything is built), catalogue membership (`EVENT_TYPE` is a key of
`FACT_MODELS` and the payload is that fact's payload model), the typed `Envelope[P]` (the second,
wire-level `R11` check), then ONE row: `session.add(row)` and `await session.flush()`.

One flush per row, on purpose (L4): SQLAlchemy's unit of work may batch same-table inserts, and
#8's ORM assigned identity values out of `Add` order, so `seq` must not depend on the batching. The
only thing `seq` depends on is PostgreSQL's identity counter, advanced in raise order.

The writer copies the five identity fields into columns verbatim (`correlation_id` and
`causation_id` are the aggregate's, R12) and applies `wire_instant` to the instant, so the stored
`occurred_at`, the envelope's and every payload instant are the same millisecond (OI19).
`trace_parent` stays NULL until feature 27.
"""

from collections.abc import Iterable
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from otc_contracts import FACT_MODELS, to_wire_json
from otc_orders.application.ports.clock import Clock
from otc_orders.infrastructure.outbox.errors import UndeclaredFactError
from otc_orders.infrastructure.outbox.payloads import build_fact, narrow
from otc_orders.infrastructure.persistence.models import Outbox
from otc_shared_kernel import validate_domain_event_envelope


class OutboxWriter:
    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    async def write(self, session: AsyncSession, events: Iterable[object]) -> None:
        for raw in events:
            event = narrow(raw)
            event_type = type(event).EVENT_TYPE
            validate_domain_event_envelope(
                event_id=event.event_id,
                event_type=event_type,
                aggregate_id=event.aggregate_id,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                occurred_at=event.occurred_at,
            )
            fact_model = FACT_MODELS.get(event_type)
            if fact_model is None:
                raise UndeclaredFactError(event_type, "no model is registered for it")
            built = build_fact(event)
            declared = fact_model.model_fields["payload"].annotation
            if declared is not type(built.payload):
                raise UndeclaredFactError(
                    event_type,
                    f"the catalogue's payload is {declared!r}, not {type(built.payload).__name__}",
                )
            session.add(
                Outbox(
                    id=uuid4(),
                    event_id=event.event_id.value,
                    event_type=event_type,
                    aggregate_id=event.aggregate_id.value,
                    correlation_id=event.correlation_id.value,
                    causation_id=event.causation_id.value,
                    payload=to_wire_json(built.payload),
                    occurred_at=built.occurred_at,
                    published_at=None,
                    created_at=self._clock.now(),
                    trace_parent=None,
                )
            )
            await session.flush()
