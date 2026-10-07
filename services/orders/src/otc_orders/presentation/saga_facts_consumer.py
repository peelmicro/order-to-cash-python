"""`SagaFactsConsumerTask`: the ONE Kafka-transport task of the Orders service.

Design: `design.md` 5.1, 5.5.

`run(stop)` gives the subscriber a handler and returns when the subscriber does; the lifespan owns
and awaits the task. It depends on the `FactStreamSubscriber` port, never on aiokafka (the
`fact-producer-confinement` contract forbids the client in `presentation`).

`handle(message)` routes, in this order:

1. The value is not JSON, not an object, or fails `Envelope[dict[str, Any]]` (seven fields, UUID
ids, the `eventType` pattern, an aware `occurredAt`): ERROR log, then RETURN NORMALLY, so the offset
commits. It cannot be deduplicated (no trustworthy `eventId`) or parked (no `correlationId`), and
redelivery cannot fix a producer bug.
2. `eventType` is one of the four facts the orchestrator produces itself: return with no dispatch,
no transaction, no dedup row and no load (SO2).
3. `eventType` is not a catalogued fact: WARNING (distinct from malformed), return.
4. Otherwise build the fact's own `Handle<Fact>FactCommand` and `await dispatcher.send(...)`, whose
   return means the transaction committed. Whatever it raises propagates to the subscriber: no
   commit, paced redelivery (SO9). The per-fact payload validation and the `UniqueId` construction
   happen INSIDE that command's handler, so a well-formed envelope with a poisoned payload is a
   processing failure here (and dead-lettered by feature 27), not a log-and-acknowledge.

Feature 27 wraps the `dispatcher.send` call (`design.md` 9.8, item 1) and must re-run the SO9 arms
after adding the wrapper.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from otc_contracts import Envelope, from_wire_json
from otc_cqrs import Dispatcher
from otc_orders.application.ports.fact_stream import FactMessage, FactStreamSubscriber
from otc_orders.application.saga.fact_commands import FACT_COMMANDS
from otc_orders.application.saga.step_table import Skip, variants_for
from otc_orders.application.scope import OrdersScope

log = logging.getLogger("otc_orders.presentation.saga_facts_consumer")


class SagaFactsConsumerTask:
    def __init__(
        self,
        *,
        subscriber: FactStreamSubscriber,
        dispatcher: Dispatcher[OrdersScope],
        scope_factory: Callable[[], OrdersScope],
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
        if isinstance(variants_for(envelope.event_type), Skip):
            return
        command_type = FACT_COMMANDS.get(envelope.event_type)
        if command_type is None:
            log.warning(
                "unknown fact type acknowledged without processing",
                extra={
                    "topic": message.topic,
                    "partition": message.partition,
                    "offset": message.offset,
                    "eventType": envelope.event_type,
                },
            )
            return
        await self._dispatcher.send(
            command_type(envelope=envelope, topic=message.topic), self._scope_factory()
        )
