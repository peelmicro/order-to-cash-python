"""`NotificationSender`: the notification port (`domain-model.md` section 6).

ONE port, several adapters (`infrastructure/notification/`): the console adapter every automated
test binds, the SMTP adapter the real host binds (Mailpit locally), and the degrading decorator
over the SMTP one. A test that bypassed this port would prove nothing about the real wiring.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    """The rendered notification, provider-neutral.

    `message_id` is set once, centrally, by `dispatch` from the fact's `eventId`
    (`<eventId>@order-to-cash`): defence in depth that makes every send attributable in the inbox,
    never the deduplication mechanism (that is the durable `processed_events` ledger).
    """

    to: str
    subject: str
    text_body: str
    html_body: str
    message_id: str | None = None


class NotificationSender(Protocol):
    async def send(self, message: NotificationMessage) -> None:
        """Deliver the message. Raises when delivery fails (the classifier says whether a retry
        could ever succeed)."""
        ...
