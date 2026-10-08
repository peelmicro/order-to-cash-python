"""E5 / FS14: an unknown product on ANY line raises before anything is replenished."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from otc_fulfillment.application.messages import ReplenishStockCommand, StockLine
from otc_fulfillment.application.ports.stock_store import StockTransaction
from otc_fulfillment.application.scope import FulfillmentScope
from otc_fulfillment.application.stock_replenishment import UnknownStockItemError, replenish
from otc_fulfillment.domain.snapshot import StockItemSnapshot
from otc_fulfillment.domain.stock_item import StockItem
from otc_shared_kernel import Quantity, UniqueId


def item(code: str, units: int, number: int) -> StockItem:
    return StockItem.rehydrate(
        StockItemSnapshot(
            id=UniqueId(uuid.UUID(int=number)),
            company_code="ACME-CO",
            product_code=code,
            units=units,
            reserved_units=1,
            low_stock_threshold=2,
            reservations=(),
        )
    )


class FakeRepository:
    def __init__(self, items: dict[str, StockItem]) -> None:
        self.items = items
        self.saved = 0

    async def lock_for_replenish(
        self, company_code: str, product_codes: Any
    ) -> dict[str, StockItem]:
        return {c: self.items[c] for c in product_codes if c in self.items}

    async def save(self) -> None:
        self.saved += 1


class FakeTransactions:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository

    @property
    def tx(self) -> StockTransaction:
        return self  # type: ignore[return-value]

    async def run[T](self, work: Callable[[StockTransaction], Awaitable[T]]) -> T:
        return await work(self.tx)


def scope(repository: FakeRepository) -> FulfillmentScope:
    return FulfillmentScope(
        transactions=FakeTransactions(repository),
        reads=object(),  # type: ignore[arg-type]
        clock=object(),  # type: ignore[arg-type]
        ids=object(),  # type: ignore[arg-type]
    )


def command(*lines: tuple[str, int]) -> ReplenishStockCommand:
    return ReplenishStockCommand(
        company_code="ACME-CO",
        lines=tuple(StockLine(product_code=c, units=Quantity(n)) for c, n in lines),
    )


async def test_an_unknown_product_on_any_line_raises_before_anything_is_replenished() -> None:
    known = item("PRD-A1", 10, 0xA1)
    repository = FakeRepository({"PRD-A1": known})

    # the KNOWN line comes first: a handler that replenishes as it goes would already have added 7
    with pytest.raises(UnknownStockItemError) as refusal:
        await replenish(command(("PRD-A1", 7), ("PRD-Z9", 3)), scope(repository))

    assert refusal.value.product_code == "PRD-Z9"
    assert known.units == 10, "no line was replenished"
    assert repository.saved == 0


async def test_every_line_known_replenishes_all_sums_repeated_lines_and_saves_once() -> None:
    a, b = item("PRD-A1", 10, 0xA1), item("PRD-B2", 20, 0xB2)
    repository = FakeRepository({"PRD-A1": a, "PRD-B2": b})

    result = await replenish(
        command(("PRD-B2", 5), ("PRD-A1", 7), ("PRD-B2", 6)), scope(repository)
    )

    assert (a.units, b.units) == (17, 31)
    assert repository.saved == 1
    assert [(v.product_code, v.units, v.reserved_units) for v in result.items] == [
        ("PRD-B2", 31, 1),
        ("PRD-A1", 17, 1),
    ]
