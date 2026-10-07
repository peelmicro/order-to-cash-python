"""`PlaceOrderCommandHandler` (feature 15): the order of its steps, and what a refusal leaves.

No broker, no database: the ports are in-memory fakes that LOG every call into one list, so the
order of the steps is an assertion (`reference data -> stock check -> begin -> allocate -> save`),
and "no transaction was opened" is a counted fact, not an absence. Loop scope: default (function).

Money fixtures are pairwise distinct and non-zero: initial amount 8465, discounts 350, total 8115.
"""

from collections.abc import AsyncIterator, Collection, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_orders.application.commands.place_order import (
    OrderDiscountNotSupportedError,
    PlaceOrderCommand,
    PlaceOrderCommandHandler,
    PlaceOrderLine,
    ReferenceDataNotFoundError,
    StockUnavailableError,
)
from otc_orders.application.ports.reference_catalog import PartyReference, ProductReference
from otc_orders.application.ports.stock_availability import (
    StockAvailabilityLine,
    StockAvailabilityLineResult,
    StockAvailabilityResult,
    StockCheckBusinessError,
    StockCheckTimeoutError,
    StockCheckTransportError,
)
from otc_orders.application.scope import MissingBindingError, OrdersScope
from otc_orders.domain.order import Order
from otc_orders.infrastructure.outbox.payloads import narrow
from otc_shared_kernel import GLN, DomainError, Money, OrderNumber, Quantity

NOW = datetime(2026, 10, 6, 8, 30, 0, 123000, tzinfo=UTC)
RETAILER_GLN = "4012345000009"
COMPANY_GLN = "5412345000006"


class Log(list[str]):
    pass


class FakeCatalog:
    def __init__(self, log: Log, *, products: Mapping[str, ProductReference] | None = None) -> None:
        self.log = log
        self.retailers = {"RET-01": PartyReference("RET-01", GLN(RETAILER_GLN))}
        self.companies = {"CMP-01": PartyReference("CMP-01", GLN(COMPANY_GLN))}
        self.currencies = {"EUR", "USD"}
        self.products = dict(
            products
            or {
                "SKU-A": ProductReference("SKU-A", "Alpha pallet", Money(777, "EUR")),
                "SKU-B": ProductReference("SKU-B", None, Money(1234, "EUR")),
            }
        )
        self.asked_products: list[tuple[str, ...]] = []

    async def find_retailer(self, retailer_code: str) -> PartyReference | None:
        self.log.append("catalog.retailer")
        return self.retailers.get(retailer_code)

    async def find_company(self, company_code: str) -> PartyReference | None:
        self.log.append("catalog.company")
        return self.companies.get(company_code)

    async def currency_exists(self, currency_code: str) -> bool:
        self.log.append("catalog.currency")
        return currency_code in self.currencies

    async def find_products(self, product_codes: Collection[str]) -> Mapping[str, ProductReference]:
        self.log.append("catalog.products")
        self.asked_products.append(tuple(product_codes))
        return {c: self.products[c] for c in product_codes if c in self.products}


class FakeStock:
    def __init__(self, log: Log) -> None:
        self.log = log
        self.outcome: StockAvailabilityResult | Exception = StockAvailabilityResult(True, ())
        self.asked: list[tuple[str, tuple[StockAvailabilityLine, ...]]] = []

    async def check(
        self, company_code: str, lines: Sequence[StockAvailabilityLine]
    ) -> StockAvailabilityResult:
        self.log.append("stock.check")
        self.asked.append((company_code, tuple(lines)))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeOrders:
    def __init__(self, log: Log, saved: list[Order], fail: bool) -> None:
        self._log, self._saved, self._fail = log, saved, fail

    async def save(self, order: Order) -> None:
        self._log.append("orders.save")
        if self._fail:
            raise RuntimeError("the insert failed")
        self._saved.append(order)

    async def get_by_id(self, order_id: Any) -> Order | None:
        raise NotImplementedError

    async def get_by_id_for_update(self, order_id: Any) -> Order | None:
        raise NotImplementedError  # feature 16: the saga's load; the place path never takes it

    async def get_by_reference(self, reference: OrderNumber) -> Order | None:
        raise NotImplementedError


class FakeAllocator:
    def __init__(self, log: Log) -> None:
        self._log = log

    async def next_number(self) -> OrderNumber:
        self._log.append("allocate")
        return OrderNumber("ORD-000042")


class FakeTransaction:
    def __init__(self, log: Log, saved: list[Order], fail_save: bool) -> None:
        self.orders = FakeOrders(log, saved, fail_save)
        self.order_numbers = FakeAllocator(log)
        # feature 16 added two members to `OrdersTransaction`; the place path touches neither
        self.saga_commands: Any = None
        self.ignored_facts: Any = None


class FakeUnitOfWork:
    def __init__(self, log: Log) -> None:
        self.log = log
        self.opened = 0
        self.committed = 0
        self.rolled_back = 0
        self.saved: list[Order] = []
        self.fail_save = False

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[FakeTransaction]:
        self.opened += 1
        self.log.append("uow.begin")
        try:
            yield FakeTransaction(self.log, self.saved, self.fail_save)
        except BaseException:
            self.rolled_back += 1
            self.log.append("uow.rollback")
            raise
        self.committed += 1
        self.log.append("uow.commit")


class FixedClock:
    def now(self) -> datetime:
        return NOW


class World:
    def __init__(self) -> None:
        self.log = Log()
        self.catalog = FakeCatalog(self.log)
        self.stock = FakeStock(self.log)
        self.uow = FakeUnitOfWork(self.log)
        self.scope = OrdersScope(
            unit_of_work=self.uow, catalog=self.catalog, stock=self.stock, clock=FixedClock()
        )

    def handler(self) -> PlaceOrderCommandHandler:
        return PlaceOrderCommandHandler(self.scope)


def command(**changes: Any) -> PlaceOrderCommand:
    fields: dict[str, Any] = {
        "request_id": None,
        "retailer_code": "RET-01",
        "company_code": "CMP-01",
        "currency": "EUR",
        "lines": (
            PlaceOrderLine("SKU-A", Quantity(3), unit_price=1999, line_discount=250),
            PlaceOrderLine("SKU-B", Quantity(2), unit_price=1234, line_discount=100),
        ),
        "order_discount": None,
        "notes": "dock 4",
    }
    return PlaceOrderCommand(**(fields | changes))


@pytest.fixture
def world() -> World:
    return World()


async def test_the_steps_run_in_the_designed_order_and_the_transaction_opens_last(
    world: World,
) -> None:
    await world.handler().handle(command())

    assert world.log == [
        "catalog.retailer",
        "catalog.company",
        "catalog.currency",
        "catalog.products",
        "stock.check",
        "uow.begin",
        "allocate",
        "orders.save",
        "uow.commit",
    ]


async def test_the_reply_carries_three_distinct_money_values_each_from_its_own_source(
    world: World,
) -> None:
    result = await world.handler().handle(command())

    assert result.order_reference == OrderNumber("ORD-000042")
    assert (result.initial_amount, result.initial_discount, result.total_amount) == (
        Money(8465, "EUR"),
        Money(350, "EUR"),
        Money(8115, "EUR"),
    )
    [saved] = world.uow.saved
    assert result.order_id == saved.id
    assert result.order_date == NOW == saved.order_date
    assert (saved.initial_amount, saved.initial_discount, saved.total_amount) == (
        result.initial_amount,
        result.initial_discount,
        result.total_amount,
    )


async def test_buyer_and_supplier_glns_come_from_the_retailer_and_the_company_respectively(
    world: World,
) -> None:
    await world.handler().handle(command())

    [saved] = world.uow.saved
    assert saved.buyer_gln == GLN(RETAILER_GLN)
    assert saved.supplier_gln == GLN(COMPANY_GLN)
    assert RETAILER_GLN != COMPANY_GLN


async def test_a_line_without_a_unit_price_takes_the_catalogue_price_and_description(
    world: World,
) -> None:
    lines = (
        PlaceOrderLine("SKU-A", Quantity(4), unit_price=None, line_discount=None),
        PlaceOrderLine("SKU-B", Quantity(1), unit_price=999, line_discount=11),
    )

    result = await world.handler().handle(command(lines=lines))

    [saved] = world.uow.saved
    first, second = saved.lines
    assert (first.unit_price, first.line_discount, first.description) == (
        Money(777, "EUR"),
        Money(0, "EUR"),
        "Alpha pallet",
    )
    assert (second.unit_price, second.line_discount, second.description) == (
        Money(999, "EUR"),
        Money(11, "EUR"),
        None,
    )
    assert result.initial_amount == Money(4 * 777 + 999, "EUR")
    assert result.initial_discount == Money(11, "EUR")


async def test_duplicate_product_codes_are_looked_up_once_in_first_seen_order(
    world: World,
) -> None:
    lines = (
        PlaceOrderLine("SKU-B", Quantity(1), 1, None),
        PlaceOrderLine("SKU-A", Quantity(1), 1, None),
        PlaceOrderLine("SKU-B", Quantity(1), 1, None),
    )

    await world.handler().handle(command(lines=lines))

    assert world.catalog.asked_products == [("SKU-B", "SKU-A")]
    assert [len(asked) for _, asked in world.stock.asked] == [3]


async def test_the_stock_check_carries_the_company_and_every_line_in_order(world: World) -> None:
    await world.handler().handle(command())

    assert world.stock.asked == [
        (
            "CMP-01",
            (
                StockAvailabilityLine("SKU-A", Quantity(3)),
                StockAvailabilityLine("SKU-B", Quantity(2)),
            ),
        )
    ]


@pytest.mark.parametrize(
    ("changes", "field", "value", "steps_before_refusal"),
    [
        ({"retailer_code": "NOPE"}, "retailerCode", "NOPE", ["catalog.retailer"]),
        ({"company_code": "NOPE"}, "companyCode", "NOPE", ["catalog.retailer", "catalog.company"]),
        (
            {"currency": "GBP"},
            "currency",
            "GBP",
            ["catalog.retailer", "catalog.company", "catalog.currency"],
        ),
    ],
)
async def test_an_unknown_party_or_currency_is_refused_before_the_stock_check_and_any_transaction(
    world: World,
    changes: dict[str, Any],
    field: str,
    value: str,
    steps_before_refusal: list[str],
) -> None:
    with pytest.raises(ReferenceDataNotFoundError) as refused:
        await world.handler().handle(command(**changes))

    assert (refused.value.field, refused.value.value) == (field, value)
    assert world.log == steps_before_refusal
    assert world.uow.opened == 0


async def test_an_unknown_product_names_the_first_unknown_line(world: World) -> None:
    lines = (
        PlaceOrderLine("SKU-A", Quantity(1), 1, None),
        PlaceOrderLine("SKU-GHOST", Quantity(1), 1, None),
        PlaceOrderLine("SKU-GHOST-2", Quantity(1), 1, None),
    )

    with pytest.raises(ReferenceDataNotFoundError) as refused:
        await world.handler().handle(command(lines=lines))

    assert (refused.value.field, refused.value.value) == ("productCode", "SKU-GHOST")
    assert "stock.check" not in world.log
    assert world.uow.opened == 0


async def test_a_non_zero_order_discount_is_refused_before_any_lookup(world: World) -> None:
    with pytest.raises(OrderDiscountNotSupportedError) as refused:
        await world.handler().handle(command(order_discount=500))

    assert refused.value.order_discount == 500
    assert str(refused.value).startswith("orderDiscount 5.00 EUR was supplied")
    assert world.log == []


@pytest.mark.parametrize("discount", [None, 0])
async def test_an_absent_or_zero_order_discount_is_accepted(world: World, discount: int) -> None:
    result = await world.handler().handle(command(order_discount=discount))

    assert result.total_amount == Money(8115, "EUR")


async def test_a_short_line_is_refused_with_only_the_short_lines_and_opens_no_transaction(
    world: World,
) -> None:
    world.stock.outcome = StockAvailabilityResult(
        False,
        (
            StockAvailabilityLineResult("SKU-A", 3, 50, True),
            StockAvailabilityLineResult("SKU-B", 2, 1, False),
        ),
    )

    with pytest.raises(StockUnavailableError) as refused:
        await world.handler().handle(command())

    assert refused.value.shortages == (StockAvailabilityLineResult("SKU-B", 2, 1, False),)
    assert world.uow.opened == 0
    assert "allocate" not in world.log


@pytest.mark.parametrize(
    "failure",
    [
        StockCheckTimeoutError("fulfillment.stock.check", 1500),
        StockCheckTransportError("fulfillment.stock.check", "no responder"),
        StockCheckBusinessError("fulfillment.stock.check", "INTERNAL_ERROR", "boom"),
    ],
    ids=["timeout", "transport", "responder's own error"],
)
async def test_a_stock_check_failure_propagates_unchanged_and_opens_no_transaction(
    world: World, failure: Exception
) -> None:
    world.stock.outcome = failure

    with pytest.raises(type(failure)) as refused:
        await world.handler().handle(command())

    assert refused.value is failure
    assert world.uow.opened == 0


async def test_a_failure_inside_the_transaction_rolls_it_back_and_propagates(
    world: World,
) -> None:
    world.uow.fail_save = True

    with pytest.raises(RuntimeError, match="the insert failed"):
        await world.handler().handle(command())

    assert (world.uow.opened, world.uow.committed, world.uow.rolled_back) == (1, 0, 1)
    assert world.log[-3:] == ["allocate", "orders.save", "uow.rollback"]


async def test_the_handler_validates_nothing_the_aggregate_validates(world: World) -> None:
    # a USD line price under an EUR order, caught by the aggregate (order.line_currency_mismatch)
    world.catalog.products["SKU-A"] = ProductReference("SKU-A", "Alpha", Money(5, "USD"))
    lines = (PlaceOrderLine("SKU-A", Quantity(1), unit_price=None, line_discount=None),)

    with pytest.raises(DomainError) as refused:
        await world.handler().handle(command(lines=lines))

    assert refused.value.code == "order.line_currency_mismatch"
    assert world.uow.rolled_back == 1


async def test_the_placed_event_is_caused_by_a_fresh_id_not_by_the_order(world: World) -> None:
    await world.handler().handle(command())

    [saved] = world.uow.saved
    [event] = (narrow(e) for e in saved.domain_events)
    assert event.causation_id != saved.id
    assert event.correlation_id == saved.id


def test_a_scope_with_an_unbound_port_is_refused_at_construction(world: World) -> None:
    with pytest.raises(MissingBindingError) as refused:
        OrdersScope(
            unit_of_work=world.uow,
            catalog=world.catalog,
            stock=None,  # type: ignore[arg-type]
            clock=FixedClock(),
        )

    assert refused.value.binding == "stock"
