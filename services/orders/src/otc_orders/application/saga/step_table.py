"""The saga's step table as DATA: fourteen facts, four skips (`design.md` 6, saga.md 3.1, 4, 5).

Pure data and pure functions. It imports the domain, `otc_shared_kernel` and the generated payload
models only: no SQLAlchemy, aiokafka, nats or FastAPI.

The value for a consumed fact is a TUPLE OF VARIANTS, each with its own precondition (#7's final
shape), so feature 41 adds SA-4's variants as rows without reshaping the table. In this feature
every consumed fact has exactly one variant.

Every aggregate call is given `occurred_at=fact.occurred_at` and, where the method takes one,
`causation_id=fact.event_id`: the instant is the fact's, never the clock's, and the chain of
causation runs through the fact that caused the step (R12).

`Cancel` has no `command_after` field, so a cancel cannot owe a command: R26's "no `stock.release`"
is structural.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from otc_contracts.generated.asyncapi import Reason1, StockReleasedPayload
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.fact import SagaFact
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.compensation_step import (
    CompensationStep,
    CompensationStepKind,
)
from otc_orders.domain.value_objects.order_status import OrderStatus


@dataclass(frozen=True, slots=True)
class Skip:
    """A fact the orchestrator produces itself: acknowledged with no I/O at all (SO2)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Advance:
    precondition: OrderStatus
    apply: Callable[[Order, SagaFact], None] | None  # None: status deliberately unchanged
    command_after: SagaCommandKind | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Cancel:
    precondition: OrderStatus
    reason: Callable[[SagaFact], CancellationReason]
    compensation_steps: Callable[[SagaFact], tuple[CompensationStep, ...]]


type Variant = Advance | Cancel


def map_release_reason(fact: SagaFact) -> CancellationReason:
    """`stock.released.v1`'s own `reason` -> the order's cancellation reason (SO7)."""
    payload = fact.payload
    if not isinstance(payload, StockReleasedPayload):
        raise TypeError(f"{fact.event_type} does not carry a StockReleasedPayload")
    match payload.reason:
        case Reason1.credit_rejected:
            return CancellationReason.CREDIT_REJECTED
        case Reason1.order_cancelled:
            return CancellationReason.OPERATOR_CANCELLED
        case _:
            # A third reason added to the spec must fail loudly, never fall through to a guess.
            raise ValueError(
                f"no cancellation reason is mapped for release reason {payload.reason}"
            )


def release_steps_from(fact: SagaFact) -> tuple[CompensationStep, ...]:
    """Exactly one compensation step, built from the OBSERVED release fact (SO7)."""
    return (
        CompensationStep(
            step=CompensationStepKind.STOCK_RELEASED,
            event_id=fact.event_id,
            event_type=fact.event_type,
            occurred_at=fact.occurred_at,
            summary=None,
        ),
    )


def _reserve_stock(order: Order, fact: SagaFact) -> None:
    order.mark_stock_reserved(occurred_at=fact.occurred_at)


def _confirm(order: Order, fact: SagaFact) -> None:
    # One load, one save, ONE `order.confirmed.v1`: both edges are taken, only `confirm` raises.
    order.approve_credit(occurred_at=fact.occurred_at)
    order.confirm(occurred_at=fact.occurred_at, causation_id=fact.event_id)


def _despatch(order: Order, fact: SagaFact) -> None:
    order.mark_despatched(occurred_at=fact.occurred_at)


def _invoice(order: Order, fact: SagaFact) -> None:
    order.mark_invoiced(occurred_at=fact.occurred_at)


def _pay(order: Order, fact: SagaFact) -> None:
    order.mark_paid(occurred_at=fact.occurred_at)


def _complete(order: Order, fact: SagaFact) -> None:
    order.complete(occurred_at=fact.occurred_at, causation_id=fact.event_id)


def _stock_rejected_reason(_fact: SagaFact) -> CancellationReason:
    return CancellationReason.STOCK_REJECTED


def _no_compensation(_fact: SagaFact) -> tuple[CompensationStep, ...]:
    return ()


SAGA_STEPS: Mapping[str, Skip | tuple[Variant, ...]] = {
    "order.placed.v1": (
        Advance(
            precondition=OrderStatus.PLACED,
            apply=None,
            command_after=SagaCommandKind.STOCK_RESERVE,
        ),
    ),
    "stock.reserved.v1": (
        Advance(
            precondition=OrderStatus.PLACED,
            apply=_reserve_stock,
            command_after=SagaCommandKind.CREDIT_HOLD,
        ),
    ),
    "stock.rejected.v1": (
        Cancel(
            precondition=OrderStatus.PLACED,
            reason=_stock_rejected_reason,
            compensation_steps=_no_compensation,
        ),
    ),
    "credit.approved.v1": (
        Advance(
            precondition=OrderStatus.STOCK_RESERVED,
            apply=_confirm,
            command_after=SagaCommandKind.DESPATCH_CREATE,
        ),
    ),
    "credit.rejected.v1": (
        Advance(
            precondition=OrderStatus.STOCK_RESERVED,
            apply=None,
            command_after=SagaCommandKind.STOCK_RELEASE,
        ),
    ),
    "stock.released.v1": (
        Cancel(
            precondition=OrderStatus.STOCK_RESERVED,
            reason=map_release_reason,
            compensation_steps=release_steps_from,
        ),
    ),
    "order.despatched.v1": (
        Advance(
            precondition=OrderStatus.CONFIRMED,
            apply=_despatch,
            command_after=SagaCommandKind.INVOICE_ISSUE,
        ),
    ),
    "invoice.issued.v1": (
        Advance(precondition=OrderStatus.DESPATCHED, apply=_invoice, command_after=None),
    ),
    "payment.received.v1": (
        Advance(precondition=OrderStatus.INVOICED, apply=_pay, command_after=None),
    ),
    "credit.released.v1": (
        Advance(precondition=OrderStatus.PAID, apply=_complete, command_after=None),
    ),
    "order.confirmed.v1": Skip(),
    "order.completed.v1": Skip(),
    "order.cancelled.v1": Skip(),
    "order.saga_failed.v1": Skip(),
}


def variants_for(event_type: str) -> tuple[Variant, ...] | Skip | None:
    return SAGA_STEPS.get(event_type)


def step_for_status(event_type: str, status: OrderStatus) -> Variant | None:
    """The variant whose precondition EQUALS `status`: no ranges, no "or later" (R25)."""
    variants = SAGA_STEPS.get(event_type)
    if variants is None or isinstance(variants, Skip):
        return None
    for variant in variants:
        if variant.precondition == status:
            return variant
    return None
