# ruff: noqa: I001 - the copy keeps the canonical's import order; the parity guard compares it
"""Billing's COPY of Orders' `infrastructure/outbox/wire.py` (the canonical).

The canonical: `services/orders/src/otc_orders/infrastructure/outbox/wire.py`.
After this docstring the copy equals it, modulo the token map `otc_orders` ->
`otc_billing` and `ORDERS_FACTS_TOPIC` -> `BILLING_FACTS_TOPIC`, and modulo the
formatter's line reflow of the longer names. Any other difference fails
`tests/architecture/test_outbox_copy_parity.py`. Change the canonical, never this copy.
"""

import json
from typing import Any

from otc_contracts import Envelope, to_wire_json
from otc_billing.infrastructure.outbox.publisher import PublishableFact
from otc_billing.infrastructure.persistence.models import Outbox


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
