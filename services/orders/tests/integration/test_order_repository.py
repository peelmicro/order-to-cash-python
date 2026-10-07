"""The Order repository against a real PostgreSQL (feature 14 task 3.8; #7 D5, #8 D2's lesson).

Every fixture value is distinct from every other (two lines differing in product, quantity, price
and discount; non-round totals 8465 / 350 / 8115), so a mapper that reads the wrong column, or a
total computed from the wrong term, cannot coincide with the right answer. Loop scope: the default
(function); the engine, the sessionmaker and every session live and die inside the test's loop.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from otc_orders.domain.order import Order
from otc_orders.domain.order_line import OrderLineInput
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.compensation_step import (
    CompensationStep,
    CompensationStepKind,
)
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.persistence.order_repository import ReferenceDataMissingError
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_shared_kernel import Money, OrderNumber, Quantity, UniqueId

INSTANT = datetime(2026, 10, 5, 12, 0, 0, 123000, tzinfo=UTC)


def _line_facts(order: Order) -> dict[UniqueId, tuple[str, str | None, int, int, int]]:
    return {
        line.id: (
            line.product_code,
            line.description,
            line.quantity.value,
            line.unit_price.amount,
            line.line_discount.amount,
        )
        for line in order.lines
    }


async def stored_totals(dsn: str, order: Order) -> tuple[int, int, int]:
    """The three derived total columns, read raw: they are written but never read into the
    aggregate (they are derived from the lines on load), so only SQL can see them."""
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT initial_amount, initial_discount, total_amount FROM orders WHERE id = $1",
            order.id.value,
        )
    finally:
        await conn.close()
    assert row is not None
    return row["initial_amount"], row["initial_discount"], row["total_amount"]


async def test_a_placed_order_round_trips_through_save_and_get_by_id(
    uow: SqlAlchemyUnitOfWork, place_order: Any, migrated_db: Any
) -> None:
    placed: Order = place_order(
        notes="deliver to dock 4", occurred_at=INSTANT, order_date=INSTANT - timedelta(hours=1)
    )
    async with uow.begin() as tx:
        await tx.orders.save(placed)

    async with uow.begin() as tx:
        loaded = await tx.orders.get_by_id(placed.id)

    assert loaded is not None
    assert loaded is not placed
    assert loaded.id == placed.id
    assert loaded.order_reference == OrderNumber("ORD-000001")
    assert loaded.order_date == INSTANT - timedelta(hours=1)
    assert (loaded.retailer_code, loaded.company_code) == ("RET-01", "CMP-01")
    assert loaded.buyer_gln.value == "4012345000009"
    assert loaded.supplier_gln.value == "5412345000006"
    assert loaded.currency == "EUR"
    assert loaded.status is OrderStatus.PLACED
    assert loaded.cancellation_reason is None
    assert loaded.notes == "deliver to dock 4"
    assert _line_facts(loaded) == _line_facts(placed)
    assert (
        loaded.initial_amount,
        loaded.initial_discount,
        loaded.total_amount,
    ) == (Money(8465, "EUR"), Money(350, "EUR"), Money(8115, "EUR"))
    assert (loaded.created_at, loaded.updated_at) == (INSTANT, INSTANT)
    assert loaded.domain_events == (), "rehydrating raises no event"
    assert await stored_totals(migrated_db.dsn, placed) == (8465, 350, 8115), "the written totals"


async def test_a_cancelled_order_round_trips_through_get_by_reference_with_notes_reason_and_line_discounts(  # noqa: E501
    uow: SqlAlchemyUnitOfWork, place_order: Any
) -> None:
    placed: Order = place_order(
        notes="fragile goods", occurred_at=INSTANT, order_reference="ORD-000007"
    )
    async with uow.begin() as tx:
        await tx.orders.save(placed)

    cancelled_at = INSTANT + timedelta(minutes=5)
    async with uow.begin() as tx:
        order = await tx.orders.get_by_id(placed.id)
        assert order is not None
        order.cancel(
            reason=CancellationReason.STOCK_REJECTED,
            compensation_steps=[
                CompensationStep(
                    step=CompensationStepKind.STOCK_RELEASED,
                    event_id=UniqueId.new(),
                    event_type="stock.released.v1",
                    occurred_at=cancelled_at,
                )
            ],
            occurred_at=cancelled_at,
            causation_id=UniqueId.new(),
            note="the warehouse said no",
        )
        await tx.orders.save(order)

    async with uow.begin() as tx:
        loaded = await tx.orders.get_by_reference(OrderNumber("ORD-000007"))

    assert loaded is not None
    assert loaded.id == placed.id
    assert loaded.status is OrderStatus.CANCELLED
    assert loaded.cancellation_reason is CancellationReason.STOCK_REJECTED
    assert loaded.notes == "fragile goods"
    assert loaded.updated_at == cancelled_at
    assert loaded.created_at == INSTANT
    # each line's discount, price and quantity are read from their own columns
    assert _line_facts(loaded) == _line_facts(placed)
    assert {line.line_discount.amount for line in loaded.lines} == {250, 100}
    assert {line.unit_price.amount for line in loaded.lines} == {1999, 1234}


async def test_get_by_id_of_an_unknown_order_is_none(uow: SqlAlchemyUnitOfWork) -> None:
    async with uow.begin() as tx:
        assert await tx.orders.get_by_id(UniqueId.new()) is None
        assert await tx.orders.get_by_reference(OrderNumber("ORD-999999")) is None


async def test_save_of_a_loaded_order_inserts_updates_and_deletes_its_changed_lines(
    uow: SqlAlchemyUnitOfWork, place_order: Any, migrated_db: Any
) -> None:
    placed: Order = place_order(occurred_at=INSTANT)
    line_a, line_b = placed.lines
    async with uow.begin() as tx:
        await tx.orders.save(placed)

    later = INSTANT + timedelta(minutes=3)
    async with uow.begin() as tx:
        order = await tx.orders.get_by_id(placed.id)
        assert order is not None
        added = order.add_line(
            product_code="SKU-C",
            description="Gamma crate",
            quantity=Quantity(5),
            unit_price=Money(777, "EUR"),
            line_discount=Money(33, "EUR"),
            occurred_at=later,
        )
        order.remove_line(line_id=line_a.id, occurred_at=later)
        order.change_line(
            line_id=line_b.id,
            quantity=Quantity(9),
            unit_price=Money(1500, "EUR"),
            line_discount=Money(40, "EUR"),
            occurred_at=later,
        )
        await tx.orders.save(order)

    async with uow.begin() as tx:
        reloaded = await tx.orders.get_by_id(placed.id)
    assert reloaded is not None
    assert {line.id for line in reloaded.lines} == {line_b.id, added}, "A removed, C added"
    facts = _line_facts(reloaded)
    assert facts[line_b.id] == ("SKU-B", None, 9, 1500, 40), "B changed in place"
    assert facts[added] == ("SKU-C", "Gamma crate", 5, 777, 33)
    # 9 x 1500 + 5 x 777 = 17385 ; discounts 40 + 33 = 73 ; total 17312
    assert reloaded.total_amount == Money(17312, "EUR")
    assert reloaded.updated_at == later

    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        rows = await conn.fetch("SELECT id FROM order_items WHERE order_id = $1", placed.id.value)
        stored_total = await conn.fetchval(
            "SELECT total_amount FROM orders WHERE id = $1", placed.id.value
        )
    finally:
        await conn.close()
    assert {row["id"] for row in rows} == {line_b.id.value, added.value}
    assert stored_total == 17312
    assert await stored_totals(migrated_db.dsn, placed) == (17385, 73, 17312), "totals rewritten"


async def test_a_confirmed_order_saved_for_the_first_time_keeps_created_at_and_updated_at_apart(
    uow: SqlAlchemyUnitOfWork, place_order: Any
) -> None:
    """The insert path with an aggregate that has already moved: `created_at` is the placement,
    `updated_at` the last transition. Any fixture where the two coincide cannot tell them apart."""
    order: Order = place_order(occurred_at=INSTANT)
    confirmed_at = INSTANT + timedelta(minutes=3)
    order.mark_stock_reserved(occurred_at=INSTANT + timedelta(minutes=1))
    order.approve_credit(occurred_at=INSTANT + timedelta(minutes=2))
    order.confirm(occurred_at=confirmed_at, causation_id=UniqueId.new())
    async with uow.begin() as tx:
        await tx.orders.save(order)
    async with uow.begin() as tx:
        loaded = await tx.orders.get_by_id(order.id)
    assert loaded is not None
    assert loaded.status is OrderStatus.CONFIRMED
    assert loaded.created_at == INSTANT
    assert loaded.updated_at == confirmed_at


async def test_save_of_an_order_with_an_unknown_reference_code_names_the_table_and_the_code(
    uow: SqlAlchemyUnitOfWork, place_order: Any
) -> None:
    unknown_line = OrderLineInput(
        product_code="SKU-NOPE",
        description=None,
        quantity=Quantity(1),
        unit_price=Money(10, "EUR"),
        line_discount=Money(0, "EUR"),
    )
    order: Order = place_order(lines=[unknown_line], occurred_at=INSTANT)
    with pytest.raises(ReferenceDataMissingError) as raised:
        async with uow.begin() as tx:
            await tx.orders.save(order)
    assert (raised.value.table, raised.value.code) == ("products", "SKU-NOPE")


async def save_after_the_row_vanished(uow: SqlAlchemyUnitOfWork, order: Order, dsn: str) -> None:
    async with uow.begin() as tx:
        loaded = await tx.orders.get_by_id(order.id)
        assert loaded is not None
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute("DELETE FROM order_items")
            await conn.execute("DELETE FROM orders")
        finally:
            await conn.close()
        loaded.mark_stock_reserved(occurred_at=INSTANT + timedelta(minutes=1))
        await tx.orders.save(loaded)


async def test_save_of_a_loaded_order_whose_row_has_vanished_names_the_orders_table_and_its_id(
    uow: SqlAlchemyUnitOfWork, place_order: Any, migrated_db: Any
) -> None:
    placed: Order = place_order(occurred_at=INSTANT)
    async with uow.begin() as tx:
        await tx.orders.save(placed)
    with pytest.raises(ReferenceDataMissingError) as raised:
        await save_after_the_row_vanished(uow, placed, migrated_db.dsn)
    assert (raised.value.table, raised.value.code) == ("orders", str(placed.id))
