"""Acceptance 3 (R17, R18): idempotent by `eventId` through the durable ledger. A byte-identical
redelivery of each of the seven facts leaves the Mailpit inbox and the `processed_events` ledger
unchanged, also after a runtime restart (#7's in-memory ledger sent THREE emails for one `eventId`
and failed exactly this).

How a redelivery is proven CONSUMED (not merely not yet read): after the duplicate, a SECOND,
different fact (a new `eventId`, the same correlation id, so the same topic and partition and so
strictly after the duplicate) is published and awaited. When its email is in the inbox the duplicate
before it has been processed; the inbox then holds exactly the first and the second, and the ledger
exactly their two rows. Counts are taken against the baseline read BEFORE the redelivery, never a
bare zero.

Loop scope: function.
"""

import uuid
from typing import Any

import pytest

NOTIFIED = [
    "order.placed.v1",
    "order.confirmed.v1",
    "order.despatched.v1",
    "invoice.issued.v1",
    "payment.received.v1",
    "order.completed.v1",
    "order.cancelled.v1",
]


def message_ids(messages: list[dict[str, Any]]) -> list[str]:
    return sorted(str(m["MessageID"]) for m in messages)


@pytest.mark.parametrize("event_type", NOTIFIED)
async def test_r18_a_byte_identical_redelivery_leaves_the_inbox_and_the_ledger_unchanged(
    notifications_host_factory: Any,
    publisher: Any,
    inbox: Any,
    facts: Any,
    topic_of: Any,
    ledger_rows: Any,
    event_type: str,
) -> None:
    first = facts.event(event_type)
    second = facts.with_values(event_type, event_id=uuid.UUID(int=0xBEEF0001))
    topic = topic_of[event_type]

    async with notifications_host_factory():
        await publisher.publish(topic, first.correlation_id, facts.wire_from(first))
        await inbox.wait_for_count(1)
        baseline_inbox = await inbox.full_messages()
        baseline_rows = await ledger_rows()
        assert len(baseline_inbox) == 1
        assert len(baseline_rows) == 1

        # the redelivery: the very same bytes, twice, then a different fact as the fence
        await publisher.publish(topic, first.correlation_id, facts.wire_from(first))
        await publisher.publish(topic, first.correlation_id, facts.wire_from(first))
        await publisher.publish(topic, second.correlation_id, facts.wire_from(second))
        await inbox.wait_for_count(len(baseline_inbox) + 1)

    # read AFTER the host stopped: the definitive inbox, not a transient state seen while polling
    ids = message_ids(await inbox.full_messages())
    assert ids == sorted([f"{first.event_id}@order-to-cash", f"{second.event_id}@order-to-cash"])
    assert ids.count(f"{first.event_id}@order-to-cash") == 1, "the redelivered fact was sent once"
    rows = await ledger_rows()
    assert len(rows) == len(baseline_rows) + 1
    assert {event_id for event_id, _ in rows} == {first.event_id, second.event_id}


async def test_r18_a_redelivery_after_a_runtime_restart_within_one_process_sends_nothing_more(
    notifications_host_factory: Any,
    publisher: Any,
    inbox: Any,
    facts: Any,
    topic_of: Any,
    ledger_rows: Any,
) -> None:
    """#7's ledger was a `Set` on the heap: a restart forgot it. Two runtimes, one after the other,
    in ONE interpreter, over the same database and the same consumer group; the second is a brand
    new runtime object graph that never saw the first's memory.

    What this does NOT prove: a process-wide cache (a module-level `set`) survives a runtime
    rebuild in the same interpreter, so this test alone would pass with one (the reviewer's R19a).
    That mutation is killed by `test_delivery_ledger.py::
    test_forget_removes_exactly_the_pair_and_the_event_can_be_recorded_again` (R19b). The real
    two-process evidence is record section 11: two host PIDs (`otc_notifications.log` [2689861] and
    `otc_notifications_2.log` [2703138]) with the inbox and the ledger staying at 8 and 8."""
    group = "notifications-restart-it"
    event_type = "order.confirmed.v1"
    first = facts.event(event_type)
    fence = facts.with_values(event_type, event_id=uuid.UUID(int=0xBEEF0002))
    topic = topic_of[event_type]

    async with notifications_host_factory(NOTIFICATIONS_CONSUMER_GROUP=group):
        await publisher.publish(topic, first.correlation_id, facts.wire_from(first))
        await inbox.wait_for_count(1)
    baseline_inbox = await inbox.count()
    baseline_rows = await ledger_rows()
    assert (baseline_inbox, len(baseline_rows)) == (1, 1)

    async with notifications_host_factory(NOTIFICATIONS_CONSUMER_GROUP=group) as restarted:
        assert restarted.runtime.subscriber.ready, (
            "a brand new runtime, with no memory of the first"
        )
        await publisher.publish(topic, first.correlation_id, facts.wire_from(first))
        await publisher.publish(topic, fence.correlation_id, facts.wire_from(fence))
        await inbox.wait_for_count(baseline_inbox + 1)

    ids = message_ids(await inbox.full_messages())
    assert ids == sorted([f"{first.event_id}@order-to-cash", f"{fence.event_id}@order-to-cash"])
    assert len(await ledger_rows()) == len(baseline_rows) + 1


async def test_r17_a_fact_the_filter_refuses_leaves_no_ledger_row(
    notifications_host_factory: Any,
    publisher: Any,
    inbox: Any,
    facts: Any,
    ledger_rows: Any,
) -> None:
    """Every non-notified type on its own topic, then a notified fence: only the fence is kept."""
    plan = {
        "stock.reserved.v1": "otc.fulfillment.facts.v1",
        "stock.rejected.v1": "otc.fulfillment.facts.v1",
        "stock.released.v1": "otc.fulfillment.facts.v1",
        "credit.approved.v1": "otc.billing.facts.v1",
        "credit.rejected.v1": "otc.billing.facts.v1",
        "credit.released.v1": "otc.billing.facts.v1",
        "order.saga_failed.v1": "otc.orders.facts.v1",
    }
    fence = facts.event("order.placed.v1")
    baseline_rows = await ledger_rows()

    async with notifications_host_factory():
        for event_type, topic in plan.items():
            event = facts.event(event_type)
            await publisher.publish(topic, event.correlation_id, facts.wire_from(event))
        await publisher.publish("otc.orders.facts.v1", fence.correlation_id, facts.wire_from(fence))
        await inbox.wait_for_count(1)

    assert await inbox.count() == 1
    assert await ledger_rows() == [*baseline_rows, (fence.event_id, "notifications")]
