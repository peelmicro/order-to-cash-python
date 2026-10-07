"""Table T-1 and the status state machine (R8, R9; `design.md` section 4).

T-1 is TRANSCRIBED below (12 rows: source, target, fact) and also PARSED at run time from
`specs/shared/domain-model.md` section 3.3, so neither a typo in the literal nor a drift in the spec
passes silently. The expectation is never built from `LEGAL_EDGES` (tasks.md trap 3).
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from otc_orders.domain.errors import IllegalOrderTransitionError, OrderNotCancellableError
from otc_orders.domain.order import Order
from otc_orders.domain.state_machine import LEGAL_EDGES, Edge, is_legal
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import UniqueId

State = tuple[object, ...]

# (row, source token or None for creation, target token, fact or None)
T1: list[tuple[int, str | None, str, str | None]] = [
    (1, None, "placed", "order.placed.v1"),
    (2, "placed", "stock_reserved", None),
    (3, "stock_reserved", "credit_approved", None),
    (4, "credit_approved", "confirmed", "order.confirmed.v1"),
    (5, "confirmed", "despatched", None),
    (6, "despatched", "invoiced", None),
    (7, "invoiced", "paid", None),
    (8, "paid", "completed", "order.completed.v1"),
    (9, "placed", "cancelled", "order.cancelled.v1"),
    (10, "stock_reserved", "cancelled", "order.cancelled.v1"),
    (11, "credit_approved", "cancelled", "order.cancelled.v1"),
    (12, "confirmed", "cancelled", "order.cancelled.v1"),
]
LEGAL_PAIRS = {(source, target) for _, source, target, _ in T1 if source is not None}
STATUS_TOKENS = [
    "placed",
    "stock_reserved",
    "credit_approved",
    "confirmed",
    "despatched",
    "invoiced",
    "paid",
    "completed",
    "cancelled",
]
ATTEMPTABLE_TARGETS = [token for token in STATUS_TOKENS if token != "placed"]
CANCELLABLE_SOURCES = ["placed", "stock_reserved", "credit_approved", "confirmed"]
TERMINAL = ["completed", "cancelled"]


def _spec_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "specs" / "shared" / "domain-model.md"
        if candidate.exists():
            return candidate
    raise AssertionError("specs/shared/domain-model.md not found above this test")


def _cell(text: str) -> str | None:
    cleaned = text.strip().strip("`").strip()
    return None if cleaned in {"*(none)*", "—"} else cleaned


def _parse_t1_from_the_specification() -> list[tuple[int, str | None, str, str | None]]:
    lines = _spec_path().read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("**Table T-1"))
    rows: list[tuple[int, str | None, str, str | None]] = []
    for line in lines[start + 1 :]:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0].isdigit():
            target = _cell(cells[2])
            assert target is not None
            rows.append((int(cells[0]), _cell(cells[1]), target, _cell(cells[4])))
        elif rows:
            break
    return rows


def test_legal_edges_are_exactly_the_eleven_status_to_status_edges_of_table_t1() -> None:
    held = {(edge.source.value, edge.target.value) for edge in LEGAL_EDGES}
    assert len(LEGAL_PAIRS) == 11
    assert len(LEGAL_EDGES) == 11
    assert held == LEGAL_PAIRS, (
        f"LEGAL_EDGES differs from Table T-1: missing={sorted(LEGAL_PAIRS - held)} "
        f"extra={sorted(held - LEGAL_PAIRS)}"
    )


def test_table_t1_parsed_from_the_specification_equals_the_transcription() -> None:
    parsed = _parse_t1_from_the_specification()
    assert parsed == T1
    assert len(parsed) == 12
    assert sum(1 for _, source, _, _ in parsed if source is not None) == 11
    assert sum(1 for _, _, _, fact in parsed if fact is not None) == 7
    assert sum(1 for _, _, _, fact in parsed if fact is None) == 5


def _status(order: Order) -> OrderStatus:
    """The status as an `OrderStatus`: stops mypy narrowing it to one literal across calls."""
    return order.status


@pytest.fixture
def attempts(
    at: Callable[[int], datetime], causation: UniqueId
) -> dict[str, Callable[[Order], None]]:
    """One attempt per attemptable target status (`placed` is created, never targeted)."""
    return {
        "stock_reserved": lambda o: o.mark_stock_reserved(occurred_at=at(90)),
        "credit_approved": lambda o: o.approve_credit(occurred_at=at(90)),
        "confirmed": lambda o: o.confirm(occurred_at=at(90), causation_id=causation),
        "despatched": lambda o: o.mark_despatched(occurred_at=at(90)),
        "invoiced": lambda o: o.mark_invoiced(occurred_at=at(90)),
        "paid": lambda o: o.mark_paid(occurred_at=at(90)),
        "completed": lambda o: o.complete(occurred_at=at(90), causation_id=causation),
        "cancelled": lambda o: o.cancel(
            reason=CancellationReason.OPERATOR_CANCELLED,
            compensation_steps=(),
            occurred_at=at(90),
            causation_id=causation,
        ),
    }


def test_r8_order_walks_every_legal_edge_of_table_t1(
    place_order: Callable[..., Order],
    walk_to: Callable[[Order, OrderStatus], None],
    at: Callable[[int], datetime],
    causation: UniqueId,
) -> None:
    # From `Order.place` and real transitions, never `rehydrate`: rows 2-8, then each cancel row.
    order = place_order()
    assert _status(order) is OrderStatus.PLACED
    order.mark_stock_reserved(occurred_at=at(10))
    assert _status(order) is OrderStatus.STOCK_RESERVED
    order.approve_credit(occurred_at=at(20))
    assert _status(order) is OrderStatus.CREDIT_APPROVED
    order.confirm(occurred_at=at(30), causation_id=causation)
    assert _status(order) is OrderStatus.CONFIRMED
    order.mark_despatched(occurred_at=at(40))
    assert _status(order) is OrderStatus.DESPATCHED
    order.mark_invoiced(occurred_at=at(50))
    assert _status(order) is OrderStatus.INVOICED
    order.mark_paid(occurred_at=at(60))
    assert _status(order) is OrderStatus.PAID
    order.complete(occurred_at=at(70), causation_id=causation)
    assert _status(order) is OrderStatus.COMPLETED

    for row, source in [
        (9, OrderStatus.PLACED),
        (10, OrderStatus.STOCK_RESERVED),
        (11, OrderStatus.CREDIT_APPROVED),
        (12, OrderStatus.CONFIRMED),
    ]:
        fresh = place_order()
        walk_to(fresh, source)
        assert fresh.status is source, f"T-1 row {row}"
        fresh.cancel(
            reason=CancellationReason.OPERATOR_CANCELLED,
            compensation_steps=(),
            occurred_at=at(80),
            causation_id=causation,
        )
        assert fresh.status is OrderStatus.CANCELLED, f"T-1 row {row}"


def test_r8_order_reaches_cancelled_only_from_placed_stock_reserved_credit_approved_and_confirmed(
    order_in: Callable[..., Order],
    attempts: dict[str, Callable[[Order], None]],
) -> None:
    for token in STATUS_TOKENS:
        order = order_in(OrderStatus(token))
        if token in CANCELLABLE_SOURCES:
            attempts["cancelled"](order)
            assert order.status is OrderStatus.CANCELLED, token
        else:
            with pytest.raises(OrderNotCancellableError) as raised:
                attempts["cancelled"](order)
            assert raised.value.code == "order.not_cancellable", token
    assert len(CANCELLABLE_SOURCES) == 4


def test_r8_order_treats_completed_and_cancelled_as_terminal(
    order_in: Callable[..., Order],
    attempts: dict[str, Callable[[Order], None]],
    state_of: Callable[[Order], State],
) -> None:
    refused = 0
    for source in TERMINAL:
        for target, attempt in attempts.items():
            order = order_in(OrderStatus(source))
            before = state_of(order)
            with pytest.raises(IllegalOrderTransitionError):
                attempt(order)
            assert state_of(order) == before, f"{source} -> {target} changed the order"
            refused += 1
    assert refused == 16
    assert not any(is_legal(OrderStatus(s), t) for s in TERMINAL for t in OrderStatus)


def test_r9_order_raises_on_every_from_to_pair_absent_from_table_t1_without_mutating_state_or_appending_an_event(  # noqa: E501
    order_in: Callable[..., Order],
    attempts: dict[str, Callable[[Order], None]],
    state_of: Callable[[Order], State],
) -> None:
    assert len(attempts) == len(ATTEMPTABLE_TARGETS) == 8
    assert set(attempts) == set(ATTEMPTABLE_TARGETS)
    attempted = legal = illegal = 0
    for source in STATUS_TOKENS:
        for target in ATTEMPTABLE_TARGETS:
            attempted += 1
            order = order_in(OrderStatus(source))
            before = state_of(order)
            events_before = order.domain_events
            if (source, target) in LEGAL_PAIRS:
                legal += 1
                attempts[target](order)
                assert order.status is OrderStatus(target)
                continue
            illegal += 1
            with pytest.raises(IllegalOrderTransitionError):
                attempts[target](order)
            after = state_of(order)
            assert after == before, f"{source} -> {target} changed the order"  # status..updated_at
            assert order.domain_events == events_before, f"{source} -> {target} appended an event"
    assert (attempted, legal, illegal) == (72, 11, 61)


def test_every_pair_is_decided_by_is_legal_exactly_as_table_t1_says() -> None:
    decided = {
        (source, target)
        for source in STATUS_TOKENS
        for target in STATUS_TOKENS
        if is_legal(OrderStatus(source), OrderStatus(target))
    }
    assert decided == LEGAL_PAIRS
    assert Edge(OrderStatus.PLACED, OrderStatus.STOCK_RESERVED) in LEGAL_EDGES
