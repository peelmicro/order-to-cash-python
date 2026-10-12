# ruff: noqa: E501 - test names are sentences naming the case, as in the integration suite
"""The saga's step table: every fact against every status (R19-R28, SO2, SO7).

The expected outcome of every cell is a LITERAL transcribed from `specs/shared/saga.md` 3.1 / 4 / 5,
never read from `SAGA_STEPS`: fourteen facts x nine statuses = 126 cells. A cell whose status is not
the fact's precondition expects `None` (R25: equality, no ranges, no "or later"). A cell that is the
precondition expects the status the step ends in, the domain events it raises and the command it
owes.
"""

from collections.abc import Callable
from typing import Any

import pytest

from otc_contracts import FACT_MODELS
from otc_contracts.generated.asyncapi import Reason1, Reason3
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.fact import SagaFact
from otc_orders.application.saga.step_table import (
    SAGA_STEPS,
    Advance,
    Cancel,
    Skip,
    map_credit_release_reason,
    map_release_reason,
    release_steps_from,
    step_for_status,
    stock_then_credit_release_steps,
    variants_for,
)
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.compensation_step import CompensationStepKind
from otc_orders.domain.value_objects.order_status import OrderStatus

STATUSES = {status.value: status for status in OrderStatus}

# fact -> {status at which it applies: (status after, events raised, command owed)}. Ten facts are
# consumed; eight apply at exactly one status, `stock.released.v1` and `credit.released.v1` at three
# (feature 41, saga.md 4.3 and 5).
CONSUMED: dict[str, dict[str, tuple[str, tuple[str, ...], str | None]]] = {
    "order.placed.v1": {"placed": ("placed", (), "stock.reserve")},  # R19
    "stock.reserved.v1": {"placed": ("stock_reserved", (), "credit.hold")},  # R20
    "stock.rejected.v1": {"placed": ("cancelled", ("order.cancelled.v1",), None)},  # R26
    "credit.approved.v1": {  # R21
        "stock_reserved": ("confirmed", ("order.confirmed.v1",), "despatch.create")
    },
    "credit.rejected.v1": {"stock_reserved": ("stock_reserved", (), "stock.release")},  # R27
    "stock.released.v1": {
        "stock_reserved": ("cancelled", ("order.cancelled.v1",), None),  # R28
        # SA-4: the release won the race; the cancellation completes on credit.released.v1
        "credit_approved": ("credit_approved", (), "credit.release"),
        "confirmed": ("confirmed", (), "credit.release"),
    },
    "order.despatched.v1": {"confirmed": ("despatched", (), "invoice.issue")},  # R22
    "invoice.issued.v1": {"despatched": ("invoiced", (), None)},  # R23
    "payment.received.v1": {"invoiced": ("paid", (), None)},  # R24 (first half)
    "credit.released.v1": {
        "paid": ("completed", ("order.completed.v1",), None),  # R24
        # SA-4: the credit release completes an operator cancellation
        "credit_approved": ("cancelled", ("order.cancelled.v1",), None),
        "confirmed": ("cancelled", ("order.cancelled.v1",), None),
    },
}
SELF_PRODUCED = (
    "order.confirmed.v1",
    "order.completed.v1",
    "order.cancelled.v1",
    "order.saga_failed.v1",
)
ALL_FACTS = (*CONSUMED, *SELF_PRODUCED)


def applied(order: Order, fact: SagaFact) -> tuple[str, tuple[str, ...], str | None]:
    """Run the table's step for `fact` against `order`; what happened, as plain tokens."""
    step = step_for_status(fact.event_type, order.status)
    assert step is not None
    owed: str | None = None
    match step:
        case Advance():
            if step.apply is not None:
                step.apply(order, fact)
            owed = step.command_after.value if step.command_after is not None else None
        case Cancel():
            order.cancel(
                reason=step.reason(fact),
                compensation_steps=step.compensation_steps(fact),
                occurred_at=fact.occurred_at,
                causation_id=fact.event_id,
            )
    events = tuple(type(event).EVENT_TYPE for event in order.domain_events)  # type: ignore[attr-defined]
    return order.status.value, events, owed


@pytest.mark.parametrize("status", list(OrderStatus), ids=lambda s: s.value)
@pytest.mark.parametrize("event_type", ALL_FACTS)
def test_every_fact_against_every_status_does_what_saga_md_says_and_nothing_elsewhere(
    event_type: str,
    status: OrderStatus,
    order_in: Callable[..., Order],
    make_fact: Callable[..., SagaFact],
) -> None:
    # `credit.released.v1` completes an operator cancellation from `credit_approved` / `confirmed`
    # (reason `order_cancelled`); from `paid` it is the payment's (`invoice_paid`, the default).
    fact = make_fact(
        event_type,
        credit_release_reason=(
            Reason3.invoice_paid if status is OrderStatus.PAID else Reason3.order_cancelled
        ),
    )
    step = step_for_status(event_type, status)
    expected = CONSUMED.get(event_type, {}).get(status.value)
    if expected is None:
        assert step is None, f"{event_type} must do nothing at {status.value}, got {step}"
        return
    assert step is not None, f"{event_type} must apply at {status.value}"
    order = order_in(status)
    assert applied(order, fact) == expected, f"{event_type} at {status.value}"


def test_the_table_has_fourteen_rows_and_a_cell_for_each_of_the_126_pairs() -> None:
    cells = [(f, s) for f in ALL_FACTS for s in OrderStatus]
    assert len(ALL_FACTS) == 14
    assert len(cells) == 126
    assert set(SAGA_STEPS) == set(ALL_FACTS)


def test_so2_the_four_self_produced_facts_map_to_skip() -> None:
    skips = {event_type for event_type, value in SAGA_STEPS.items() if isinstance(value, Skip)}
    consumed = {
        event_type for event_type, value in SAGA_STEPS.items() if not isinstance(value, Skip)
    }

    assert skips == {
        "order.confirmed.v1",
        "order.completed.v1",
        "order.cancelled.v1",
        "order.saga_failed.v1",
    }
    assert consumed == {
        "order.placed.v1",
        "stock.reserved.v1",
        "stock.rejected.v1",
        "stock.released.v1",
        "credit.approved.v1",
        "credit.rejected.v1",
        "order.despatched.v1",
        "invoice.issued.v1",
        "payment.received.v1",
        "credit.released.v1",
    }
    assert skips | consumed == set(FACT_MODELS), (
        "every catalogued fact is either skipped or consumed"
    )
    for event_type in skips:
        assert step_for_status(event_type, OrderStatus.PLACED) is None


def test_variants_for_distinguishes_a_skip_a_variant_tuple_and_an_unknown_type() -> None:
    assert isinstance(variants_for("order.completed.v1"), Skip)
    variants = variants_for("stock.reserved.v1")
    assert isinstance(variants, tuple)
    assert len(variants) == 1
    assert variants_for("not.a.fact.v1") is None
    assert step_for_status("not.a.fact.v1", OrderStatus.PLACED) is None


def test_r21_performs_both_edges_and_raises_exactly_one_order_confirmed(
    order_in: Callable[..., Order],
    make_fact: Callable[..., SagaFact],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visited: list[OrderStatus] = []
    original: Any = Order._transition_to

    def recording(self: Order, target: OrderStatus, **kwargs: Any) -> None:
        visited.append(target)
        original(self, target, **kwargs)

    monkeypatch.setattr(Order, "_transition_to", recording)
    fact = make_fact("credit.approved.v1")
    order = order_in(OrderStatus.STOCK_RESERVED)

    status, events, owed = applied(order, fact)

    assert visited == [OrderStatus.CREDIT_APPROVED, OrderStatus.CONFIRMED], (
        "the intermediate credit_approved edge must be taken, then confirmed"
    )
    assert (status, events, owed) == ("confirmed", ("order.confirmed.v1",), "despatch.create")
    [confirmed] = order.domain_events
    assert confirmed.causation_id == fact.event_id, "R12: caused by the fact, not by the order"  # type: ignore[attr-defined]
    assert confirmed.occurred_at == fact.occurred_at  # type: ignore[attr-defined]


def test_r23_owes_nothing_after_the_invoice_is_issued(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    fact = make_fact("invoice.issued.v1")
    step = step_for_status("invoice.issued.v1", OrderStatus.DESPATCHED)
    assert isinstance(step, Advance)
    assert step.command_after is None
    assert applied(order_in(OrderStatus.DESPATCHED), fact) == ("invoiced", (), None)


def test_r26_cancels_with_empty_compensation_steps_and_owes_nothing(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    fact = make_fact("stock.rejected.v1")
    step = step_for_status("stock.rejected.v1", OrderStatus.PLACED)
    assert isinstance(step, Cancel)
    assert step.compensation_steps(fact) == ()
    assert step.reason(fact) is CancellationReason.STOCK_REJECTED
    assert not hasattr(step, "command_after"), "a Cancel cannot owe a command: no such field"
    order = order_in(OrderStatus.PLACED)
    applied(order, fact)
    [cancelled] = order.domain_events
    assert cancelled.compensation_steps == ()  # type: ignore[attr-defined]
    assert cancelled.causation_id == fact.event_id  # type: ignore[attr-defined]


def test_r27_leaves_the_status_unchanged_and_owes_stock_release(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    step = step_for_status("credit.rejected.v1", OrderStatus.STOCK_RESERVED)
    assert isinstance(step, Advance)
    assert step.apply is None
    assert step.command_after is SagaCommandKind.STOCK_RELEASE
    order = order_in(OrderStatus.STOCK_RESERVED)
    assert applied(order, make_fact("credit.rejected.v1")) == (
        "stock_reserved",
        (),
        "stock.release",
    )


def test_so7_maps_both_release_reasons_and_builds_the_step_from_the_observed_fact(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    credit_fact = make_fact("stock.released.v1", release_reason=Reason1.credit_rejected)
    operator_fact = make_fact("stock.released.v1", release_reason=Reason1.order_cancelled)

    assert map_release_reason(credit_fact) is CancellationReason.CREDIT_REJECTED
    assert map_release_reason(operator_fact) is CancellationReason.OPERATOR_CANCELLED

    [step] = release_steps_from(credit_fact)
    assert step.step is CompensationStepKind.STOCK_RELEASED
    assert step.event_id == credit_fact.event_id
    assert step.event_id != credit_fact.correlation_id, "built from the fact, not the order"
    assert step.event_type == credit_fact.event_type == "stock.released.v1"
    assert step.occurred_at == credit_fact.occurred_at
    assert step.summary is None, "gate point G2: #8's value"
    assert len(release_steps_from(credit_fact)) == 1

    order = order_in(OrderStatus.STOCK_RESERVED)
    applied(order, credit_fact)
    [cancelled] = order.domain_events
    assert cancelled.cancellation_reason is CancellationReason.CREDIT_REJECTED  # type: ignore[attr-defined]
    assert cancelled.compensation_steps == (step,)  # type: ignore[attr-defined]
    assert cancelled.causation_id == credit_fact.event_id  # type: ignore[attr-defined]


def test_a_release_whose_reason_is_not_mapped_fails_loudly(
    make_fact: Callable[..., SagaFact],
) -> None:
    fact = make_fact("stock.released.v1")
    object.__setattr__(fact.payload, "reason", "a_third_reason")
    with pytest.raises(ValueError, match="a_third_reason"):
        map_release_reason(fact)


def test_a_release_step_from_a_non_release_payload_is_a_type_error(
    make_fact: Callable[..., SagaFact],
) -> None:
    with pytest.raises(TypeError):
        map_release_reason(make_fact("credit.rejected.v1"))


# ----------------------------------------------------------------- feature 41: SA-4's variants


def test_the_two_released_facts_have_exactly_three_variants_with_these_preconditions_in_this_order() -> (
    None
):
    stock_variants = variants_for("stock.released.v1")
    credit_variants = variants_for("credit.released.v1")

    assert isinstance(stock_variants, tuple)
    assert isinstance(credit_variants, tuple)
    assert [(type(v), v.precondition) for v in stock_variants] == [
        (Cancel, OrderStatus.STOCK_RESERVED),
        (Advance, OrderStatus.CREDIT_APPROVED),
        (Advance, OrderStatus.CONFIRMED),
    ]
    assert [(type(v), v.precondition) for v in credit_variants] == [
        (Advance, OrderStatus.PAID),
        (Cancel, OrderStatus.CREDIT_APPROVED),
        (Cancel, OrderStatus.CONFIRMED),
    ]
    one_variant = {
        event_type
        for event_type, value in SAGA_STEPS.items()
        if isinstance(value, tuple) and len(value) == 1
    }
    assert len(one_variant) == 8, "every other consumed fact keeps exactly one variant"


@pytest.mark.parametrize("status", [OrderStatus.CREDIT_APPROVED, OrderStatus.CONFIRMED])
def test_stock_released_at_credit_approved_or_confirmed_changes_no_status_and_owes_credit_release(
    status: OrderStatus, order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    step = step_for_status("stock.released.v1", status)
    assert isinstance(step, Advance)
    assert step.apply is None
    assert step.command_after is SagaCommandKind.CREDIT_RELEASE
    order = order_in(status)
    fact = make_fact("stock.released.v1", release_reason=Reason1.order_cancelled)

    assert applied(order, fact) == (status.value, (), "credit.release")


def test_the_credit_release_cancel_names_stock_then_credit_built_from_the_observed_fact(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    fact = make_fact("credit.released.v1", credit_release_reason=Reason3.order_cancelled)

    first, second = stock_then_credit_release_steps(fact)

    assert (first.step, second.step) == (
        CompensationStepKind.STOCK_RELEASED,
        CompensationStepKind.CREDIT_RELEASED,
    ), "stock first: the contested resource (saga.md 4.3)"
    assert first.event_id is None, "no state survives from the earlier stock.released.v1"
    assert first.event_type == "stock.released.v1"
    assert first.summary is not None
    assert "order_cancelled" in first.summary
    assert second.event_id == fact.event_id
    assert second.event_type == "credit.released.v1"
    assert second.summary is None
    assert first.occurred_at == second.occurred_at == fact.occurred_at
    assert len(stock_then_credit_release_steps(fact)) == 2


@pytest.mark.parametrize("status", [OrderStatus.CREDIT_APPROVED, OrderStatus.CONFIRMED])
def test_credit_released_with_order_cancelled_cancels_with_operator_cancelled_caused_by_the_fact(
    status: OrderStatus, order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    fact = make_fact("credit.released.v1", credit_release_reason=Reason3.order_cancelled)
    order = order_in(status)

    assert applied(order, fact) == ("cancelled", ("order.cancelled.v1",), None)

    [cancelled] = order.domain_events
    assert cancelled.cancellation_reason is CancellationReason.OPERATOR_CANCELLED  # type: ignore[attr-defined]
    assert cancelled.causation_id == fact.event_id  # type: ignore[attr-defined]
    assert cancelled.occurred_at == fact.occurred_at  # type: ignore[attr-defined]
    assert cancelled.compensation_steps == stock_then_credit_release_steps(fact)  # type: ignore[attr-defined]


def test_a_credit_release_reason_that_does_not_complete_a_cancellation_fails_loudly(
    make_fact: Callable[..., SagaFact],
) -> None:
    paid = make_fact("credit.released.v1", credit_release_reason=Reason3.invoice_paid)

    with pytest.raises(ValueError, match="invoice_paid"):
        map_credit_release_reason(paid)
    assert (
        map_credit_release_reason(
            make_fact("credit.released.v1", credit_release_reason=Reason3.order_cancelled)
        )
        is CancellationReason.OPERATOR_CANCELLED
    )


def test_a_credit_release_step_from_a_non_credit_release_payload_is_a_type_error(
    make_fact: Callable[..., SagaFact],
) -> None:
    with pytest.raises(TypeError):
        map_credit_release_reason(make_fact("stock.released.v1"))
