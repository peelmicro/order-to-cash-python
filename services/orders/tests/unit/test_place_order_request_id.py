"""`PlaceOrderCommandHandler` and `requestId` (R62, RI2 - RI5): no broker, no database.

The ports are in-memory fakes that LOG every call into one list, so "no reference data and no stock
check" is a counted fact. The unit of work fake models the real one's contract: an exception raised
in the block is a rollback; `collision` makes the fake raise `RequestIdAlreadyPlacedError` AFTER the
block, as `SqlAlchemyUnitOfWork.begin()` does (the winner commits in between).

Money fixtures are pairwise distinct and non-zero. The command computes 8465 / 350 / 8115; the
winner stored by another request computes 3000 / 100 / 2900, so a reply built from the loser's own
command differs from the winner's on every money field. Loop scope: default (function).
"""

from collections.abc import AsyncIterator, Collection, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from otc_orders.application.commands.place_order import (
    OrderDiscountNotSupportedError,
    PlaceOrderCommand,
    PlaceOrderCommandHandler,
    PlaceOrderLine,
    PlaceOrderResult,
)
from otc_orders.application.ports.reference_catalog import (
    CurrencyListing,
    PartyListing,
    PartyReference,
    ProductListing,
    ProductReference,
)
from otc_orders.application.ports.stock_availability import (
    StockAvailabilityLine,
    StockAvailabilityResult,
)
from otc_orders.application.ports.unit_of_work import RequestIdAlreadyPlacedError
from otc_orders.application.scope import OrdersScope
from otc_orders.domain.order import Order
from otc_orders.domain.order_line import OrderLineInput
from otc_orders.infrastructure.outbox.payloads import narrow
from otc_shared_kernel import GLN, Money, OrderNumber, Quantity, UniqueId

NOW = datetime(2026, 10, 6, 8, 30, 0, 123000, tzinfo=UTC)
EARLIER = datetime(2026, 10, 6, 8, 29, 41, 7000, tzinfo=UTC)
REQUEST_A = UUID("6b1f1f0e-6a0c-4c58-9d5c-0d6a3a1c1a01")
REQUEST_B = UUID("c7d2e1aa-91f4-4c7b-8a35-5e0f2b9d7b02")


class Log(list[str]):
    pass


class FakeCatalog:
    """Every call is logged; with `forbidden` it raises instead (RI2 touches no reference data)."""

    def __init__(self, log: Log, *, forbidden: bool) -> None:
        self.log, self.forbidden = log, forbidden

    def _touch(self, name: str) -> None:
        self.log.append(name)
        if self.forbidden:
            raise AssertionError(f"RI2: a replay must not resolve reference data ({name})")

    async def find_retailer(self, retailer_code: str) -> PartyReference | None:
        self._touch("catalog.retailer")
        return PartyReference("RET-01", GLN("4012345000009"))

    async def find_company(self, company_code: str) -> PartyReference | None:
        self._touch("catalog.company")
        return PartyReference("CMP-01", GLN("5412345000006"))

    async def currency_exists(self, currency_code: str) -> bool:
        self._touch("catalog.currency")
        return True

    async def find_products(self, product_codes: Collection[str]) -> Mapping[str, ProductReference]:
        self._touch("catalog.products")
        return {c: ProductReference(c, "d", Money(777, "EUR")) for c in product_codes}

    async def list_products(self, *, include_disabled: bool) -> Sequence[ProductListing]:
        raise AssertionError("never listed")

    async def list_retailers(self, *, include_disabled: bool) -> Sequence[PartyListing]:
        raise AssertionError("never listed")

    async def list_companies(self, *, include_disabled: bool) -> Sequence[PartyListing]:
        raise AssertionError("never listed")

    async def list_currencies(self) -> Sequence[CurrencyListing]:
        raise AssertionError("never listed")


class FakeStock:
    def __init__(self, log: Log, *, forbidden: bool) -> None:
        self.log, self.forbidden = log, forbidden

    async def check(
        self, company_code: str, lines: Sequence[StockAvailabilityLine]
    ) -> StockAvailabilityResult:
        self.log.append("stock.check")
        if self.forbidden:
            raise AssertionError("RI2: a replay must not make the stock check")
        return StockAvailabilityResult(True, ())


class Store:
    """What the 'database' holds: committed orders by request id; the lookup counter."""

    def __init__(self) -> None:
        self.by_request: dict[UUID, Order] = {}
        self.lookups: list[UUID] = []
        self.saved: list[tuple[Order, UUID | None]] = []
        self.before_collision: Order | None = None  # the winner that commits during the race


class FakeOrders:
    def __init__(self, log: Log, store: Store) -> None:
        self._log, self._store = log, store

    async def save(self, order: Order, *, request_id: UUID | None = None) -> None:
        self._log.append("orders.save")
        self._store.saved.append((order, request_id))

    async def find_by_request_id(self, request_id: UUID) -> Order | None:
        self._log.append("orders.find_by_request_id")
        self._store.lookups.append(request_id)
        return self._store.by_request.get(request_id)

    async def get_by_id(self, order_id: Any) -> Order | None:
        raise NotImplementedError

    async def get_by_id_for_update(self, order_id: Any) -> Order | None:
        raise NotImplementedError

    async def get_by_reference(self, reference: OrderNumber) -> Order | None:
        raise NotImplementedError


class FakeAllocator:
    async def next_number(self) -> OrderNumber:
        return OrderNumber("ORD-000042")


class FakeTransaction:
    def __init__(self, log: Log, store: Store) -> None:
        self.orders = FakeOrders(log, store)
        self.order_numbers = FakeAllocator()
        self.saga_commands: Any = None
        self.ignored_facts: Any = None


class FakeUnitOfWork:
    def __init__(self, log: Log, store: Store) -> None:
        self.log, self.store = log, store
        self.raise_after_block: Exception | None = None  # applied to the block that saves

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[FakeTransaction]:
        self.log.append("uow.begin")
        transaction = FakeTransaction(self.log, self.store)
        try:
            yield transaction
        except BaseException:
            self.log.append("uow.rollback")
            raise
        if self.raise_after_block is not None and self.store.saved:
            self.log.append("uow.rollback")
            winner = self.store.before_collision
            if winner is not None:
                self.store.by_request[REQUEST_A] = winner  # the winner commits meanwhile
            failure, self.raise_after_block = self.raise_after_block, None  # the race happens once
            raise failure
        self.log.append("uow.commit")


class FixedClock:
    def now(self) -> datetime:
        return NOW


class World:
    def __init__(self, *, replay_forbidden: bool = False) -> None:
        self.log = Log()
        self.store = Store()
        self.uow = FakeUnitOfWork(self.log, self.store)
        self.scope = OrdersScope(
            unit_of_work=self.uow,
            catalog=FakeCatalog(self.log, forbidden=replay_forbidden),
            stock=FakeStock(self.log, forbidden=replay_forbidden),
            clock=FixedClock(),
        )

    def handler(self) -> PlaceOrderCommandHandler:
        return PlaceOrderCommandHandler(self.scope)


def command(request_id: UUID | None) -> PlaceOrderCommand:
    return PlaceOrderCommand(
        request_id=request_id,
        retailer_code="RET-01",
        company_code="CMP-01",
        currency="EUR",
        lines=(
            PlaceOrderLine("SKU-A", Quantity(3), unit_price=1999, line_discount=250),
            PlaceOrderLine("SKU-B", Quantity(2), unit_price=1234, line_discount=100),
        ),
        order_discount=None,
        notes="dock 4",
    )


def winner_order() -> Order:
    """The order another request committed: 3000 / 100 / 2900, another reference and instant."""
    return Order.place(
        order_reference=OrderNumber("ORD-000007"),
        order_date=EARLIER,
        retailer_code="RET-01",
        buyer_gln=GLN("4012345000009"),
        company_code="CMP-01",
        supplier_gln=GLN("5412345000006"),
        currency="EUR",
        lines=[
            OrderLineInput(
                product_code="SKU-A",
                description="Alpha",
                quantity=Quantity(1),
                unit_price=Money(3000, "EUR"),
                line_discount=Money(100, "EUR"),
            )
        ],
        notes=None,
        occurred_at=EARLIER,
        causation_id=UniqueId.new(),
    )


def fields_of(result: PlaceOrderResult) -> tuple[object, ...]:
    return (
        result.order_id,
        result.order_reference,
        result.currency,
        result.initial_amount,
        result.initial_discount,
        result.total_amount,
        result.order_date,
    )


def reply_of(order: Order) -> tuple[object, ...]:
    return (
        order.id,
        order.order_reference,
        order.currency,
        order.initial_amount,
        order.initial_discount,
        order.total_amount,
        order.order_date,
    )


async def test_ri3_a_request_id_collision_resolves_to_the_winners_reply() -> None:
    world = World()
    winner = winner_order()
    world.store.before_collision = winner
    world.uow.raise_after_block = RequestIdAlreadyPlacedError("uq_orders_request_id")

    result = await world.handler().handle(command(REQUEST_A))

    assert fields_of(result) == reply_of(winner)
    # the three money fields are the winner's, none the loser's own command's (8465 / 350 / 8115)
    assert (result.initial_amount, result.initial_discount, result.total_amount) == (
        Money(3000, "EUR"),
        Money(100, "EUR"),
        Money(2900, "EUR"),
    )
    # the loser rolled back, then re-read in a NEW transaction: begin, rollback, begin, commit
    assert world.log[-4:] == [
        "uow.rollback",
        "uow.begin",
        "orders.find_by_request_id",
        "uow.commit",
    ]
    assert len(world.store.saved) == 1  # the loser attempted exactly one insert, none after


async def test_ri3_an_order_reference_collision_propagates_unchanged() -> None:
    world = World()
    other_collision = RuntimeError("duplicate key value violates unique constraint order_reference")
    world.uow.raise_after_block = other_collision  # not a RequestIdAlreadyPlacedError

    with pytest.raises(RuntimeError) as raised:
        await world.handler().handle(command(REQUEST_A))

    assert raised.value is other_collision
    # only the fast-path lookup ran; no second read of a "winner" for a foreign collision
    assert world.store.lookups == [REQUEST_A], (
        "a foreign collision must not trigger a winner re-read (only the fast-path lookup ran)"
    )


async def test_ri3_a_collision_with_no_readable_winner_propagates_the_original_error() -> None:
    world = World()
    original = RuntimeError("the database's own unique violation")
    collision = RequestIdAlreadyPlacedError("uq_orders_request_id")
    collision.__cause__ = original
    world.uow.raise_after_block = collision  # and no winner is ever stored

    with pytest.raises(RuntimeError) as raised:
        await world.handler().handle(command(REQUEST_A))

    assert raised.value is original
    assert world.store.lookups == [
        REQUEST_A,
        REQUEST_A,
    ]  # the fast path, then the re-read: found none


async def test_ri2_a_known_request_id_replays_the_original_reply_without_catalog_or_stock() -> None:
    world = World(replay_forbidden=True)  # the catalog and stock fakes raise if called
    original = winner_order()
    world.store.by_request[REQUEST_A] = original

    result = await world.handler().handle(command(REQUEST_A))

    assert fields_of(result) == reply_of(original)
    assert (result.initial_amount, result.initial_discount, result.total_amount) == (
        Money(3000, "EUR"),
        Money(100, "EUR"),
        Money(2900, "EUR"),
    )
    assert world.log == ["uow.begin", "orders.find_by_request_id", "uow.commit"]
    assert world.store.saved == []  # no write


async def test_ri2_a_known_request_id_with_a_non_zero_order_discount_is_refused_and_not_replayed() -> (  # noqa: E501
    None
):
    """RI2's valid-request condition: the order-discount refusal comes BEFORE the replay lookup
    (#7 `place-order.handler.ts:68-77`; #8 looks up first, `PlaceOrderCommandHandler.cs:39-50`).
    The stored order exists, yet the request is refused: no lookup, no reply, no write."""
    world = World(replay_forbidden=True)
    world.store.by_request[REQUEST_A] = winner_order()
    refused = replace(command(REQUEST_A), order_discount=500)

    try:
        reply = await world.handler().handle(refused)
    except OrderDiscountNotSupportedError:
        pass
    else:
        pytest.fail(
            f"RI2: a non-zero orderDiscount is refused before the replay lookup; got {reply}"
        )

    assert world.store.lookups == [], "the refusal precedes the replay lookup"
    assert world.log == [], "no transaction, no catalog, no stock"
    assert world.store.saved == []


async def test_ri4_no_request_id_performs_no_lookup() -> None:
    world = World()

    result = await world.handler().handle(command(None))

    assert world.store.lookups == []
    assert "orders.find_by_request_id" not in world.log
    assert result.order_reference == OrderNumber("ORD-000042")
    assert len(world.store.saved) == 1
    assert world.store.saved[0][1] is None  # saved with no request id


async def test_ri1_a_first_request_id_is_handed_to_save() -> None:
    world = World()

    await world.handler().handle(command(REQUEST_A))

    assert [request_id for _, request_id in world.store.saved] == [REQUEST_A]


async def test_ri5_the_causation_id_is_the_request_id_when_supplied_and_fresh_when_omitted() -> (
    None
):
    first, second, omitted_a, omitted_b = World(), World(), World(), World()

    await first.handler().handle(command(REQUEST_A))
    await second.handler().handle(command(REQUEST_B))
    await omitted_a.handler().handle(command(None))
    await omitted_b.handler().handle(command(None))

    def causation(world: World) -> UUID:
        [(order, _)] = world.store.saved
        [event] = order.domain_events
        return narrow(event).causation_id.value

    assert causation(first) == REQUEST_A
    assert causation(second) == REQUEST_B  # a second, distinct id: a constant would fail here
    fresh = {causation(omitted_a), causation(omitted_b)}
    assert len(fresh) == 2  # fresh per order
    assert fresh.isdisjoint({REQUEST_A, REQUEST_B})
