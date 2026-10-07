"""`SagaFactHandler.handle(fact)`: one saga step in ONE transaction (`design.md` 7.1).

The dedup row, the aggregate change, its outbox rows, the owed-command row and the ignored-fact
record commit together or not at all (R17, SO3). The order is loaded with `get_by_id_for_update`
(SO17), never `get_by_id`, and routed by `correlation_id` alone: nothing here builds an
`OrderNumber` from inbound data (SO12). The canonical idempotent consumer is used unmodified,
through `FactConsumption`.

`enqueued` and `ignored` are closure variables set only inside `work`; `run_once` never retries
`work`, so they cannot carry a value from an aborted attempt. There is NO deadlock retry here
(outbox design 12.1, G2): a deadlock victim propagates, the offset is not committed, the redelivery
re-runs the step.
"""

import enum
import logging
from dataclasses import dataclass

from otc_contracts import to_wire_json
from otc_orders.application.ports.saga_command_store import EnqueueOutcome, OwedCommand
from otc_orders.application.ports.saga_ignored_facts import IgnoredFactMarker
from otc_orders.application.ports.unit_of_work import OrdersTransaction
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.command_payloads import build_command_payload
from otc_orders.application.saga.fact import SagaFact
from otc_orders.application.saga.fact_consumption import ConsumptionResult, FactConsumption
from otc_orders.application.saga.step_table import (
    Advance,
    Cancel,
    Skip,
    step_for_status,
    variants_for,
)
from otc_orders.domain.value_objects.order_status import OrderStatus

log = logging.getLogger("otc_orders.saga.fact_handler")


class SagaFactOutcome(enum.Enum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class SagaFactResult:
    outcome: SagaFactOutcome
    enqueued: SagaCommandKind | None


class SagaFactHandler:
    def __init__(self, consumption: FactConsumption) -> None:
        self._consumption = consumption

    async def handle(self, fact: SagaFact) -> SagaFactResult:
        variants = variants_for(fact.event_type)
        if variants is None or isinstance(variants, Skip):
            # Defensive: the consumer filters the four self-produced facts and unknown types first.
            return SagaFactResult(SagaFactOutcome.PROCESSED, None)
        expected = variants[0].precondition if len(variants) == 1 else None
        enqueued: SagaCommandKind | None = None
        ignored = False

        async def work(tx: OrdersTransaction) -> None:
            nonlocal enqueued, ignored
            order = await tx.orders.get_by_id_for_update(fact.correlation_id)
            if order is None:
                await self._ignore(tx, fact, None, expected, IgnoredFactMarker.UNKNOWN_ORDER)
                ignored = True
                return
            step = step_for_status(fact.event_type, order.status)
            if step is None:
                await self._ignore(
                    tx, fact, order.status, expected, IgnoredFactMarker.PRECONDITION_UNMET
                )
                ignored = True
                return
            match step:
                case Advance():
                    if step.apply is not None:
                        step.apply(order, fact)
                        await tx.orders.save(order)
                    if step.command_after is not None:
                        outcome = await tx.saga_commands.enqueue(
                            OwedCommand(
                                order_id=order.id,
                                order_reference=order.order_reference.value,
                                kind=step.command_after,
                                payload=to_wire_json(
                                    build_command_payload(step.command_after, order, fact)
                                ),
                                triggering_event_id=fact.event_id,
                            )
                        )
                        if outcome is EnqueueOutcome.ALREADY_OWED:
                            log.warning(
                                "saga command already owed; the existing row is re-signalled",
                                extra={
                                    "correlationId": str(fact.correlation_id),
                                    "command": step.command_after.value,
                                    "eventType": fact.event_type,
                                },
                            )
                        enqueued = step.command_after
                case Cancel():
                    order.cancel(
                        reason=step.reason(fact),
                        compensation_steps=step.compensation_steps(fact),
                        occurred_at=fact.occurred_at,
                        causation_id=fact.event_id,
                    )
                    await tx.orders.save(order)

        consumed = await self._consumption.run_once(fact.event_id.value, work)
        if consumed is ConsumptionResult.DUPLICATE:
            return SagaFactResult(SagaFactOutcome.DUPLICATE, None)
        if ignored:
            return SagaFactResult(SagaFactOutcome.IGNORED, None)
        return SagaFactResult(SagaFactOutcome.PROCESSED, enqueued)

    @staticmethod
    async def _ignore(
        tx: OrdersTransaction,
        fact: SagaFact,
        observed: OrderStatus | None,
        expected: OrderStatus | None,
        marker: IgnoredFactMarker,
    ) -> None:
        await tx.ignored_facts.record(
            event_id=fact.event_id,
            event_type=fact.event_type,
            correlation_id=fact.correlation_id,
            order_id=None if marker is IgnoredFactMarker.UNKNOWN_ORDER else fact.correlation_id,
            observed_status=observed,
            expected_status=expected,
            marker=marker,
        )
        log.warning(
            "saga fact ignored",
            extra={
                "correlationId": str(fact.correlation_id),
                "eventType": fact.event_type,
                "marker": marker.value,
                "observedStatus": observed.value if observed else None,
                "expectedStatus": expected.value if expected else None,
            },
        )
