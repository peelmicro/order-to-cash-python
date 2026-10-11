"""`DegradingNotificationSender`: degrade to the console on a PERMANENT send failure (#8 id 73).

Ported from #7's `degrading-notification-sender.ts` (commit `ad90de6`) and #8's
`DegradingNotificationSender.cs`. It wraps the real sender and is bound ONLY when the SMTP adapter
is (a console-only binding has nothing to degrade from). On every send it delegates to the inner
sender and, only on failure, asks the classifier whether a retry could ever succeed:

* TRANSIENT: the ORIGINAL exception is re-raised unchanged. Every caller above this (`dispatch`'s
  compensating `forget`, feature 27's retry and dead-letter) behaves exactly as without the wrapper.
* PERMANENT: ONE loud, structured error line naming the cause (`event=notification.send.degraded`,
  a stable field a log alert can match), the SAME message rendered through the fallback, and a
  NORMAL return. A caller that never sees a raise never retries and never dead-letters: the fact is
  acknowledged and its ledger row stays committed, as if the send had succeeded. A fact whose
  recipient the server refuses for good would otherwise hold its partition forever.
"""

import logging

from otc_notifications.application.ports.notification_sender import (
    NotificationMessage,
    NotificationSender,
)
from otc_notifications.infrastructure.notification.send_failure_classifier import (
    SendFailure,
    classify_send_failure,
)

log = logging.getLogger("otc_notifications.notification.degrading")

DEGRADED_EVENT = "notification.send.degraded"


class DegradingNotificationSender:
    def __init__(self, inner: NotificationSender, fallback: NotificationSender) -> None:
        self._inner = inner
        self._fallback = fallback

    @property
    def inner(self) -> NotificationSender:
        """Which sender this decorator wraps (a wiring test must tell two sibling senders apart)."""
        return self._inner

    @property
    def fallback(self) -> NotificationSender:
        return self._fallback

    async def send(self, message: NotificationMessage) -> None:
        try:
            await self._inner.send(message)
        except Exception as error:
            if classify_send_failure(error) is SendFailure.TRANSIENT:
                raise
            log.error(
                "notifications: email delivery degraded - permanent send failure, will NOT retry "
                "or dead-letter; rendering to console and acknowledging the fact",
                exc_info=error,
                extra={
                    "event": DEGRADED_EVENT,
                    "to": message.to,
                    "subject": message.subject,
                    "messageId": message.message_id,
                },
            )
            await self._fallback.send(message)
