"""`UpdateSignalPublisher`: announces that a document changed (`R55`, `PR17`).

Not a fact and not a command: two NATS core publishes with no reply subject and no responder. A
failure to publish is the caller's to log and swallow (`PR19`), never the adapter's to hide.
"""

from typing import Protocol

from otc_projector.application.ports.read_model import AppliedDocument
from otc_projector.domain.projection_delta import TimelineEntryDelta


class UpdateSignalPublisher(Protocol):
    async def publish(self, applied: AppliedDocument, entry: TimelineEntryDelta) -> None: ...


ORDER_UPDATED_SUBJECT_PREFIX = "readmodel.order.updated."
TIMELINE_APPENDED_SUBJECT_PREFIX = "readmodel.timeline.appended."


def order_updated_subject(order_id: str) -> str:
    """One channel per order, so a single-order subscriber and a whole-stream one (`readmodel.>`)
    both receive it."""
    return f"{ORDER_UPDATED_SUBJECT_PREFIX}{order_id}"


def timeline_appended_subject(order_id: str) -> str:
    return f"{TIMELINE_APPENDED_SUBJECT_PREFIX}{order_id}"
