# ruff: noqa: I001 - the copy keeps the canonical's import order; the parity guard compares it
"""Billing's COPY of Orders' `infrastructure/outbox/writer.py` (the canonical).

The canonical: `services/orders/src/otc_orders/infrastructure/outbox/writer.py`.
After this docstring the copy equals it, modulo the token map `otc_orders` ->
`otc_billing` and `ORDERS_FACTS_TOPIC` -> `BILLING_FACTS_TOPIC`, and modulo the
formatter's line reflow of the longer names. Any other difference fails
`tests/architecture/test_outbox_copy_parity.py`. Change the canonical, never this copy.
"""

from collections.abc import Iterable
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from otc_contracts import FACT_MODELS, to_wire_json
from otc_billing.application.ports.clock import Clock
from otc_billing.infrastructure.outbox.errors import UndeclaredFactError
from otc_billing.infrastructure.outbox.payloads import build_fact, narrow
from otc_billing.infrastructure.persistence.models import Outbox
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
