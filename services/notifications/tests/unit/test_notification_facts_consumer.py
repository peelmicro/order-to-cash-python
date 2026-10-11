"""The fact consumer task, through the REAL dispatcher, handlers, templates and dispatch unit.

Only the two ports are fakes (an in-memory ledger and a recording sender): every fact of the
fourteen is fed to `NotificationFactsConsumerTask.handle` as the producer's bytes, so the notified-
fact filter is CROSSED, not bypassed (#8's first review). Also here: the malformed-envelope
acknowledgement, the envelope copy (#8 id 58: the subject's correlation id is the ENVELOPE's, and
the envelope's other ids are all different), a poisoned payload propagating, and the topic being
irrelevant to routing.
"""

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from otc_notifications.application.ports.fact_stream import FactMessage
from otc_notifications.application.scope import NotificationsScope
from otc_notifications.composition import build_dispatcher
from otc_notifications.presentation.notification_facts_consumer import (
    NotificationFactsConsumerTask,
)

NOTIFIED = [
    "order.placed.v1",
    "order.confirmed.v1",
    "order.despatched.v1",
    "invoice.issued.v1",
    "payment.received.v1",
    "order.completed.v1",
    "order.cancelled.v1",
]
NOT_NOTIFIED = [
    "stock.reserved.v1",
    "stock.rejected.v1",
    "stock.released.v1",
    "credit.approved.v1",
    "credit.rejected.v1",
    "credit.released.v1",
    "order.saga_failed.v1",
]
RECIPIENT_DOMAIN = "@retailer.order-to-cash.example"


def record(value: bytes, topic: str = "otc.orders.facts.v1") -> FactMessage:
    return FactMessage(topic=topic, partition=0, offset=0, key=None, value=value, headers=())


@pytest.fixture
def consumer(ledger: Any, sender: Any) -> NotificationFactsConsumerTask:
    class Unused:
        async def run(self, handler: Any, stop: Any) -> None:
            raise AssertionError("handle() is driven directly")

    return NotificationFactsConsumerTask(
        subscriber=Unused(),
        dispatcher=build_dispatcher(),
        scope_factory=lambda: NotificationsScope(ledger=ledger, sender=sender),
    )


@pytest.mark.parametrize("event_type", NOTIFIED)
async def test_each_notified_fact_is_sent_once_through_the_port_with_its_event_id_as_message_id(
    consumer: NotificationFactsConsumerTask,
    ledger: Any,
    sender: Any,
    facts: Any,
    event_type: str,
) -> None:
    event = facts.event(event_type)

    await consumer.handle(record(facts.wire(event_type)))

    [message] = sender.sent
    assert message.message_id == f"{event.event_id}@order-to-cash"
    assert message.to.endswith(RECIPIENT_DOMAIN)
    assert ledger.recorded == {event.event_id}


@pytest.mark.parametrize("event_type", NOT_NOTIFIED)
async def test_a_well_formed_non_notified_fact_produces_no_email_and_no_ledger_row(
    consumer: NotificationFactsConsumerTask,
    ledger: Any,
    sender: Any,
    facts: Any,
    event_type: str,
) -> None:
    await consumer.handle(record(facts.wire(event_type)))

    assert sender.sent == []
    assert ledger.calls == [], "not even a record() call: the ledger is untouched"


async def test_the_filter_is_by_event_type_not_by_topic(
    consumer: NotificationFactsConsumerTask, sender: Any, facts: Any
) -> None:
    """`otc.orders.facts.v1` also carries `order.saga_failed.v1`; `otc.billing.facts.v1` carries
    `credit.*` next to `invoice.issued.v1`. One topic yields an email for one and not the other."""
    for topic in ("otc.orders.facts.v1", "otc.fulfillment.facts.v1", "otc.billing.facts.v1"):
        await consumer.handle(record(facts.wire("order.saga_failed.v1"), topic))
        await consumer.handle(record(facts.wire("credit.approved.v1"), topic))
    assert sender.sent == []

    await consumer.handle(record(facts.wire("invoice.issued.v1"), "otc.orders.facts.v1"))
    assert len(sender.sent) == 1, "a notified type on an unexpected topic is still notified"


@pytest.mark.parametrize("event_type", NOTIFIED)
async def test_the_subject_carries_the_envelopes_correlation_id_not_another_envelope_id(
    consumer: NotificationFactsConsumerTask,
    sender: Any,
    facts: Any,
    event_type: str,
) -> None:
    """#8 id 58: corrupting the consumer's hand copy of `correlationId` left #8's suite green. Here
    no field is copied by hand (the whole envelope is parsed by the generated model), and the four
    ids of the fixture are all different, so a transposition would be visible."""
    event = facts.event(event_type)
    ids = {event.event_id, event.aggregate_id, event.correlation_id, event.causation_id}
    assert len(ids) == 4

    await consumer.handle(record(facts.wire(event_type)))

    [message] = sent_once(sender)
    assert f"(correlationId: {event.correlation_id})" in message.subject
    for other in ids - {event.correlation_id}:
        assert str(other) not in message.subject
        assert str(other) not in message.text_body
        assert str(other) not in message.html_body


def sent_once(sender: Any) -> list[Any]:
    assert len(sender.sent) == 1
    return list(sender.sent)


async def test_a_byte_identical_redelivery_sends_nothing_more(
    consumer: NotificationFactsConsumerTask, ledger: Any, sender: Any, facts: Any
) -> None:
    wire = facts.wire("order.placed.v1")
    await consumer.handle(record(wire))
    baseline_sent, baseline_rows = len(sender.sent), set(ledger.recorded)

    await consumer.handle(record(wire))
    await consumer.handle(record(wire))

    assert len(sender.sent) == baseline_sent == 1
    assert ledger.recorded == baseline_rows


async def test_two_different_facts_with_the_same_event_id_send_once(
    consumer: NotificationFactsConsumerTask, sender: Any, facts: Any
) -> None:
    """The key is `eventId` alone (per consumer), as the ledger's unique index says."""
    shared = UUID("0000feed-0000-4000-8000-00000000feed")
    await consumer.handle(
        record(facts.wire_from(facts.with_values("order.placed.v1", event_id=shared)))
    )
    await consumer.handle(
        record(facts.wire_from(facts.with_values("order.confirmed.v1", event_id=shared)))
    )
    assert len(sender.sent) == 1


@pytest.mark.parametrize(
    "garbage",
    [b"", b"not json", b"[]", b"{}", b'{"eventId":"x"}', b'{"eventType":"order.placed.v1"}'],
)
async def test_a_malformed_envelope_is_acknowledged_and_logged_not_retried(
    consumer: NotificationFactsConsumerTask,
    ledger: Any,
    sender: Any,
    garbage: bytes,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("ERROR"):
        await consumer.handle(record(garbage))  # returns normally: the offset commits

    assert sender.sent == []
    assert ledger.calls == []
    [logged] = [r for r in caplog.records if "malformed fact envelope" in r.message]
    assert logged.length == len(garbage)  # type: ignore[attr-defined]


async def test_a_notified_fact_with_a_poisoned_payload_raises_for_redelivery_and_leaves_no_row(
    consumer: NotificationFactsConsumerTask, ledger: Any, sender: Any, facts: Any
) -> None:
    document = facts.wire("order.placed.v1").decode().replace('"ORD-000101"', '"not-a-reference"')

    with pytest.raises(ValidationError):
        await consumer.handle(record(document.encode()))

    assert sender.sent == []
    assert ledger.calls == [], "nothing recorded: a fixed redelivery can send"


async def test_a_send_failure_propagates_to_the_subscriber_and_the_row_is_forgotten(
    consumer: NotificationFactsConsumerTask, ledger: Any, sender: Any, facts: Any
) -> None:
    sender.failures = [ConnectionError("smtp down")]
    wire = facts.wire("payment.received.v1")

    with pytest.raises(ConnectionError):
        await consumer.handle(record(wire))
    assert ledger.recorded == set()

    await consumer.handle(record(wire))  # the redelivery
    assert len(sender.sent) == 1
