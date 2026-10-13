"""`NotificationFactsConsumerTask`: the ONE Kafka-transport task of the Notifications service.

`run(stop)` gives the subscriber a handler and returns when the subscriber does; the lifespan owns
and awaits the task. It depends on the `FactStreamSubscriber` port, never on aiokafka (the
`fact-producer-confinement` contract forbids the client in `presentation`).

`handle(message)` routes, in this order:

1. The value is not JSON, not an object, or fails `Envelope[dict[str, Any]]` (seven fields, UUID
   ids, the `eventType` pattern, an aware `occurredAt`): ERROR log, then RETURN NORMALLY, so the
   offset commits. It cannot be deduplicated (no trustworthy `eventId`) and redelivery cannot fix a
   producer bug.
2. `eventType` is not a key of `NOTIFIED_FACTS` (the `stock.*` and `credit.*` facts, the diagnostic
   `order.saga_failed.v1`, any future type): return, with no ledger row, no render and no send.
3. Otherwise parse the WHOLE envelope with the fact's own generated model (no field is copied by
   hand: #8 id 58) and `await dispatcher.send(command(event=...))`, whose return means the send
   happened or was a duplicate. Whatever it raises, the poisoned payload included, propagates to
   `FactRetry`: a failed attempt is retried (a TRANSIENT send failure is re-raised by the sender
   decorator, and `dispatch` forgets its ledger row each time, so every attempt genuinely sends
   again) and, after `FACT_RETRY_MAX_ATTEMPTS`, the original bytes go to `<topic>.dlq` and the
   offset commits (`R16`). A PERMANENT send failure never reaches the wrapper: the degrading sender
   renders it to the console and returns. A failing dead-letter publication propagates to the
   subscriber, which does not commit and redelivers. Steps 1 and 2 are outside the wrapper.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from structlog.contextvars import bound_contextvars

from otc_contracts import Envelope, from_wire_json
from otc_cqrs import Dispatcher
from otc_notifications.application.notified_facts import NOTIFIED_FACTS
from otc_notifications.application.ports.fact_stream import (
    FactMessage,
    FactProcessor,
    FactStreamSubscriber,
)
from otc_notifications.application.scope import NotificationsScope

log = logging.getLogger("otc_notifications.presentation.notification_facts_consumer")


class NotificationFactsConsumerTask:
    def __init__(
        self,
        *,
        subscriber: FactStreamSubscriber,
        dispatcher: Dispatcher[NotificationsScope],
        scope_factory: Callable[[], NotificationsScope],
        retry: FactProcessor,
    ) -> None:
        self._subscriber = subscriber
        self._dispatcher = dispatcher
        self._scope_factory = scope_factory
        self._retry = retry

    async def run(self, stop: asyncio.Event) -> None:
        await self._subscriber.run(self.handle, stop)

    async def handle(self, message: FactMessage) -> None:
        try:
            envelope = from_wire_json(Envelope[dict[str, Any]], message.value)
        except ValueError:
            log.exception(
                "malformed fact envelope acknowledged without processing",
                extra={
                    "topic": message.topic,
                    "partition": message.partition,
                    "offset": message.offset,
                    "length": len(message.value),
                },
            )
            return
        with bound_contextvars(correlationId=str(envelope.correlation_id)):
            await self._process(message, envelope)

    async def _process(self, message: FactMessage, envelope: Envelope[dict[str, Any]]) -> None:
        notified = NOTIFIED_FACTS.get(envelope.event_type)
        if notified is None:
            return

        async def work() -> None:
            event = from_wire_json(notified.event_model, message.value)
            # A fresh scope per attempt: nothing a failed attempt left behind is reused.
            await self._dispatcher.send(notified.command(event=event), self._scope_factory())

        await self._retry.process(message, envelope.event_type, work)
