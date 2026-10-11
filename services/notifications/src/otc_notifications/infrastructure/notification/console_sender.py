"""`ConsoleNotificationSender`: the no-I/O adapter every automated test binds, and the default.

Logs one structured line per message: `to`, `subject` and `messageId` only, never the body (the
body can carry a business reference, `paymentReference`, that has no reason to sit in logs).
"""

import logging

from otc_notifications.application.ports.notification_sender import NotificationMessage

log = logging.getLogger("otc_notifications.notification.console")


class ConsoleNotificationSender:
    async def send(self, message: NotificationMessage) -> None:
        log.info(
            "notification (console adapter): to=%s subject=%s messageId=%s",
            message.to,
            message.subject,
            message.message_id,
            extra={"to": message.to, "subject": message.subject, "messageId": message.message_id},
        )
