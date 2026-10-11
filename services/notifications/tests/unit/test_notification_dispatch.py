"""`dispatch`: record first, send outside any transaction, forget when the send throws (R17, R18).

The port-level behaviours that make a duplicate email impossible, against an in-memory ledger and
a recording sender (the REAL ledger and a REAL SMTP server are `integration/`). Each test names the
claim; the arming table in `progress/impl_notifications_service.md` records the mutation that
fails it.
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

import pytest

from otc_notifications.application.dispatch import dispatch
from otc_notifications.application.ports.delivery_ledger import LedgerOutcome
from otc_notifications.application.ports.notification_sender import NotificationMessage
from otc_notifications.application.scope import MissingBindingError, NotificationsScope

EVENT = UUID("0000abcd-0000-4000-8000-00000000abcd")


def message(subject: str = "s") -> NotificationMessage:
    return NotificationMessage("to@x.example", subject, "text", "<p>html</p>")


def scope(ledger: Any, sender: Any) -> NotificationsScope:
    return NotificationsScope(ledger=ledger, sender=sender)


async def test_r17_the_ledger_row_is_recorded_before_the_message_is_sent(
    ledger: Any, sender: Any
) -> None:
    order: list[str] = []
    original_record = ledger.record

    async def record(event_id: UUID) -> LedgerOutcome:
        order.append("record")
        return await original_record(event_id)  # type: ignore[no-any-return]

    async def send(m: NotificationMessage) -> None:
        order.append("send")

    ledger.record = record
    sender.send = send

    outcome = await dispatch(scope(ledger, sender), EVENT, message)

    assert outcome is LedgerOutcome.RECORDED
    assert order == ["record", "send"], "record-first: a crash after the send can never be re-sent"


async def test_r18_a_duplicate_is_acknowledged_without_a_build_a_send_or_a_second_row(
    ledger: Any, sender: Any
) -> None:
    await dispatch(scope(ledger, sender), EVENT, message)
    sent_before = list(sender.sent)
    rows_before = set(ledger.recorded)

    def must_not_build() -> NotificationMessage:
        raise AssertionError("a duplicate must not even render the message")

    outcome = await dispatch(scope(ledger, sender), EVENT, must_not_build)

    assert outcome is LedgerOutcome.DUPLICATE
    assert sender.sent == sent_before, "no second email"
    assert ledger.recorded == rows_before, "no second row, none removed"
    assert [c for c in ledger.calls if c[0] == "forget"] == []


async def test_r18_two_events_with_different_ids_are_both_sent(ledger: Any, sender: Any) -> None:
    other = UUID("0000dcba-0000-4000-8000-00000000dcba")
    await dispatch(scope(ledger, sender), EVENT, lambda: message("one"))
    await dispatch(scope(ledger, sender), other, lambda: message("two"))
    assert [m.subject for m in sender.sent] == ["one", "two"]
    assert ledger.recorded == {EVENT, other}


async def test_the_message_id_is_the_event_id_at_order_to_cash_set_centrally(
    ledger: Any, sender: Any
) -> None:
    await dispatch(scope(ledger, sender), EVENT, message)
    [sent] = sender.sent
    assert sent.message_id == f"{EVENT}@order-to-cash"
    assert (sent.to, sent.subject) == ("to@x.example", "s"), "the rest of the message is untouched"


async def test_a_failed_send_forgets_the_row_and_propagates_the_original_error(
    ledger: Any, sender: Any
) -> None:
    boom = ConnectionError("smtp is down")
    sender.failures = [boom]

    with pytest.raises(ConnectionError) as raised:
        await dispatch(scope(ledger, sender), EVENT, message)

    assert raised.value is boom, "the ORIGINAL error, not a wrapper"
    assert ledger.recorded == set(), "the row is gone: the redelivery is a fresh attempt"
    assert ledger.calls == [("record", EVENT), ("forget", EVENT)]


async def test_after_a_failed_send_the_redelivery_sends_exactly_once(
    ledger: Any, sender: Any
) -> None:
    sender.failures = [ConnectionError("down")]
    with pytest.raises(ConnectionError):
        await dispatch(scope(ledger, sender), EVENT, message)

    await dispatch(scope(ledger, sender), EVENT, message)
    again = await dispatch(scope(ledger, sender), EVENT, message)

    assert len(sender.sent) == 1, "the second delivery sent; the third was a duplicate"
    assert again is LedgerOutcome.DUPLICATE


async def test_a_failing_compensation_never_masks_the_send_error_and_is_logged_with_the_ids(
    ledger: Any, sender: Any, caplog: pytest.LogCaptureFixture
) -> None:
    sender.failures = [TimeoutError("smtp timeout")]
    ledger.forget_error = RuntimeError("database unreachable")

    with caplog.at_level(logging.ERROR), pytest.raises(TimeoutError, match="smtp timeout"):
        await dispatch(scope(ledger, sender), EVENT, message)

    [record] = [r for r in caplog.records if r.name == "otc_notifications.dispatch"]
    assert record.eventId == str(EVENT)  # type: ignore[attr-defined]
    assert "TimeoutError" in record.sendError  # type: ignore[attr-defined]
    assert record.exc_info is not None
    assert record.exc_info[1] is not None
    assert "database unreachable" in str(record.exc_info[1])
    assert EVENT in ledger.recorded, "the orphaned row is what the log tells an operator to clear"


async def test_a_cancelled_send_forgets_the_row_and_cancellation_propagates(
    ledger: Any, sender: Any
) -> None:
    sender.failures = [asyncio.CancelledError()]

    with pytest.raises(asyncio.CancelledError):
        await dispatch(scope(ledger, sender), EVENT, message)

    assert ledger.recorded == set(), "a send that never completed must not leave the fact consumed"


async def test_a_render_failure_after_the_record_is_not_forgotten_by_dispatch(
    ledger: Any, sender: Any
) -> None:
    """Documented behaviour, not an endorsement: `build` runs after `record` and outside the
    compensating `try`, as in #7 and #8. A template cannot fail on a validated event; the typed
    parse happens before `dispatch`. This pins the actual behaviour so a change is deliberate."""

    def broken() -> NotificationMessage:
        raise ValueError("template bug")

    with pytest.raises(ValueError, match="template bug"):
        await dispatch(scope(ledger, sender), EVENT, broken)
    assert EVENT in ledger.recorded


def test_the_scope_refuses_a_port_bound_to_nothing(ledger: Any, sender: Any) -> None:
    with pytest.raises(MissingBindingError) as refused:
        NotificationsScope(ledger=ledger, sender=None)  # type: ignore[arg-type]
    assert refused.value.binding == "sender"
    with pytest.raises(MissingBindingError) as refused_ledger:
        NotificationsScope(ledger=None, sender=sender)  # type: ignore[arg-type]
    assert refused_ledger.value.binding == "ledger"
