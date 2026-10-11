"""Which `NotificationSender` the composition root binds, and what each wraps (#8
`NotificationSenderBindingTests`: two real sibling senders swapped inside the decorator left #8's
suite green because nothing could tell WHICH sender the decorator wrapped)."""

from typing import Any

import pytest

from otc_notifications.composition import build_sender
from otc_notifications.infrastructure.notification.console_sender import ConsoleNotificationSender
from otc_notifications.infrastructure.notification.degrading_sender import (
    DegradingNotificationSender,
)
from otc_notifications.infrastructure.notification.smtp_sender import SmtpNotificationSender
from otc_notifications.infrastructure.settings import SmtpSettings


def settings(**env: str) -> SmtpSettings:
    return SmtpSettings.model_validate(env)


def test_console_is_the_default_and_is_not_wrapped() -> None:
    bound = build_sender(settings())
    assert type(bound) is ConsoleNotificationSender, "nothing to degrade from"


def test_smtp_binds_the_degrading_decorator_around_the_smtp_adapter_with_the_console_fallback() -> (
    None
):
    bound = build_sender(settings(NOTIFICATIONS_SENDER="smtp"))
    assert type(bound) is DegradingNotificationSender
    assert type(bound.inner) is SmtpNotificationSender, "the real adapter is what is wrapped"
    assert type(bound.fallback) is ConsoleNotificationSender, "and the console is what it falls to"


@pytest.mark.parametrize("sender", ["console", "smtp"])
def test_the_smtp_adapter_is_never_bound_bare(sender: str) -> None:
    bound: Any = build_sender(settings(NOTIFICATIONS_SENDER=sender))
    assert type(bound) is not SmtpNotificationSender
