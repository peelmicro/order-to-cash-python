"""`CancelOrderCommand` and its handler: the operator's cancellation (`orders.cancel`, SA-4).

`saga.md` 4.3's generalisation table, branching on the order's status AT THE MOMENT IT IS LOCKED:

* `stock_reserved`, `credit_approved`, `confirmed`: the cancellation is ACCEPTED, not made.
  `stock.release` (reason `order_cancelled`) is enqueued in this transaction, stock FIRST in every
  case: at `stock_reserved` it is the only acquisition; at `credit_approved` / `confirmed` it is the
  contested resource, and Fulfillment decides it under one lock against the despatch already
  requested. The order stays where it is until a FACT completes the cancellation
  (`stock.released.v1` from `stock_reserved`; `credit.released.v1` from the other two, after
  `stock.released.v1` owes `credit.release`); if the despatch wins, no fact follows and the
  cancellation is overtaken.
* `placed`, or a terminal status: `Order.cancel` is the one guard for both outcomes. From `placed`
  it succeeds at once (nothing was acquired); from `despatched` onwards, or from `cancelled`, it
  raises `OrderNotCancellableError`, which propagates to the responder's error mapping.

THE RACE (#8 id 62, #7's F1). The order is loaded with `get_by_id_for_update` (SO17), the same lock
a saga step takes, so the cancel and a fact-driven step for the SAME order are serialised: whichever
takes the lock first decides what the other sees. Cancel first: a later `credit.approved.v1` finds
the accepted cancellation and issues `credit.release` only. Saga step first: the cancel finds the
order already past `stock_reserved` and plans the two-hop compensation. A plain read would let both
read the same status (PostgreSQL `READ COMMITTED` never waits on a plain SELECT).

THE NOTE. `StockReleaseRequestPayload` declares no `note`, so it is stored beside the row
(`saga_commands.operator_note`) and read back by the step that completes the cancellation
(`fact_handler`). It never travels on the wire except inside `order.cancelled.v1`.
"""

import enum
from dataclasses import dataclass

from otc_contracts import to_wire_json
from otc_cqrs import Command
from otc_orders.application.ports.saga_command_store import OwedCommand
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.command_payloads import build_operator_stock_release_payload
from otc_orders.application.saga.dispatch_events import OperatorCancelAccepted
from otc_orders.application.scope import OrdersScope
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import OrderNumber, UniqueId


class CompensationPlanned(enum.Enum):
    """What WILL be released (`asyncapi.yaml` `OrdersCancelReplyPayload.compensationPlanned`):
    present tense, unlike the `CompensationStepKind` of what WAS released."""

    STOCK_RELEASE = "stock_release"
    CREDIT_RELEASE = "credit_release"


@dataclass(frozen=True, slots=True)
class CancelOrderResult:
    order_id: UniqueId
    order_reference: OrderNumber
    status: OrderStatus
    cancellation_reason: CancellationReason | None  # set only when the order is already cancelled
    compensation_planned: tuple[CompensationPlanned, ...]  # in release order; empty if immediate


@dataclass(frozen=True, slots=True)
class CancelOrderCommand(Command[CancelOrderResult]):
    order_id: UniqueId
    note: str | None


class OrderNotFoundError(Exception):
    """`orders.cancel` named an order that does not exist."""

    def __init__(self, order_id: UniqueId) -> None:
        super().__init__(f'orderId "{order_id.value}" does not resolve to an order.')
        self.order_id = order_id


# The statuses whose cancellation is completed by facts. The order of each plan IS the release
# order: stock first, credit second (saga.md 4.3). A tuple, not a set: a transposition is a change.
COMPENSATION_PLANS: dict[OrderStatus, tuple[CompensationPlanned, ...]] = {
    OrderStatus.STOCK_RESERVED: (CompensationPlanned.STOCK_RELEASE,),
    OrderStatus.CREDIT_APPROVED: (
        CompensationPlanned.STOCK_RELEASE,
        CompensationPlanned.CREDIT_RELEASE,
    ),
    OrderStatus.CONFIRMED: (
        CompensationPlanned.STOCK_RELEASE,
        CompensationPlanned.CREDIT_RELEASE,
    ),
}


class CancelOrderCommandHandler:
    def __init__(self, scope: OrdersScope) -> None:
        self._scope = scope
        self._dispatcher = scope.required_dispatcher()

    async def handle(self, command: CancelOrderCommand, /) -> CancelOrderResult:
        scope = self._scope
        request_id = UniqueId.new()  # the cancel's own id: the release row's trigger, the cause
        accepted = False
        async with scope.unit_of_work.begin() as transaction:
            order = await transaction.orders.get_by_id_for_update(command.order_id)
            if order is None:
                raise OrderNotFoundError(command.order_id)
            plan = COMPENSATION_PLANS.get(order.status)
            if plan is not None:
                await transaction.saga_commands.enqueue(
                    OwedCommand(
                        order_id=order.id,
                        order_reference=order.order_reference.value,
                        kind=SagaCommandKind.STOCK_RELEASE,
                        payload=to_wire_json(build_operator_stock_release_payload(order)),
                        triggering_event_id=request_id,
                        operator_note=command.note,
                    )
                )
                accepted = True
                result = CancelOrderResult(
                    order_id=order.id,
                    order_reference=order.order_reference,
                    status=order.status,
                    cancellation_reason=None,
                    compensation_planned=plan,
                )
            else:
                # `placed`, or a status `Order.cancel` itself refuses: the aggregate's guard, reused
                # verbatim (no status set is written here).
                order.cancel(
                    reason=CancellationReason.OPERATOR_CANCELLED,
                    compensation_steps=(),
                    occurred_at=scope.clock.now(),
                    causation_id=request_id,
                    note=command.note,
                )
                await transaction.orders.save(order)
                result = CancelOrderResult(
                    order_id=order.id,
                    order_reference=order.order_reference,
                    status=order.status,
                    cancellation_reason=order.cancellation_reason,
                    compensation_planned=(),
                )
        # Strictly AFTER the commit: the fast path is an optimisation over the durable `pending`
        # row, which the sweeper issues if this process dies before it.
        if accepted:
            await self._dispatcher.publish(
                OperatorCancelAccepted(order_id=result.order_id, triggering_event_id=request_id),
                scope,
            )
        return result
