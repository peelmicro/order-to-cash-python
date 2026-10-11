"""G5 (PR17, PR33, PR37, PR42): the two signal payloads, field by field, on a RECORDING connection.

Every field is a sentinel the test supplied, pairwise distinct (and none containing another), so a
transposed copy (`eventId` <-> `causationId`, `initialAmount` <-> `totalAmount`...) fails by name.
The headers mapping of each publish is a NEW object carrying `x-correlation-id` = the order id.
"""

import json
from datetime import UTC, datetime
from typing import Any

from otc_projector.application.ports.read_model import AppliedDocument, AppliedTotals
from otc_projector.domain.projection_delta import TimelineEntryDelta
from otc_projector.infrastructure.signal.nats_update_signal_publisher import (
    NatsUpdateSignalPublisher,
)

ORDER_ID = "11111111-aaaa-4aaa-8aaa-111111111111"
EVENT_ID = "22222222-bbbb-4bbb-8bbb-222222222222"
CAUSATION_ID = "33333333-cccc-4ccc-8ccc-333333333333"
OCCURRED_AT = datetime(2031, 7, 8, 9, 10, 11, 123000, tzinfo=UTC)


class RecordingConnection:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, dict[str, str] | None]] = []

    async def publish(
        self,
        subject: str,
        payload: bytes = b"",
        reply: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        assert reply == "", "a signal must carry no reply subject"
        self.published.append((subject, payload, headers))


def applied_document() -> AppliedDocument:
    return AppliedDocument(
        order_id=ORDER_ID,
        order_reference="ORD-424242",
        status="cancelled",
        cancellation_reason="operator_cancelled",
        despatch_reference="DES-717171",
        invoice_reference="INV-838383",
        payment_reference="PAY-949494",
        totals=AppliedTotals(
            initial_amount=5550001, initial_discount=6660002, total_amount=7770003
        ),
    )


def entry() -> TimelineEntryDelta:
    return TimelineEntryDelta(
        event_id=EVENT_ID,
        event_type="order.cancelled.v1",
        occurred_at=OCCURRED_AT,
        summary="Orden anulada por el operador — Zürich",
        causation_id=CAUSATION_ID,
        detail=None,
    )


async def published() -> RecordingConnection:
    connection = RecordingConnection()
    await NatsUpdateSignalPublisher(connection).publish(applied_document(), entry())
    return connection


async def test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field() -> None:
    connection = await published()
    assert [subject for subject, _, _ in connection.published] == [
        f"readmodel.order.updated.{ORDER_ID}",
        f"readmodel.timeline.appended.{ORDER_ID}",
    ]
    updated = json.loads(connection.published[0][1])
    appended = json.loads(connection.published[1][1])
    assert updated == {
        "eventId": EVENT_ID,
        "orderId": ORDER_ID,
        "orderReference": "ORD-424242",
        "status": "cancelled",
        "cancellationReason": "operator_cancelled",
        "references": {
            "despatchReference": "DES-717171",
            "invoiceReference": "INV-838383",
            "paymentReference": "PAY-949494",
        },
        "totals": {
            "initialAmount": 5550001,
            "initialDiscount": 6660002,
            "totalAmount": 7770003,
        },
        "occurredAt": "2031-07-08T09:10:11.123Z",
    }
    assert appended == {
        "eventId": EVENT_ID,
        "causationId": CAUSATION_ID,
        "orderId": ORDER_ID,
        "orderReference": "ORD-424242",
        "eventType": "order.cancelled.v1",
        "occurredAt": "2031-07-08T09:10:11.123Z",
        "summary": "Orden anulada por el operador — Zürich",
    }


async def test_pr17_non_ascii_text_is_written_raw_and_the_json_is_compact() -> None:
    connection = await published()
    payload = connection.published[1][1]
    assert "Zürich".encode() in payload, "non-ASCII must be written raw, not as \\u escapes"
    assert b"\\u" not in payload
    assert b": " not in payload, "the JSON must be compact"
    assert b", " not in payload, "the JSON must be compact"


async def test_pr17_two_publishes_carry_distinct_headers_each_with_the_order_id() -> None:
    connection = await published()
    first, second = connection.published[0][2], connection.published[1][2]
    assert first == {"x-correlation-id": ORDER_ID}
    assert second == {"x-correlation-id": ORDER_ID}
    assert first is not second, "the two publishes share one mutable headers mapping"
    publisher_connection = RecordingConnection()
    publisher = NatsUpdateSignalPublisher(publisher_connection)
    await publisher.publish(applied_document(), entry())
    await publisher.publish(applied_document(), entry())
    headers: list[Any] = [h for _, _, h in publisher_connection.published]
    assert len({id(h) for h in headers}) == 4, "a headers mapping was reused across publishes"


async def test_pr17_a_placeholder_document_publishes_no_totals() -> None:
    placeholder_state = AppliedDocument(
        order_id=ORDER_ID,
        order_reference=None,
        status="placed",
        cancellation_reason=None,
        despatch_reference=None,
        invoice_reference=None,
        payment_reference=None,
        totals=None,
    )
    connection = RecordingConnection()
    await NatsUpdateSignalPublisher(connection).publish(placeholder_state, entry())
    updated = json.loads(connection.published[0][1])
    assert "totals" not in updated
    assert "orderReference" not in updated
    assert updated["status"] == "placed"


async def test_pr37_each_optional_field_is_guarded_by_its_own_value() -> None:
    """Sweep survivors (M3): with ALL optional fields present, a guard that tested another field's
    value (`if applied.payment_reference is not None` written on the invoice) is unobservable. One
    field present at a time makes each guard read its own."""

    def only(**present: Any) -> AppliedDocument:
        fields: dict[str, Any] = {
            "order_reference": None,
            "cancellation_reason": None,
            "despatch_reference": None,
            "invoice_reference": None,
            "payment_reference": None,
        }
        fields.update(present)
        return AppliedDocument(order_id=ORDER_ID, status="paid", totals=None, **fields)

    cases = {
        "cancellation_reason": ("operator_cancelled", "cancellationReason", None),
        "despatch_reference": ("DES-717171", "despatchReference", "references"),
        "invoice_reference": ("INV-838383", "invoiceReference", "references"),
        "payment_reference": ("PAY-949494", "paymentReference", "references"),
    }
    for attribute, (value, wire_name, container) in cases.items():
        connection = RecordingConnection()
        await NatsUpdateSignalPublisher(connection).publish(only(**{attribute: value}), entry())
        updated = json.loads(connection.published[0][1])
        present = updated[container] if container else updated
        assert present[wire_name] == value, f"{attribute} did not reach {wire_name}"
        others = {"despatchReference", "invoiceReference", "paymentReference"} - {wire_name}
        for other in others:
            assert updated.get("references", {}).get(other) is None, (attribute, other)
        if attribute != "cancellation_reason":
            assert updated.get("cancellationReason") is None, attribute
