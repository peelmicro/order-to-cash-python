# ruff: noqa: E501 - test names are sentences naming the case, as in the integration suite
"""`SagaFactHandler.handle` with fakes: the transactional unit of `design.md` 7.1.

R25, SO3, SO8, SO12.

The fakes record the ORDER of the calls a step makes, so "save then enqueue" and "loaded for update,
never plain" are assertions, not hopes. The fake consumption runs `work` once against the fake
transaction (a first delivery) or returns `DUPLICATE` without running it (a redelivery).
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import pytest

from otc_contracts import to_wire_json
from otc_contracts.generated.asyncapi import Reason1, Reason3
from otc_orders.application.ports.saga_command_store import (
    AcceptedOperatorCancel,
    EnqueueOutcome,
    OwedCommand,
)
from otc_orders.application.ports.saga_ignored_facts import IgnoredFactMarker
from otc_orders.application.ports.saga_metrics import SagaMetrics, SagaOutcome
from otc_orders.application.ports.unit_of_work import OrdersTransaction
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.fact import SagaFact
from otc_orders.application.saga.fact_consumption import ConsumptionResult
from otc_orders.application.saga.fact_handler import (
    SagaFactHandler,
    SagaFactOutcome,
    SagaFactResult,
)
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import UniqueId


@dataclass
class Recorder:
    calls: list[str] = field(default_factory=list)
    saved: list[Order] = field(default_factory=list)
    enqueued: list[OwedCommand] = field(default_factory=list)
    ignored: list[dict[str, object]] = field(default_factory=list)


class FakeOrders:
    def __init__(self, recorder: Recorder, order: Order | None) -> None:
        self._recorder = recorder
        self._order = order

    async def get_by_id(self, order_id: UniqueId) -> Order | None:
        raise AssertionError("a saga step must load the order FOR UPDATE, never with a plain read")

    async def get_by_id_for_update(self, order_id: UniqueId) -> Order | None:
        self._recorder.calls.append("load_for_update")
        return self._order

    async def save(self, order: Order) -> None:
        self._recorder.calls.append("save")
        self._recorder.saved.append(order)


class FakeQueue:
    def __init__(
        self,
        recorder: Recorder,
        outcome: EnqueueOutcome,
        accepted: AcceptedOperatorCancel | None = None,
    ) -> None:
        self._recorder = recorder
        self._outcome = outcome
        self._accepted = accepted

    async def find_accepted_operator_cancel(
        self, order_id: UniqueId
    ) -> AcceptedOperatorCancel | None:
        self._recorder.calls.append("find_accepted_operator_cancel")
        return self._accepted

    async def enqueue(self, command: OwedCommand) -> EnqueueOutcome:
        self._recorder.calls.append("enqueue")
        self._recorder.enqueued.append(command)
        return self._outcome


class FakeIgnored:
    def __init__(self, recorder: Recorder) -> None:
        self._recorder = recorder

    async def record(self, **fields: object) -> None:
        self._recorder.calls.append("record_ignored")
        self._recorder.ignored.append(fields)


class FakeTransaction:
    def __init__(
        self,
        recorder: Recorder,
        order: Order | None,
        outcome: EnqueueOutcome,
        accepted: AcceptedOperatorCancel | None = None,
    ) -> None:
        self.orders = FakeOrders(recorder, order)
        self.saga_commands = FakeQueue(recorder, outcome, accepted)
        self.ignored_facts = FakeIgnored(recorder)
        self.order_numbers = None


class FakeConsumption:
    def __init__(self, transaction: FakeTransaction, *, duplicate: bool = False) -> None:
        self._transaction = transaction
        self._duplicate = duplicate
        self.event_ids: list[uuid.UUID] = []

    async def run_once(
        self, event_id: uuid.UUID, work: Callable[[OrdersTransaction], Awaitable[None]]
    ) -> ConsumptionResult:
        self.event_ids.append(event_id)
        if self._duplicate:
            return ConsumptionResult.DUPLICATE
        await work(self._transaction)  # type: ignore[arg-type]
        return ConsumptionResult.PROCESSED


def handler_over(
    order: Order | None,
    *,
    duplicate: bool = False,
    outcome: EnqueueOutcome = EnqueueOutcome.ENQUEUED,
    accepted: AcceptedOperatorCancel | None = None,
    metrics: SagaMetrics | None = None,
) -> tuple[SagaFactHandler, Recorder, FakeConsumption]:
    recorder = Recorder()
    consumption = FakeConsumption(
        FakeTransaction(recorder, order, outcome, accepted), duplicate=duplicate
    )
    return SagaFactHandler(consumption, metrics), recorder, consumption


async def test_a_duplicate_does_nothing_at_all(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    handler, recorder, consumption = handler_over(order_in(OrderStatus.PLACED), duplicate=True)
    fact = make_fact("stock.reserved.v1")

    result = await handler.handle(fact)

    assert result == SagaFactResult(SagaFactOutcome.DUPLICATE, None)
    assert recorder.calls == []
    assert consumption.event_ids == [fact.event_id.value]


async def test_an_unknown_order_records_one_unknown_order_row_and_saves_and_enqueues_nothing(
    make_fact: Callable[..., SagaFact],
) -> None:
    handler, recorder, _ = handler_over(None)
    fact = make_fact("stock.reserved.v1")

    result = await handler.handle(fact)

    assert result == SagaFactResult(SagaFactOutcome.IGNORED, None)
    assert recorder.calls == ["load_for_update", "record_ignored"]
    [row] = recorder.ignored
    assert row == {
        "event_id": fact.event_id,
        "event_type": "stock.reserved.v1",
        "correlation_id": fact.correlation_id,
        "order_id": None,
        "observed_status": None,
        "expected_status": OrderStatus.PLACED,
        "marker": IgnoredFactMarker.UNKNOWN_ORDER,
    }


@pytest.mark.parametrize(
    ("event_type", "observed", "expected"),
    [
        ("stock.reserved.v1", OrderStatus.STOCK_RESERVED, OrderStatus.PLACED),
        ("credit.approved.v1", OrderStatus.PLACED, OrderStatus.STOCK_RESERVED),
        ("payment.received.v1", OrderStatus.CANCELLED, OrderStatus.INVOICED),
    ],
)
async def test_a_precondition_unmet_records_both_statuses_and_saves_and_enqueues_nothing(
    event_type: str,
    observed: OrderStatus,
    expected: OrderStatus,
    order_in: Callable[..., Order],
    make_fact: Callable[..., SagaFact],
) -> None:
    handler, recorder, _ = handler_over(order_in(observed))
    fact = make_fact(event_type)

    result = await handler.handle(fact)

    assert result == SagaFactResult(SagaFactOutcome.IGNORED, None)
    assert recorder.calls == ["load_for_update", "record_ignored"]
    [row] = recorder.ignored
    assert row["observed_status"] is observed
    assert row["expected_status"] is expected
    assert row["marker"] is IgnoredFactMarker.PRECONDITION_UNMET
    assert row["order_id"] == fact.correlation_id
    assert recorder.saved == []
    assert recorder.enqueued == []


async def test_a_happy_step_loads_for_update_saves_then_enqueues_and_names_the_owed_command(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.PLACED)
    handler, recorder, _ = handler_over(order)
    fact = make_fact("stock.reserved.v1")

    result = await handler.handle(fact)

    assert result == SagaFactResult(SagaFactOutcome.PROCESSED, SagaCommandKind.CREDIT_HOLD)
    assert recorder.calls == ["load_for_update", "save", "enqueue"], "save THEN enqueue"
    assert order.status is OrderStatus.STOCK_RESERVED
    assert recorder.saved == [order]
    [owed] = recorder.enqueued
    assert owed.kind is SagaCommandKind.CREDIT_HOLD
    assert owed.order_id == order.id
    assert owed.triggering_event_id == fact.event_id
    assert '"amount":{"amount":8115,"currency":"EUR"}' in owed.payload


async def test_order_placed_enqueues_stock_reserve_without_saving_an_unchanged_order(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.PLACED)
    handler, recorder, _ = handler_over(order)

    result = await handler.handle(make_fact("order.placed.v1"))

    assert result == SagaFactResult(SagaFactOutcome.PROCESSED, SagaCommandKind.STOCK_RESERVE)
    assert recorder.calls == ["load_for_update", "enqueue"], "the lock is taken; nothing to save"
    assert order.status is OrderStatus.PLACED


async def test_credit_approved_takes_both_edges_in_one_save_and_enqueues_despatch_create(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.STOCK_RESERVED)
    handler, recorder, _ = handler_over(order)

    result = await handler.handle(make_fact("credit.approved.v1"))

    assert result.enqueued is SagaCommandKind.DESPATCH_CREATE
    assert recorder.calls == [
        "load_for_update",
        "find_accepted_operator_cancel",
        "save",
        "enqueue",
    ], "a credit approval at stock_reserved first asks whether an operator cancel was accepted"
    assert order.status is OrderStatus.CONFIRMED
    assert len(order.domain_events) == 1


async def test_a_cancel_saves_and_owes_nothing(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.PLACED)
    handler, recorder, _ = handler_over(order)

    result = await handler.handle(make_fact("stock.rejected.v1"))

    assert result == SagaFactResult(SagaFactOutcome.PROCESSED, None)
    assert recorder.calls == ["load_for_update", "save"]
    assert order.status is OrderStatus.CANCELLED


async def test_a_command_already_owed_is_still_reported_owed_and_warns(
    order_in: Callable[..., Order],
    make_fact: Callable[..., SagaFact],
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler, _, _ = handler_over(order_in(OrderStatus.PLACED), outcome=EnqueueOutcome.ALREADY_OWED)

    with caplog.at_level(logging.WARNING):
        result = await handler.handle(make_fact("stock.reserved.v1"))

    assert result.enqueued is SagaCommandKind.CREDIT_HOLD, "the fast path re-signals the row"
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning.command == "credit.hold"  # type: ignore[attr-defined]
    assert warning.correlationId == str(make_fact("stock.reserved.v1").correlation_id)  # type: ignore[attr-defined]


async def test_so12_the_owed_commands_reference_is_the_aggregates_never_the_facts(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.PLACED)
    handler, recorder, _ = handler_over(order)
    fact = make_fact("stock.reserved.v1")
    object.__setattr__(fact.payload, "order_reference", "ORD-000000")  # the wire admits it

    result = await handler.handle(fact)

    assert result.enqueued is SagaCommandKind.CREDIT_HOLD
    [owed] = recorder.enqueued
    assert owed.order_reference == "ORD-000007"
    assert '"orderReference":"ORD-000007"' in owed.payload
    assert "ORD-000000" not in owed.payload


async def test_a_skip_fact_reaching_the_handler_is_a_no_op_with_no_io(
    make_fact: Callable[..., SagaFact],
) -> None:
    handler, recorder, consumption = handler_over(None)

    result = await handler.handle(make_fact("order.confirmed.v1"))

    assert result == SagaFactResult(SagaFactOutcome.PROCESSED, None)
    assert recorder.calls == []
    assert consumption.event_ids == []


async def test_the_enqueued_payload_is_the_one_serializer_text_of_the_request_model(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    from otc_orders.application.saga.command_payloads import build_command_payload

    order = order_in(OrderStatus.PLACED)
    handler, recorder, _ = handler_over(order)
    fact = make_fact("order.placed.v1")

    await handler.handle(fact)

    [owed] = recorder.enqueued
    assert owed.payload == to_wire_json(
        build_command_payload(SagaCommandKind.STOCK_RESERVE, order, fact)
    )


# ----------------------------------------------------------------- feature 41: SA-4's branches


async def test_a_late_credit_approval_at_stock_reserved_with_an_accepted_cancel_owes_credit_release_and_changes_nothing(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.STOCK_RESERVED)
    handler, recorder, _ = handler_over(order, accepted=AcceptedOperatorCancel(note="n"))
    fact = make_fact("credit.approved.v1")

    result = await handler.handle(fact)

    assert result == SagaFactResult(SagaFactOutcome.PROCESSED, SagaCommandKind.CREDIT_RELEASE)
    assert recorder.calls == ["load_for_update", "find_accepted_operator_cancel", "enqueue"]
    assert recorder.saved == [], "no transition: nothing is saved"
    assert order.status is OrderStatus.STOCK_RESERVED
    assert order.domain_events == (), "no order.confirmed.v1"
    [owed] = recorder.enqueued
    assert owed.kind is SagaCommandKind.CREDIT_RELEASE
    assert owed.triggering_event_id == fact.event_id
    assert owed.operator_note is None, "the late release is not the operator's request"
    assert '"orderReference":"ORD-000007"' in owed.payload


async def test_a_late_credit_approval_at_stock_reserved_without_an_accepted_cancel_confirms_as_usual(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.STOCK_RESERVED)
    handler, recorder, _ = handler_over(order, accepted=None)

    result = await handler.handle(make_fact("credit.approved.v1"))

    assert result == SagaFactResult(SagaFactOutcome.PROCESSED, SagaCommandKind.DESPATCH_CREATE)
    assert order.status is OrderStatus.CONFIRMED
    assert [c.kind for c in recorder.enqueued] == [SagaCommandKind.DESPATCH_CREATE]


async def test_a_credit_approval_for_an_order_already_cancelled_by_the_operator_owes_credit_release_only(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.CANCELLED, reason=CancellationReason.OPERATOR_CANCELLED)
    handler, recorder, _ = handler_over(order, accepted=None)

    result = await handler.handle(make_fact("credit.approved.v1"))

    assert result == SagaFactResult(SagaFactOutcome.PROCESSED, SagaCommandKind.CREDIT_RELEASE)
    assert recorder.calls == ["load_for_update", "enqueue"], (
        "the cancelled shape needs no query: the aggregate already says operator_cancelled"
    )
    assert recorder.saved == []


@pytest.mark.parametrize(
    "reason", [CancellationReason.CREDIT_REJECTED, CancellationReason.STOCK_REJECTED]
)
async def test_a_credit_approval_for_a_cancellation_the_saga_decided_is_ignored(
    reason: CancellationReason,
    order_in: Callable[..., Order],
    make_fact: Callable[..., SagaFact],
) -> None:
    order = order_in(OrderStatus.CANCELLED, reason=reason)
    handler, recorder, _ = handler_over(order, accepted=AcceptedOperatorCancel(note=None))

    result = await handler.handle(make_fact("credit.approved.v1"))

    assert result == SagaFactResult(SagaFactOutcome.IGNORED, None)
    assert recorder.enqueued == []
    assert recorder.saved == []


@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.PLACED,
        OrderStatus.CREDIT_APPROVED,
        OrderStatus.CONFIRMED,
        OrderStatus.DESPATCHED,
        OrderStatus.COMPLETED,
    ],
)
async def test_a_credit_approval_at_any_other_status_is_never_a_late_approval_even_with_an_accepted_cancel(
    status: OrderStatus, order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    handler, recorder, _ = handler_over(
        order_in(status), accepted=AcceptedOperatorCancel(note=None)
    )

    result = await handler.handle(make_fact("credit.approved.v1"))

    assert result == SagaFactResult(SagaFactOutcome.IGNORED, None)
    assert recorder.enqueued == []


async def test_the_late_credit_release_that_is_already_owed_is_still_reported_owed_and_warns(
    order_in: Callable[..., Order],
    make_fact: Callable[..., SagaFact],
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler, _, _ = handler_over(
        order_in(OrderStatus.STOCK_RESERVED),
        outcome=EnqueueOutcome.ALREADY_OWED,
        accepted=AcceptedOperatorCancel(note=None),
    )

    with caplog.at_level(logging.WARNING):
        result = await handler.handle(make_fact("credit.approved.v1"))

    assert result.enqueued is SagaCommandKind.CREDIT_RELEASE
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning.command == "credit.release"  # type: ignore[attr-defined]


@pytest.mark.parametrize("status", [OrderStatus.CREDIT_APPROVED, OrderStatus.CONFIRMED])
async def test_stock_released_at_credit_approved_or_confirmed_saves_nothing_and_owes_credit_release(
    status: OrderStatus, order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(status)
    handler, recorder, _ = handler_over(order)
    fact = make_fact("stock.released.v1", release_reason=Reason1.order_cancelled)

    result = await handler.handle(fact)

    assert result == SagaFactResult(SagaFactOutcome.PROCESSED, SagaCommandKind.CREDIT_RELEASE)
    assert recorder.calls == ["load_for_update", "enqueue"], "the status is unchanged: no save"
    assert order.status is status
    [owed] = recorder.enqueued
    assert owed.triggering_event_id == fact.event_id


async def test_an_operator_cancellation_completed_by_the_stock_fact_carries_the_accepted_notes_text(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.STOCK_RESERVED)
    handler, recorder, _ = handler_over(order, accepted=AcceptedOperatorCancel(note="$operator"))

    result = await handler.handle(
        make_fact("stock.released.v1", release_reason=Reason1.order_cancelled)
    )

    assert result == SagaFactResult(SagaFactOutcome.PROCESSED, None)
    assert recorder.calls == ["load_for_update", "find_accepted_operator_cancel", "save"]
    [cancelled] = order.domain_events
    assert cancelled.note == "$operator"  # type: ignore[attr-defined]
    assert cancelled.cancellation_reason is CancellationReason.OPERATOR_CANCELLED  # type: ignore[attr-defined]


@pytest.mark.parametrize("status", [OrderStatus.CREDIT_APPROVED, OrderStatus.CONFIRMED])
async def test_an_operator_cancellation_completed_by_the_credit_fact_carries_the_accepted_notes_text(
    status: OrderStatus, order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(status)
    handler, _, _ = handler_over(order, accepted=AcceptedOperatorCancel(note="$operator"))

    await handler.handle(
        make_fact("credit.released.v1", credit_release_reason=Reason3.order_cancelled)
    )

    [cancelled] = order.domain_events
    assert cancelled.note == "$operator"  # type: ignore[attr-defined]
    assert len(cancelled.compensation_steps) == 2  # type: ignore[attr-defined]


async def test_an_operator_cancellation_with_no_accepted_note_carries_no_note(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.STOCK_RESERVED)
    handler, _, _ = handler_over(order, accepted=AcceptedOperatorCancel(note=None))

    await handler.handle(make_fact("stock.released.v1", release_reason=Reason1.order_cancelled))

    [cancelled] = order.domain_events
    assert cancelled.note is None  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("event_type", "status"),
    [("stock.rejected.v1", OrderStatus.PLACED), ("stock.released.v1", OrderStatus.STOCK_RESERVED)],
)
async def test_a_saga_decided_cancellation_never_reads_an_operator_note(
    event_type: str,
    status: OrderStatus,
    order_in: Callable[..., Order],
    make_fact: Callable[..., SagaFact],
) -> None:
    """`stock.rejected.v1` and a credit-rejected release cancel for the saga's own reason: even if a
    note were stored beside the order's release row, it is not this cancellation's."""
    order = order_in(status)
    handler, recorder, _ = handler_over(order, accepted=AcceptedOperatorCancel(note="not mine"))

    await handler.handle(make_fact(event_type))

    assert "find_accepted_operator_cancel" not in recorder.calls
    [cancelled] = order.domain_events
    assert cancelled.note is None  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- R59 / OR9 (S5.5)
# 90 minutes and 123 ms separate the order's date from every fact the conftest builds.
CLOSE_MS = 90 * 60 * 1000 + 123.0


class RecordingMetrics:
    def __init__(self) -> None:
        self.closed_calls: list[tuple[SagaOutcome, float]] = []

    def closed(self, outcome: SagaOutcome, milliseconds: float) -> None:
        self.closed_calls.append((outcome, milliseconds))


async def test_r59_a_completing_transition_records_exactly_one_completed_with_the_exact_elapsed_ms(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    metrics = RecordingMetrics()
    handler, _, _ = handler_over(order_in(OrderStatus.PAID), metrics=metrics)

    await handler.handle(make_fact("credit.released.v1"))

    assert metrics.closed_calls == [("completed", CLOSE_MS)]


async def test_r59_a_direct_cancel_stock_rejected_records_exactly_one_cancelled(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    metrics = RecordingMetrics()
    handler, _, _ = handler_over(order_in(OrderStatus.PLACED), metrics=metrics)

    await handler.handle(make_fact("stock.rejected.v1"))

    assert metrics.closed_calls == [("cancelled", CLOSE_MS)]


async def test_r59_the_compensation_completing_cancel_records_one_cancelled_not_two(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    """The operator cancellation of a confirmed order takes two facts: `stock.released.v1` (an
    Advance that owes `credit.release`: the saga is still open) and then `credit.released.v1` (the
    Cancel that closes it). Only the second records."""
    metrics = RecordingMetrics()
    first, _, _ = handler_over(order_in(OrderStatus.CONFIRMED), metrics=metrics)
    await first.handle(make_fact("stock.released.v1", release_reason=Reason1.order_cancelled))
    assert metrics.closed_calls == [], "the first compensation step must not close the saga"

    second, _, _ = handler_over(order_in(OrderStatus.CONFIRMED), metrics=metrics)
    await second.handle(
        make_fact("credit.released.v1", credit_release_reason=Reason3.order_cancelled)
    )

    assert metrics.closed_calls == [("cancelled", CLOSE_MS)]


@pytest.mark.parametrize(
    ("event_type", "status"),
    [
        ("stock.reserved.v1", OrderStatus.PLACED),
        ("credit.approved.v1", OrderStatus.STOCK_RESERVED),
        ("order.despatched.v1", OrderStatus.CONFIRMED),
        ("payment.received.v1", OrderStatus.INVOICED),
    ],
)
async def test_r59_a_step_that_leaves_the_order_open_records_nothing(
    event_type: str,
    status: OrderStatus,
    order_in: Callable[..., Order],
    make_fact: Callable[..., SagaFact],
) -> None:
    metrics = RecordingMetrics()
    handler, _, _ = handler_over(order_in(status), metrics=metrics)

    result = await handler.handle(make_fact(event_type))

    assert result.outcome is SagaFactOutcome.PROCESSED
    assert metrics.closed_calls == []


async def test_r59_an_ignored_fact_records_nothing(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    metrics = RecordingMetrics()
    # `credit.released.v1` for a `placed` order matches no variant: ignored, never a closing
    handler, _, _ = handler_over(order_in(OrderStatus.PLACED), metrics=metrics)

    result = await handler.handle(make_fact("credit.released.v1"))

    assert result.outcome is SagaFactOutcome.IGNORED
    assert metrics.closed_calls == []


async def test_r59_a_deduplicated_redelivery_of_a_closing_fact_records_nothing(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    metrics = RecordingMetrics()
    handler, _, _ = handler_over(order_in(OrderStatus.PAID), duplicate=True, metrics=metrics)

    result = await handler.handle(make_fact("credit.released.v1"))

    assert result.outcome is SagaFactOutcome.DUPLICATE
    assert metrics.closed_calls == []


async def test_r59_a_closing_step_whose_transaction_fails_records_nothing(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    """Recorded strictly AFTER commit: `work` ran and applied the closing transition, then the
    unit of work failed, so the order is NOT closed and the metric must not say it is."""
    metrics = RecordingMetrics()
    handler, _, consumption = handler_over(order_in(OrderStatus.PAID), metrics=metrics)

    class FailsAfterWork:
        async def run_once(
            self, event_id: uuid.UUID, work: Callable[[OrdersTransaction], Awaitable[None]]
        ) -> ConsumptionResult:
            await consumption.run_once(event_id, work)
            raise RuntimeError("commit failed")

    handler._consumption = FailsAfterWork()

    with pytest.raises(RuntimeError, match="commit failed"):
        await handler.handle(make_fact("credit.released.v1"))

    assert metrics.closed_calls == []
