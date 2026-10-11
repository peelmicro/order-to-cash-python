"""`SmtpNotificationSender`: the real adapter, aiosmtplib over SMTP (Mailpit locally).

Provider-neutral: nothing here is vendor-specific, a real provider is a matter of pointing
`SMTP_HOST` / `SMTP_PORT` (and the credential pair) elsewhere. aiosmtplib ships `py.typed`, so no
mypy override exists for it. One connection per message (`aiosmtplib.send` connects, sends and
disconnects): at this volume a pooled connection is a failure mode with no benefit.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import aiosmtplib

from otc_notifications.application.ports.notification_sender import NotificationMessage
from otc_notifications.infrastructure.notification.mime import build_mime_message
from otc_notifications.infrastructure.settings import SmtpSettings

type SmtpTransport = Callable[..., Awaitable[Any]]


class SmtpNotificationSender:
    def __init__(
        self, settings: SmtpSettings, *, transport: SmtpTransport = aiosmtplib.send
    ) -> None:
        self._settings = settings
        self._transport = transport

    async def send(self, message: NotificationMessage) -> None:
        settings = self._settings
        await self._transport(
            build_mime_message(message, settings.from_email),
            sender=settings.from_email,
            recipients=[message.to],
            hostname=settings.host,
            port=settings.port,
            username=settings.user,
            password=settings.password,
            start_tls=settings.start_tls,
            use_tls=False,
        )
