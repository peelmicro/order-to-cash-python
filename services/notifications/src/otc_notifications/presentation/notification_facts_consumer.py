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
   the subscriber: no commit, paced redelivery (dead-lettered by feature 27).
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from otc_contracts import Envelope, from_wire_json
from otc_cqrs import Dispatcher
from otc_notifications.application.notified_facts import NOTIFIED_FACTS
from otc_notifications.application.ports.fact_stream import FactMessage, FactStreamSubscriber
from otc_notifications.application.scope import NotificationsScope

log = logging.getLogger("otc_notifications.presentation.notification_facts_consumer")


class NotificationFactsConsumerTask:
    def __init__(
        self,
        *,
        subscriber: FactStreamSubscriber,
        dispatcher: Dispatcher[NotificationsScope],
        scope_factory: Callable[[], NotificationsScope],
    ) -> None:
        self._subscriber = subscriber
        self._dispatcher = dispatcher
        self._scope_factory = scope_factory

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
        notified = NOTIFIED_FACTS.get(envelope.event_type)
        if notified is None:
            return
        event = from_wire_json(notified.event_model, message.value)
        await self._dispatcher.send(notified.command(event=event), self._scope_factory())
