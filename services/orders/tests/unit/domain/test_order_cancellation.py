"""Cancellation (R10, invariant O6; SA-2's note; `design.md` section 7.1).

The reason-to-status pairing lists are LITERALS transcribed from Table T-1's Trigger column: the
legal pairings are asserted as well as the illegal ones, so a pairing check that refuses everything
(or nothing) fails.
"""

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum

import pytest

from otc_orders.domain.errors import (
    CancellationReasonNotApplicableError,
    CancellationReasonRequiredError,
    OrderNotCancellableError,
    UnknownCancellationReasonError,
)
from otc_orders.domain.events import OrderCancelled
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.cancellation_reason import (
    CancellationReason,
    parse_cancellation_reason,
)
from otc_orders.domain.value_objects.compensation_step import CompensationStep, CompensationStepKind
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import UniqueId

State = tuple[object, ...]

STOCK = CancellationReason.STOCK_REJECTED
CREDIT = CancellationReason.CREDIT_REJECTED
OPERATOR = CancellationReason.OPERATOR_CANCELLED
SOURCES = [
    OrderStatus.PLACED,
    OrderStatus.STOCK_RESERVED,
    OrderStatus.CREDIT_APPROVED,
    OrderStatus.CONFIRMED,
]

LEGAL_PAIRINGS = [
    (STOCK, OrderStatus.PLACED),
    (CREDIT, OrderStatus.STOCK_RESERVED),
    (OPERATOR, OrderStatus.PLACED),
    (OPERATOR, OrderStatus.STOCK_RESERVED),
    (OPERATOR, OrderStatus.CREDIT_APPROVED),
    (OPERATOR, OrderStatus.CONFIRMED),
]
ILLEGAL_PAIRINGS = [
    (STOCK, OrderStatus.STOCK_RESERVED),
    (STOCK, OrderStatus.CREDIT_APPROVED),
    (STOCK, OrderStatus.CONFIRMED),
    (CREDIT, OrderStatus.PLACED),
    (CREDIT, OrderStatus.CREDIT_APPROVED),
    (CREDIT, OrderStatus.CONFIRMED),
]


LEGAL_IDS = [f"{r.value}-from-{s.value}" for r, s in LEGAL_PAIRINGS]
ILLEGAL_IDS = [f"{r.value}-from-{s.value}" for r, s in ILLEGAL_PAIRINGS]


def _steps(
    at: Callable[[int], datetime], reason: CancellationReason
) -> tuple[CompensationStep, ...]:
    if reason is STOCK:
        return ()
    released = CompensationStep(
        step=CompensationStepKind.STOCK_RELEASED,
        event_id=UniqueId.new(),
        event_type="stock.released.v1",
        occurred_at=at(31),
        summary="Stock released",
    )
    if reason is CREDIT:
        return (released,)
    return (
        released,
        CompensationStep(
            step=CompensationStepKind.CREDIT_RELEASED,
            event_id=None,
            event_type="credit.released.v1",
            occurred_at=at(32),
        ),
    )


@pytest.mark.parametrize(("reason", "source"), LEGAL_PAIRINGS, ids=LEGAL_IDS)
def test_r10_order_requires_a_reason_from_the_closed_set_records_it_immutably_and_carries_it_on_order_cancelled_v1(  # noqa: E501
    reason: CancellationReason,
    source: OrderStatus,
    place_order: Callable[..., Order],
    walk_to: Callable[[Order, OrderStatus], None],
    at: Callable[[int], datetime],
    causation: UniqueId,
    state_of: Callable[[Order], State],
) -> None:
    order = place_order()
    walk_to(order, source)
    steps = _steps(at, reason)
    events_before = len(order.domain_events)

    order.cancel(
        reason=reason, compensation_steps=steps, occurred_at=at(40), causation_id=causation
    )

    assert order.status is OrderStatus.CANCELLED
    assert order.cancellation_reason is reason
    cancelled = order.domain_events[-1]
    assert isinstance(cancelled, OrderCancelled)
    assert len(order.domain_events) == events_before + 1
    assert cancelled.cancellation_reason is reason
    assert cancelled.compensation_steps == steps
    assert cancelled.cancelled_at == at(40)

    # Immutable: a second cancel is refused before it can overwrite anything.
    after_first = state_of(order)
    other = next(r for r in CancellationReason if r is not reason)
    with pytest.raises(OrderNotCancellableError) as second:
        order.cancel(
            reason=other, compensation_steps=(), occurred_at=at(50), causation_id=causation
        )
    assert second.value.code == "order.not_cancellable"
    assert order.cancellation_reason is reason
    assert state_of(order) == after_first


class _SneakyReason(StrEnum):
    OPERATOR_CANCELLED = "operator_cancelled"


def test_r10_order_raises_when_no_cancellation_reason_is_supplied_and_does_not_change_the_status(
    placed_order: Order,
    at: Callable[[int], datetime],
    causation: UniqueId,
    state_of: Callable[[Order], State],
) -> None:
    before = state_of(placed_order)
    with pytest.raises(CancellationReasonRequiredError) as missing:
        placed_order.cancel(
            reason=None,  # type: ignore[arg-type]  # the run-time hole an annotation cannot close
            compensation_steps=(),
            occurred_at=at(5),
            causation_id=causation,
        )
    assert missing.value.code == "order.cancellation_reason_required"
    assert state_of(placed_order) == before

    for not_a_member in ("operator_cancelled", _SneakyReason.OPERATOR_CANCELLED, 3):
        with pytest.raises(UnknownCancellationReasonError) as unknown:
            placed_order.cancel(
                reason=not_a_member,  # type: ignore[arg-type]
                compensation_steps=(),
                occurred_at=at(5),
                causation_id=causation,
            )
        assert unknown.value.code == "order.cancellation_reason_unknown"
        assert state_of(placed_order) == before
    assert placed_order.status is OrderStatus.PLACED


@pytest.mark.parametrize(("reason", "source"), ILLEGAL_PAIRINGS, ids=LEGAL_IDS)
def test_r10_order_refuses_a_cancellation_reason_table_t1_does_not_pair_with_the_current_status(
    reason: CancellationReason,
    source: OrderStatus,
    order_in: Callable[..., Order],
    at: Callable[[int], datetime],
    causation: UniqueId,
    state_of: Callable[[Order], State],
) -> None:
    order = order_in(source)
    before = state_of(order)
    with pytest.raises(CancellationReasonNotApplicableError) as raised:
        order.cancel(
            reason=reason, compensation_steps=(), occurred_at=at(5), causation_id=causation
        )
    assert raised.value.code == "order.cancellation_reason_not_applicable"
    assert state_of(order) == before


def test_r10_the_pairing_lists_are_exhaustive_over_reason_and_cancellable_source() -> None:
    every = {(r, s) for r in CancellationReason for s in SOURCES}
    assert len(every) == 12
    assert set(LEGAL_PAIRINGS) | set(ILLEGAL_PAIRINGS) == every
    assert not set(LEGAL_PAIRINGS) & set(ILLEGAL_PAIRINGS)
    assert (len(LEGAL_PAIRINGS), len(ILLEGAL_PAIRINGS)) == (6, 6)


def test_sa2_cancel_with_no_note_raises_order_cancelled_with_note_absent(
    placed_order: Order, at: Callable[[int], datetime], causation: UniqueId
) -> None:
    placed_order.cancel(
        reason=OPERATOR, compensation_steps=(), occurred_at=at(5), causation_id=causation
    )
    cancelled = placed_order.domain_events[-1]
    assert isinstance(cancelled, OrderCancelled)
    assert cancelled.note is None


def test_sa2_cancel_with_a_note_raises_order_cancelled_carrying_the_exact_note_text(
    placed_order: Order, at: Callable[[int], datetime], causation: UniqueId
) -> None:
    text = "Cliente solicitó la anulación — pedido duplicado ✓"
    placed_order.cancel(
        reason=OPERATOR,
        compensation_steps=(),
        occurred_at=at(5),
        causation_id=causation,
        note=text,
    )
    cancelled = placed_order.domain_events[-1]
    assert isinstance(cancelled, OrderCancelled)
    assert cancelled.note == text


@pytest.mark.parametrize("token", [None, "", "   "], ids=["none", "empty", "blank"])
def test_r10_parse_cancellation_reason_raises_when_the_token_is_missing(token: object) -> None:
    with pytest.raises(CancellationReasonRequiredError) as raised:
        parse_cancellation_reason(token)
    assert raised.value.code == "order.cancellation_reason_required"


@pytest.mark.parametrize(
    "token",
    [
        "Stock_Rejected",
        "cancelled",
        " stock_rejected",
        b"stock_rejected",
        _SneakyReason.OPERATOR_CANCELLED,
    ],
    ids=["capitals", "not-a-reason", "leading-space", "bytes", "str-subclass"],
)
def test_r10_parse_cancellation_reason_raises_when_the_token_is_outside_the_closed_set(
    token: object,
) -> None:
    with pytest.raises(UnknownCancellationReasonError) as raised:
        parse_cancellation_reason(token)
    assert raised.value.code == "order.cancellation_reason_unknown"
    assert repr(token) in raised.value.message
