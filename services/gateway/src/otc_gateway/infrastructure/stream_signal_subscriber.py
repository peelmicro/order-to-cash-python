"""The Gateway's subscriber of the Projector's read-model update signal (`R55`, subscriber leg).

NATS core, subscribe-only: `readmodel.order.updated.<orderId>` and `readmodel.timeline.appended.
<orderId>`, wildcarded on the last token so one subscription per subject covers every order
(`specs/projector_read_model/design.md` section 7). Core NATS keeps nothing: a subscriber that is
not
connected misses the signal, which is why the stream is a notification channel and the read model
the
source of truth (`openapi.yaml` `/orders/stream`).

ONE asyncio task for this transport (CLAUDE.md "one asyncio task class per transport"): `run` holds
both subscriptions and one `TaskGroup` of two loops, so a loop that dies takes the other with it and
the task ends. `StreamSubscriberHandle` owns that task for the lifespan: it is started and awaited
at boot, awaited on shutdown (cancellation is delivered to the task and awaited, the caller's own
cancellation is not swallowed), and `unready_reason` feeds `/health/ready`.

Ported from #7 `nats-stream-signal.adapter.ts` and #8 `NatsStreamSignalSubscriber.cs`. Like #8, the
order id is read off the SUBJECT and the payload bytes are forwarded untouched (checked to be JSON,
and to be one line: a newline inside `data:` would end the SSE frame early); a signal that fails
either check is logged and skipped, never allowed to stop the next one.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg

from otc_gateway.application.stream.hub import StreamHub

log = logging.getLogger("otc_gateway.infrastructure.stream_signal_subscriber")

ORDER_UPDATED_SUBJECT = "readmodel.order.updated.*"
TIMELINE_APPENDED_SUBJECT = "readmodel.timeline.appended.*"
ORDER_UPDATED_EVENT = "order.updated"
TIMELINE_APPENDED_EVENT = "timeline.appended"

_SUBJECT_PREFIX = {
    ORDER_UPDATED_EVENT: "readmodel.order.updated.",
    TIMELINE_APPENDED_EVENT: "readmodel.timeline.appended.",
}


def order_id_of(event_type: str, subject: str) -> UUID:
    """The trailing token of the subject, after the exact prefix of the event's own subject."""
    prefix = _SUBJECT_PREFIX[event_type]
    if not subject.startswith(prefix):
        raise ValueError(f"subject {subject!r} does not start with {prefix!r}")
    return UUID(subject.removeprefix(prefix))


def signal_text(payload: bytes) -> str:
    """The payload as SSE `data:` text: UTF-8, valid JSON, a single line."""
    text = payload.decode("utf-8")
    json.loads(text)
    if "\n" in text or "\r" in text:
        raise ValueError("the signal payload spans more than one line")
    return text


def relay(hub: StreamHub, event_type: str, subject: str, payload: bytes) -> bool:
    """One signal into the hub; False (and a warning) when it is malformed."""
    try:
        order_id = order_id_of(event_type, subject)
        text = signal_text(payload)
    except ValueError as error:  # UnicodeDecodeError and JSONDecodeError are ValueErrors
        log.warning("failed to decode a signal frame (subject=%s): %r", subject, error)
        return False
    hub.publish(event_type, order_id, text)
    return True


class StreamSubscriberDown(Exception):
    """The readiness probe's failure: the subscriber task is no longer running."""


class StreamSignalSubscriber:
    def __init__(self, connection: NatsClient, hub: StreamHub) -> None:
        self._connection = connection
        self._hub = hub

    async def run(self, subscribed: asyncio.Event) -> None:
        updated = await self._connection.subscribe(ORDER_UPDATED_SUBJECT)
        appended = await self._connection.subscribe(TIMELINE_APPENDED_SUBJECT)
        await self._connection.flush()  # the server knows both subscriptions before boot returns
        subscribed.set()
        async with asyncio.TaskGroup() as group:
            group.create_task(self._consume(updated.messages, ORDER_UPDATED_EVENT))
            group.create_task(self._consume(appended.messages, TIMELINE_APPENDED_EVENT))

    async def _consume(self, messages: AsyncIterator[Msg], event_type: str) -> None:
        async for message in messages:
            relay(self._hub, event_type, message.subject, message.data)
        raise RuntimeError(f"the {event_type} subscription ended")  # a clean end is a death


class StreamSubscriberHandle:
    """The lifespan's view of the subscriber task."""

    def __init__(self, task: asyncio.Task[None]) -> None:
        self._task = task

    def unready_reason(self) -> str | None:
        if not self._task.done():
            return None
        if self._task.cancelled():
            return "the stream signal subscriber was cancelled"
        error = self._task.exception()
        return f"the stream signal subscriber died: {error!r}"

    async def stop(self) -> None:
        """Cancel and AWAIT the task. `asyncio.wait` neither raises the task's error nor hides the
        caller's own cancellation, which a bare `suppress(CancelledError)` around `await task`
        would."""
        self._task.cancel()
        await asyncio.wait({self._task})
        if not self._task.cancelled() and (error := self._task.exception()) is not None:
            log.error("the stream signal subscriber had died before shutdown: %r", error)


async def start_stream_subscriber(
    connection: NatsClient, hub: StreamHub, *, subscribe_seconds: float
) -> StreamSubscriberHandle:
    """Start the task and return once both subscriptions are registered with the server, or raise
    the task's own error, or `TimeoutError` after `subscribe_seconds`."""
    subscribed = asyncio.Event()
    task = asyncio.create_task(
        StreamSignalSubscriber(connection, hub).run(subscribed), name="gateway-stream-signal"
    )
    handle = StreamSubscriberHandle(task)
    waiter = asyncio.create_task(subscribed.wait())
    try:
        async with asyncio.timeout(subscribe_seconds):
            await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if not subscribed.is_set():
            task.result()  # raises the task's own error
            raise RuntimeError("the stream signal subscriber ended before subscribing")
    except BaseException:
        await handle.stop()
        raise
    finally:
        waiter.cancel()
        await asyncio.wait({waiter})
    return handle
