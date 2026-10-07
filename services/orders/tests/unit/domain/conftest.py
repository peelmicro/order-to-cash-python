"""Builders for the Order aggregate's pure unit tests (`design.md` section 11.1).

Pytest fixtures, not helper modules: the repository runs `--import-mode=importlib`, so a test module
cannot import a sibling module. Builders, not mocks. Every instant is aware UTC; every pair of
fixture lines differs in price, quantity and discount, and the totals are non-round, so a formula
with a wrong term cannot coincide with the right answer.

Loop scope: nothing here is async.
"""

import dataclasses
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from otc_orders.domain.order import Order
from otc_orders.domain.order_line import OrderLineInput
from otc_orders.domain.snapshot import OrderLineSnapshot, OrderSnapshot
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import GLN, Money, OrderNumber, Quantity, UniqueId

BASE_INSTANT = datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC)
LINE_A_ID = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000a1"))
LINE_B_ID = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000b2"))

# Hand-computed from the two fixture lines: 3 x 1999 + 2 x 1234 = 8465; discounts 250 + 100 = 350.
EXPECTED_INITIAL_AMOUNT = 8465
EXPECTED_INITIAL_DISCOUNT = 350
EXPECTED_TOTAL_AMOUNT = 8115

State = tuple[object, ...]


@pytest.fixture
def at() -> Callable[[int], datetime]:
    """`at(n)`: the aware-UTC instant `n` minutes after a fixed base."""

    def instant(minutes: int) -> datetime:
        return BASE_INSTANT + timedelta(minutes=minutes)

    return instant


@pytest.fixture
def causation() -> UniqueId:
    return UniqueId.new()


@pytest.fixture
def line_a() -> OrderLineInput:
    return OrderLineInput(
        product_code="SKU-A",
        description="Alpha pallet",
        quantity=Quantity(3),
        unit_price=Money(1999, "EUR"),
        line_discount=Money(250, "EUR"),
    )


@pytest.fixture
def line_b() -> OrderLineInput:
    return OrderLineInput(
        product_code="SKU-B",
        description=None,
        quantity=Quantity(2),
        unit_price=Money(1234, "EUR"),
        line_discount=Money(100, "EUR"),
    )


@pytest.fixture
def place_order(
    at: Callable[[int], datetime],
    causation: UniqueId,
    line_a: OrderLineInput,
    line_b: OrderLineInput,
) -> Callable[..., Order]:
    """`place_order(lines=..., currency=..., notes=..., occurred_at=...)`: a placed EUR order."""

    def place(
        *,
        lines: Sequence[OrderLineInput] | None = None,
        currency: str = "EUR",
        notes: str | None = None,
        occurred_at: datetime | None = None,
        order_date: datetime | None = None,
        causation_id: UniqueId | None = None,
        order_reference: str = "ORD-000001",
    ) -> Order:
        return Order.place(
            order_reference=OrderNumber(order_reference),
            order_date=order_date if order_date is not None else at(-60),
            retailer_code="RET-01",
            buyer_gln=GLN("4012345000009"),
            company_code="CMP-01",
            supplier_gln=GLN("5412345000006"),
            currency=currency,
            lines=(line_a, line_b) if lines is None else lines,
            notes=notes,
            occurred_at=occurred_at if occurred_at is not None else at(0),
            causation_id=causation_id if causation_id is not None else causation,
        )

    return place


@pytest.fixture
def placed_order(place_order: Callable[..., Order]) -> Order:
    return place_order()


@pytest.fixture
def one_line_order(place_order: Callable[..., Order], line_a: OrderLineInput) -> Order:
    return place_order(lines=(line_a,))


@pytest.fixture
def walk_to(
    at: Callable[[int], datetime], causation: UniqueId
) -> Callable[[Order, OrderStatus], None]:
    """`walk_to(order, status)`: advance a placed order along the happy path (real transitions)."""

    def walk(order: Order, status: OrderStatus) -> None:
        path = [
            OrderStatus.PLACED,
            OrderStatus.STOCK_RESERVED,
            OrderStatus.CREDIT_APPROVED,
            OrderStatus.CONFIRMED,
            OrderStatus.DESPATCHED,
            OrderStatus.INVOICED,
            OrderStatus.PAID,
            OrderStatus.COMPLETED,
        ]
        steps: dict[OrderStatus, Callable[[], None]] = {
            OrderStatus.STOCK_RESERVED: lambda: order.mark_stock_reserved(occurred_at=at(10)),
            OrderStatus.CREDIT_APPROVED: lambda: order.approve_credit(occurred_at=at(20)),
            OrderStatus.CONFIRMED: lambda: order.confirm(
                occurred_at=at(30), causation_id=causation
            ),
            OrderStatus.DESPATCHED: lambda: order.mark_despatched(occurred_at=at(40)),
            OrderStatus.INVOICED: lambda: order.mark_invoiced(occurred_at=at(50)),
            OrderStatus.PAID: lambda: order.mark_paid(occurred_at=at(60)),
            OrderStatus.COMPLETED: lambda: order.complete(
                occurred_at=at(70), causation_id=causation
            ),
        }
        current, goal = path.index(order.status), path.index(status)
        assert goal >= current, "walk_to only moves forward"
        for target in path[current + 1 : goal + 1]:
            steps[target]()
        assert order.status is status

    return walk


@pytest.fixture
def make_snapshot(
    at: Callable[[int], datetime],
) -> Callable[..., OrderSnapshot]:
    """`make_snapshot(**overrides)`: a stored EUR order as business values (no totals)."""

    def build(**overrides: Any) -> OrderSnapshot:
        base = OrderSnapshot(
            id=UniqueId(uuid.UUID("00000000-0000-4000-8000-000000000001")),
            order_reference=OrderNumber("ORD-000007"),
            order_date=at(-60),
            retailer_code="RET-01",
            buyer_gln=GLN("4012345000009"),
            company_code="CMP-01",
            supplier_gln=GLN("5412345000006"),
            currency="EUR",
            status=OrderStatus.PLACED,
            cancellation_reason=None,
            notes=None,
            lines=(
                OrderLineSnapshot(
                    id=LINE_A_ID,
                    product_code="SKU-A",
                    description="Alpha pallet",
                    quantity=Quantity(3),
                    unit_price=Money(1999, "EUR"),
                    line_discount=Money(250, "EUR"),
                ),
                OrderLineSnapshot(
                    id=LINE_B_ID,
                    product_code="SKU-B",
                    description=None,
                    quantity=Quantity(2),
                    unit_price=Money(1234, "EUR"),
                    line_discount=Money(100, "EUR"),
                ),
            ),
            created_at=at(0),
            updated_at=at(5),
        )
        return dataclasses.replace(base, **overrides)

    return build


@pytest.fixture
def order_in(make_snapshot: Callable[..., OrderSnapshot]) -> Callable[..., Order]:
    """`order_in(status, reason=None, line_count=2)`: an order restored in `status` (rehydrate).

    The legal walk is R8's job; this reaches every status, including the two terminal ones.
    """

    def build(
        status: OrderStatus, *, reason: CancellationReason | None = None, line_count: int = 2
    ) -> Order:
        if status is OrderStatus.CANCELLED and reason is None:
            reason = CancellationReason.OPERATOR_CANCELLED
        snapshot = make_snapshot(status=status, cancellation_reason=reason)
        kept = dataclasses.replace(snapshot, lines=snapshot.lines[:line_count])
        return Order.rehydrate(kept)

    return build


@pytest.fixture
def state_of() -> Callable[[Order], State]:
    """Every field of the aggregate that a refused operation must leave untouched."""

    def capture(order: Order) -> State:
        return (
            order.status,
            order.cancellation_reason,
            order.currency,
            order.notes,
            tuple(
                (
                    line.id,
                    line.product_code,
                    line.description,
                    line.quantity,
                    line.unit_price,
                    line.line_discount,
                )
                for line in order.lines
            ),
            order.initial_amount,
            order.initial_discount,
            order.total_amount,
            order.created_at,
            order.updated_at,
            len(order.domain_events),
        )

    return capture
