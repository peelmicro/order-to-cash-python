"""Degrade to the console on a PERMANENT send failure, through the same port (#8 id 73; #7
`ad90de6`; acceptance 2). Both directions of the classification are pinned: a permanent failure
must NOT raise, a transient one MUST raise the same instance."""

import logging
from typing import Any

import pytest
from aiosmtplib import SMTPRecipientRefused, SMTPRecipientsRefused, SMTPSenderRefused

from otc_notifications.application.ports.notification_sender import NotificationMessage
from otc_notifications.infrastructure.notification.console_sender import ConsoleNotificationSender
from otc_notifications.infrastructure.notification.degrading_sender import (
    DEGRADED_EVENT,
    DegradingNotificationSender,
)

MESSAGE = NotificationMessage("to@x.example", "the subject", "body text", "<p>body</p>", "id@order")


class FakeFallback:
    def __init__(self) -> None:
        self.sent: list[NotificationMessage] = []

    async def send(self, message: NotificationMessage) -> None:
        self.sent.append(message)


async def test_a_successful_send_does_not_touch_the_fallback(sender: Any) -> None:
    fallback = FakeFallback()
    await DegradingNotificationSender(sender, fallback).send(MESSAGE)
    assert sender.sent == [MESSAGE]
    assert fallback.sent == []


async def test_a_permanent_failure_renders_through_the_fallback_and_returns_normally(
    sender: Any, caplog: pytest.LogCaptureFixture
) -> None:
    sender.failures = [SMTPSenderRefused(550, "mailbox unavailable", "no-reply@x.example")]
    fallback = FakeFallback()

    with caplog.at_level(logging.ERROR):
        await DegradingNotificationSender(sender, fallback).send(MESSAGE)  # no raise

    assert fallback.sent == [MESSAGE], "the SAME message through the same port"
    [line] = [r for r in caplog.records if r.name == "otc_notifications.notification.degrading"]
    assert line.levelno == logging.ERROR
    assert line.event == DEGRADED_EVENT == "notification.send.degraded"  # type: ignore[attr-defined]
    assert (line.to, line.subject, line.messageId) == (  # type: ignore[attr-defined]
        "to@x.example",
        "the subject",
        "id@order",
    )
    assert line.exc_info is not None
    assert "mailbox unavailable" in str(line.exc_info[1])


async def test_a_permanent_all_recipients_refusal_degrades_too(sender: Any) -> None:
    sender.failures = [
        SMTPRecipientsRefused([SMTPRecipientRefused(550, "no such user", "to@x.example")])
    ]
    fallback = FakeFallback()
    await DegradingNotificationSender(sender, fallback).send(MESSAGE)
    assert fallback.sent == [MESSAGE]


@pytest.mark.parametrize(
    "error",
    [
        SMTPSenderRefused(451, "try again later", "a@x.example"),
        ConnectionRefusedError("down"),
        TimeoutError("slow"),
        RuntimeError("unknown"),
    ],
)
async def test_a_transient_failure_is_re_raised_unchanged_and_the_fallback_is_untouched(
    sender: Any, error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    sender.failures = [error]
    fallback = FakeFallback()

    with caplog.at_level(logging.ERROR), pytest.raises(type(error)) as raised:
        await DegradingNotificationSender(sender, fallback).send(MESSAGE)

    assert raised.value is error, "the original instance, so retry and dead-letter see it as is"
    assert fallback.sent == []
    assert [r for r in caplog.records if r.name.endswith("degrading")] == [], "no degraded line"


async def test_cancellation_is_never_swallowed_as_a_failure(sender: Any) -> None:
    import asyncio

    sender.failures = [asyncio.CancelledError()]
    with pytest.raises(asyncio.CancelledError):
        await DegradingNotificationSender(sender, FakeFallback()).send(MESSAGE)


async def test_the_console_adapter_logs_to_subject_and_message_id_and_never_the_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = NotificationMessage(
        "to@x.example", "subj", "PAYMENT-REF-IN-BODY", "<p>HTML-BODY</p>", "m@o"
    )
    with caplog.at_level(logging.INFO):
        await ConsoleNotificationSender().send(secret)

    [line] = [r for r in caplog.records if r.name == "otc_notifications.notification.console"]
    assert (line.to, line.subject, line.messageId) == ("to@x.example", "subj", "m@o")  # type: ignore[attr-defined]
    assert "PAYMENT-REF-IN-BODY" not in line.getMessage()
    assert "HTML-BODY" not in line.getMessage()
