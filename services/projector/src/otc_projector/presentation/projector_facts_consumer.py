"""`ProjectorFactsConsumerTask`: the ONE Kafka-transport task of the projector.

`PR1` - `PR4`, `PR36`.

`run(stop)` gives the subscriber a handler and returns when the subscriber does; the lifespan owns
and awaits the task. It depends on the `FactStreamSubscriber` port, never on aiokafka (the
`fact-producer-confinement` contract forbids the client in `presentation`).

`handle(message)` routes, in this order. There is NO filter table: the projector acts on all
fourteen facts, so `FACT_MODELS` (through `parse_fact`) is the only table (`PR36`).

1. The value is not JSON, not an object, or fails `Envelope[dict[str, Any]]` (seven fields, UUID
   ids, the `eventType` pattern, an aware `occurredAt`; an empty value, a tombstone, lands here):
   ERROR log with topic, partition, offset and length, then RETURN NORMALLY, so the offset commits.
   It cannot be deduplicated (no trustworthy `eventId`) and redelivery cannot fix a producer bug
   (`PR3`).
2. A well-formed envelope whose `eventType` `FACT_MODELS` does not register: ERROR log naming the
   type, then return (commit): never a bare `return` (`PR4`). The envelope's lower-case pattern
   refuses `Order.Placed.v1` in step 1, so this step sees pattern-valid siblings such as
   `order.shipped.v1` or `order.placed.v2`.
3. Otherwise parse the WHOLE envelope with the fact's own generated model (no field is copied by
   hand: #8 id 58) and `await dispatcher.send(ProjectFactCommand(event=...))`. A registered type
   whose payload fails its model, or whatever the dispatcher raises, PROPAGATES to the subscriber:
   a failed attempt is retried and, after `FACT_RETRY_MAX_ATTEMPTS`, the original bytes go to
   `<topic>.dlq` and the offset commits (`R16`, `FactRetry`). Steps 1 and 2 are outside the wrapper
   (log and acknowledge); the unregistered-type branch of step 2 sits INSIDE the wrapped callable
   and returns normally, so it is never retried and never dead-lettered (`PR4`). A failing
   dead-letter publication propagates to the subscriber, which does not commit and redelivers.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from structlog.contextvars import bound_contextvars

from otc_contracts import Envelope, UnknownFactTypeError, from_wire_json, parse_fact
from otc_cqrs import Dispatcher
from otc_projector.application.messages import ProjectFactCommand
from otc_projector.application.ports.fact_stream import (
    FactMessage,
    FactProcessor,
    FactStreamSubscriber,
)
from otc_projector.application.scope import ProjectorScope

log = logging.getLogger("otc_projector.presentation.projector_facts_consumer")


class ProjectorFactsConsumerTask:
    def __init__(
        self,
        *,
        subscriber: FactStreamSubscriber,
        dispatcher: Dispatcher[ProjectorScope],
        scope_factory: Callable[[], ProjectorScope],
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
            await self._process(message, envelope.event_type)

    async def _process(self, message: FactMessage, event_type: str) -> None:
        async def work() -> None:
            try:
                event = parse_fact(message.value)
            except UnknownFactTypeError as error:
                log.error(
                    "unregistered fact type acknowledged without processing: %s",
                    error,
                    extra={
                        "topic": message.topic,
                        "partition": message.partition,
                        "offset": message.offset,
                    },
                )
                return
            # A fresh scope per attempt: nothing a failed attempt left behind is reused.
            await self._dispatcher.send(ProjectFactCommand(event=event), self._scope_factory())

        await self._retry.process(message, event_type, work)
