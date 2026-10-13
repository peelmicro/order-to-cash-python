"""F8 (S8b): `.env.example` ships `SMTP_USER=` and `SMTP_PASSWORD=` blank. The settings must treat
them as unset so the SMTP adapter never attempts AUTH; Mailpit has no AUTH extension and refused
every send otherwise. Proven against a REAL Mailpit, with settings built as the composition builds
them (`SmtpSettings()` from the environment).

Loop scope: function.
"""

from typing import Any

from otc_notifications.application.ports.notification_sender import NotificationMessage
from otc_notifications.infrastructure.notification.smtp_sender import SmtpNotificationSender
from otc_notifications.infrastructure.settings import SenderKind, SmtpSettings


async def test_blank_smtp_credentials_deliver_one_message_to_a_real_mailpit(
    host_environment: Any, inbox: Any
) -> None:
    host_environment(SMTP_USER="", SMTP_PASSWORD="")
    settings = SmtpSettings()
    assert settings.sender is SenderKind.SMTP

    await SmtpNotificationSender(settings).send(
        NotificationMessage(
            to="acme@retailer.order-to-cash.example",
            subject="blank credentials",
            text_body="text",
            html_body="<p>html</p>",
            message_id="blank-creds@order-to-cash",
        )
    )

    assert await inbox.count() == 1, "one message reached Mailpit with blank credentials"
