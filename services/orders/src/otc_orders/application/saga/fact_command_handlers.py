"""`SagaFactCommandHandler`: ONE handler class, registered ten times (`design.md` 7.7).

It builds the `SagaFact` from the command's envelope INSIDE the processing unit (a poisoned payload
or a nil `correlationId` raises here, so the record is redelivered, not acknowledged: L23), runs
`SagaFactHandler.handle`, and ONLY WHEN the fact was processed and owed a command, strictly after
`run_once` returned (so after commit), publishes the matching dispatch-owed event through
`scope.dispatcher`. A duplicate, an ignored fact and a processed step that owed nothing publish
nothing.
"""

import logging
from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol

from otc_contracts import FACT_MODELS, WireModel, from_wire_json, to_wire_json, wire_instant
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.dispatch_events import (
    CreditRejectionRecorded,
    OrderConfirmedBySaga,
    OrderMarkedDespatched,
    OrderMarkedStockReserved,
    OrderPlacedFactRecorded,
)
from otc_orders.application.saga.fact import SagaFact
from otc_orders.application.saga.fact_commands import FactCommand
from otc_orders.application.saga.fact_handler import (
    SagaFactHandler,
    SagaFactOutcome,
    SagaFactResult,
)
from otc_orders.application.scope import OrdersScope
from otc_shared_kernel import UniqueId

log = logging.getLogger("otc_orders.saga.fact_command_handlers")


# The command each dispatch-owed event signals (and `order_sagas.py` signals): the one place the
# kind -> event pairing is written. `credit.release` is owed by no step in this feature.
class _DispatchEventFactory(Protocol):
    def __call__(self, *, order_id: UniqueId, triggering_event_id: UniqueId) -> object: ...


DISPATCH_EVENTS: Mapping[SagaCommandKind, _DispatchEventFactory] = MappingProxyType(
    {
        SagaCommandKind.STOCK_RESERVE: OrderPlacedFactRecorded,
        SagaCommandKind.CREDIT_HOLD: OrderMarkedStockReserved,
        SagaCommandKind.STOCK_RELEASE: CreditRejectionRecorded,
        SagaCommandKind.DESPATCH_CREATE: OrderConfirmedBySaga,
        SagaCommandKind.INVOICE_ISSUE: OrderMarkedDespatched,
    }
)


class FactPayloadError(ValueError):
    """The envelope was well formed but the fact's own model refused it: a processing failure."""


def build_saga_fact(command: FactCommand) -> SagaFact:
    envelope = command.envelope
    model = FACT_MODELS.get(envelope.event_type)
    if model is None:
        raise FactPayloadError(f"no model is registered for {envelope.event_type!r}")
    # Re-validated against the fact's own generated model (typed payload, strict, patterns). The
    # envelope round-trips through the one serializer; a failure is a ValueError and so a
    # redelivery.
    typed = from_wire_json(model, to_wire_json(envelope))
    payload = getattr(typed, "payload", None)
    if not isinstance(payload, WireModel):
        raise FactPayloadError(f"{envelope.event_type} carries no payload model")
    return SagaFact(
        event_id=UniqueId(envelope.event_id),
        event_type=envelope.event_type,
        correlation_id=UniqueId(envelope.correlation_id),
        occurred_at=wire_instant(envelope.occurred_at),
        payload=payload,
        topic=command.topic,
    )


class SagaFactCommandHandler:
    def __init__(self, scope: OrdersScope) -> None:
        self._scope = scope
        self._handler = SagaFactHandler(scope.required_fact_consumption())
        self._dispatcher = scope.required_dispatcher()

    async def handle(self, command: FactCommand, /) -> SagaFactResult:
        fact = build_saga_fact(command)
        result = await self._handler.handle(fact)
        if result.outcome is SagaFactOutcome.PROCESSED and result.enqueued is not None:
            event_type = DISPATCH_EVENTS[result.enqueued]
            await self._dispatcher.publish(
                event_type(order_id=fact.correlation_id, triggering_event_id=fact.event_id),
                self._scope,
            )
        return result
