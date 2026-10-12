"""`SagaFactHandler.handle(fact)`: one saga step in ONE transaction (`design.md` 7.1).

The dedup row, the aggregate change, its outbox rows, the owed-command row and the ignored-fact
record commit together or not at all (R17, SO3). The order is loaded with `get_by_id_for_update`
(SO17), never `get_by_id`, and routed by `correlation_id` alone: nothing here builds an
`OrderNumber` from inbound data (SO12). The canonical idempotent consumer is used unmodified,
through `FactConsumption`.

Two branches belong to feature 41 (SA-4, saga.md 4.3): a `Cancel` that resolves to
`operator_cancelled` carries the operator's note (read from the accepted cancellation the cancel
enqueued, never from the fact), and a LATE `credit.approved.v1` for an order whose operator
cancellation was accepted is routed BEFORE the generic dispatch, because the generic one would
confirm the order and request a despatch.

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
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
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


# The one fact that needs a check BEFORE the generic status dispatch (saga.md 4.3, "A credit
# approval that arrives after the cancellation").
LATE_APPROVAL_EVENT_TYPE = "credit.approved.v1"

# The second late arrival (SA-8, saga.md 4.3, "A stock reservation that arrives after the
# cancellation"). A SIBLING branch, not a generalisation of the one above: the approval's late
# shapes include `stock_reserved` with the operator's release under way, the reservation's only
# one is `cancelled` with `operator_cancelled` (a `stock_reserved` order already holds its stock),
# and the two emit different commands for different resources.
LATE_RESERVATION_EVENT_TYPE = "stock.reserved.v1"


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
            if fact.event_type == LATE_APPROVAL_EVENT_TYPE and await self._is_late_approval(
                tx, order
            ):
                # The hold was acquired, so it is unwound: `credit.release` and NOTHING else (no
                # transition, no `order.confirmed.v1`, no `despatch.create`).
                enqueued = await self._enqueue(tx, order, SagaCommandKind.CREDIT_RELEASE, fact)
                return
            if fact.event_type == LATE_RESERVATION_EVENT_TYPE and self._is_late_reservation(order):
                # The reservation was made, so it is unwound: `stock.release` (reason
                # `order_cancelled`) and NOTHING else (no transition, no `credit.hold`). The
                # (order, command) ledger makes a re-issue a no-op (R34, F5).
                enqueued = await self._enqueue(tx, order, SagaCommandKind.STOCK_RELEASE, fact)
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
                        enqueued = await self._enqueue(tx, order, step.command_after, fact)
                case Cancel():
                    reason = step.reason(fact)
                    note: str | None = None
                    if reason is CancellationReason.OPERATOR_CANCELLED:
                        accepted = await tx.saga_commands.find_accepted_operator_cancel(order.id)
                        note = None if accepted is None else accepted.note
                    order.cancel(
                        reason=reason,
                        compensation_steps=step.compensation_steps(fact),
                        occurred_at=fact.occurred_at,
                        causation_id=fact.event_id,
                        note=note,
                    )
                    await tx.orders.save(order)

        consumed = await self._consumption.run_once(fact.event_id.value, work)
        if consumed is ConsumptionResult.DUPLICATE:
            return SagaFactResult(SagaFactOutcome.DUPLICATE, None)
        if ignored:
            return SagaFactResult(SagaFactOutcome.IGNORED, None)
        return SagaFactResult(SagaFactOutcome.PROCESSED, enqueued)

    @staticmethod
    async def _is_late_approval(tx: OrdersTransaction, order: Order) -> bool:
        """An operator cancellation was accepted and this approval is for the hold issued before
        it: the order is still `stock_reserved` with the accepted cancellation's release under way,
        or already `cancelled` with reason `operator_cancelled`. A cancellation the saga decided
        (`stock_rejected`, `credit_rejected`) is NOT one, and neither is any other status."""
        if order.status is OrderStatus.CANCELLED:
            return order.cancellation_reason is CancellationReason.OPERATOR_CANCELLED
        if order.status is OrderStatus.STOCK_RESERVED:
            return await tx.saga_commands.find_accepted_operator_cancel(order.id) is not None
        return False

    @staticmethod
    def _is_late_reservation(order: Order) -> bool:
        """The order is `cancelled` with reason `operator_cancelled`. A cancellation the saga
        decided (`stock_rejected`, `credit_rejected`) is NOT one: a rejection means nothing was
        reserved (R26, F3), and the others hold no reservation to unwind."""
        return (
            order.status is OrderStatus.CANCELLED
            and order.cancellation_reason is CancellationReason.OPERATOR_CANCELLED
        )

    @staticmethod
    async def _enqueue(
        tx: OrdersTransaction, order: Order, kind: SagaCommandKind, fact: SagaFact
    ) -> SagaCommandKind:
        outcome = await tx.saga_commands.enqueue(
            OwedCommand(
                order_id=order.id,
                order_reference=order.order_reference.value,
                kind=kind,
                payload=to_wire_json(build_command_payload(kind, order, fact)),
                triggering_event_id=fact.event_id,
            )
        )
        if outcome is EnqueueOutcome.ALREADY_OWED:
            log.warning(
                "saga command already owed; the existing row is re-signalled",
                extra={
                    "correlationId": str(fact.correlation_id),
                    "command": kind.value,
                    "eventType": fact.event_type,
                },
            )
        return kind

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
