"""Acceptance 2, against a REAL SMTP server: degrade on a PERMANENT send failure, retry on a
TRANSIENT one (#8 id 73; #7 `ad90de6`). Mailpit's chaos API forces a genuine `550` (permanent) and
a genuine `451` (transient) answer to MAIL FROM, so the classification is proven against what
aiosmtplib really raises, not against constructed exceptions (those are the unit tests).

* 550: the fact is acknowledged. The degraded log line appears once, the inbox stays empty, the
  ledger row STAYS (the fact is consumed), and the next fact is processed: the partition is not
  held and nothing is retried.
* 451: the send fails, the ledger row is forgotten, the offset is not committed, and the paced
  redelivery sends the email exactly once after the fault is lifted.

Loop scope: function.
"""

import logging
import uuid
from typing import Any

import pytest


async def test_a_permanent_550_degrades_to_the_console_and_the_fact_is_acknowledged(
    notifications_host_factory: Any,
    publisher: Any,
    inbox: Any,
    facts: Any,
    ledger_rows: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    refused = facts.event("order.completed.v1")
    next_fact = facts.with_values("order.completed.v1", event_id=uuid.UUID(int=0xBEEF0003))
    topic = "otc.orders.facts.v1"
    await inbox.set_chaos(Sender=(550, 100))

    with caplog.at_level(logging.INFO):
        async with notifications_host_factory():
            await publisher.publish(topic, refused.correlation_id, facts.wire_from(refused))
            await _wait_for_log(caplog, "notification.send.degraded")
            await inbox.clear_chaos()
            await publisher.publish(topic, next_fact.correlation_id, facts.wire_from(next_fact))
            await inbox.wait_for_count(1)

    delivered = await inbox.full_messages()
    assert len(delivered) == 1, (
        f"the refused fact is not retried: the inbox holds {len(delivered)} messages, not 1"
    )
    [only] = delivered
    assert only["MessageID"] == f"{next_fact.event_id}@order-to-cash", (
        "the refused fact is not retried"
    )
    degraded = [
        r for r in caplog.records if getattr(r, "event", None) == "notification.send.degraded"
    ]
    assert len(degraded) == 1, "ONE loud line for the one refused fact"
    assert degraded[0].messageId == f"{refused.event_id}@order-to-cash"  # type: ignore[attr-defined]
    console = [r for r in caplog.records if r.name == "otc_notifications.notification.console"]
    assert [r.messageId for r in console] == [  # type: ignore[attr-defined]
        f"{refused.event_id}@order-to-cash"
    ], "rendered once"
    assert {event_id for event_id, _ in await ledger_rows()} == {
        refused.event_id,
        next_fact.event_id,
    }


async def test_a_transient_451_is_retried_and_the_email_is_sent_exactly_once_after_recovery(
    notifications_host_factory: Any,
    publisher: Any,
    inbox: Any,
    facts: Any,
    ledger_rows: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = facts.event("order.placed.v1")
    await inbox.set_chaos(Sender=(451, 100))

    with caplog.at_level(logging.INFO):
        async with notifications_host_factory():
            await publisher.publish(
                "otc.orders.facts.v1", event.correlation_id, facts.wire_from(event)
            )
            await _wait_for_log(caplog, "fact handler failed")
            assert await inbox.count() == 0, "nothing was delivered while the server answered 451"
            assert await ledger_rows() == [], "and the ledger row was forgotten: the retry is fresh"
            await inbox.clear_chaos()
            [delivered] = await inbox.wait_for_count(1)

    message = await inbox.message(delivered["ID"])
    assert message["MessageID"] == f"{event.event_id}@order-to-cash"
    degraded = [
        r for r in caplog.records if getattr(r, "event", None) == "notification.send.degraded"
    ]
    assert degraded == [], "a transient failure never degrades"
    assert await ledger_rows() == [(event.event_id, "notifications")]


async def _wait_for_log(caplog: pytest.LogCaptureFixture, fragment: str) -> None:
    import asyncio
    import time

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(
            fragment in r.getMessage() or getattr(r, "event", None) == fragment
            for r in caplog.records
        ):
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"no log record containing {fragment!r} within 30 s")
