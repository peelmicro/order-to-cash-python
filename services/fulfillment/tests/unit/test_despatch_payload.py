"""`OrderDespatched` -> the `order.despatched.v1` envelope and payload, every field against a
distinct source value (R36's fact; the sibling of `test_outbox_payloads.py` for feature 18).

Each value the event carries is pairwise distinct across the test (four ids, the aggregate id apart
from every other id, company apart from retailer, two lines of different units, a sub-millisecond
instant), so a mapper that reads one field for another is seen.
"""

import json
import uuid
from datetime import UTC, datetime

from otc_contracts import to_wire_json
from otc_contracts.generated import asyncapi
from otc_fulfillment.domain.events import DespatchedLine, OrderDespatched
from otc_fulfillment.infrastructure.outbox.payloads import build_fact, narrow
from otc_shared_kernel import DespatchReference, UniqueId


def uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(f"00000000-0000-4000-8000-{n:012d}"))


OCCURRED_AT = datetime(2026, 10, 8, 9, 30, 5, 123987, tzinfo=UTC)  # sub-millisecond: truncated


def despatched() -> OrderDespatched:
    return OrderDespatched(
        event_id=uid(1),
        aggregate_id=uid(2),
        correlation_id=uid(3),
        causation_id=uid(4),
        occurred_at=OCCURRED_AT,
        order_reference="ORD-000123",
        despatch_reference=DespatchReference("DES-000031"),
        despatch_date=OCCURRED_AT,
        company_code="CMP-88",
        retailer_code="RET-77",
        lines=(
            DespatchedLine(product_code="PRD-A1", units=3),
            DespatchedLine(product_code="PRD-B2", units=5),
        ),
    )


def test_r36_the_despatched_fact_becomes_its_envelope_and_payload_with_every_field_equal_to_the_supplied_value() -> (  # noqa: E501
    None
):
    built = build_fact(despatched())

    assert isinstance(built.payload, asyncapi.OrderDespatchedPayload)
    assert json.loads(to_wire_json(built.payload)) == {
        "orderReference": "ORD-000123",
        "despatchReference": "DES-000031",
        "despatchDate": "2026-10-08T09:30:05.123Z",
        "companyCode": "CMP-88",
        "retailerCode": "RET-77",
        "lines": [
            {"productCode": "PRD-A1", "units": 3},
            {"productCode": "PRD-B2", "units": 5},
        ],
    }
    envelope = json.loads(to_wire_json(built.envelope))
    assert list(envelope)[:7] == [
        "eventId",
        "eventType",
        "aggregateId",
        "correlationId",
        "causationId",
        "occurredAt",
        "payload",
    ]
    assert envelope["eventId"] == str(uid(1))
    assert envelope["eventType"] == "order.despatched.v1"
    assert envelope["aggregateId"] == str(uid(2)), "the despatch advice's own id"
    assert envelope["correlationId"] == str(uid(3))
    assert envelope["causationId"] == str(uid(4))
    assert envelope["occurredAt"] == "2026-10-08T09:30:05.123Z"
    assert built.occurred_at == datetime(2026, 10, 8, 9, 30, 5, 123000, tzinfo=UTC)


def test_r36_the_despatch_date_in_the_payload_is_the_same_millisecond_as_the_envelopes() -> None:
    # OI19: the stored instant, the envelope's and every payload instant are one millisecond
    built = build_fact(despatched())
    envelope = json.loads(to_wire_json(built.envelope))

    assert (
        envelope["payload"]["despatchDate"] == envelope["occurredAt"] == "2026-10-08T09:30:05.123Z"
    )


def test_the_despatched_fact_is_narrowed_as_a_fulfillment_event() -> None:
    event = despatched()

    assert narrow(event) is event
