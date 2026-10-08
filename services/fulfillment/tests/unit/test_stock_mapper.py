"""D8: a unit count the column cannot hold is refused where the mapper assigns it (FS20, L5).

No database: the range guard is an ORM attribute event, so building mapped instances is enough.
"""

import uuid
from datetime import UTC, datetime

import pytest

from otc_fulfillment.domain.reservation import ReservationStatus, ReservationView
from otc_fulfillment.domain.snapshot import StockItemSnapshot
from otc_fulfillment.domain.stock_item import StockItem
from otc_fulfillment.infrastructure.persistence import stock_mapper
from otc_fulfillment.infrastructure.persistence.models import Stock
from otc_fulfillment.infrastructure.persistence.range_guards import QuantityOutOfRangeError
from otc_shared_kernel import UniqueId

NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)
INT32_OVER = 2**31


def _item(units: int, reserved: int) -> StockItem:
    return StockItem.rehydrate(
        StockItemSnapshot(
            id=UniqueId(uuid.UUID(int=0xA1)),
            company_code="ACME-CO",
            product_code="PRD-A1",
            units=units,
            reserved_units=reserved,
            low_stock_threshold=3,
            reservations=(),
        )
    )


def _row() -> Stock:
    return Stock(
        id=uuid.UUID(int=0xA1),
        company_code="ACME-CO",
        product_code="PRD-A1",
        units=10,
        reserved_units=4,
        low_stock_threshold=3,
        created_at=NOW,
        updated_at=NOW,
    )


def test_a_unit_count_beyond_the_column_is_refused_when_the_mapper_assigns_it() -> None:
    with pytest.raises(QuantityOutOfRangeError) as units:
        stock_mapper.apply_item(_item(INT32_OVER, 4), _row(), NOW)
    assert units.value.code == "quantity.out_of_range"
    assert units.value.where == "stock.units"

    with pytest.raises(QuantityOutOfRangeError) as reserved:
        stock_mapper.apply_item(_item(INT32_OVER + 5, INT32_OVER), _row(), NOW)
    assert reserved.value.code == "quantity.out_of_range"

    # control: the largest value the column holds is assigned
    row = _row()
    assert stock_mapper.apply_item(_item(INT32_OVER - 1, 4), row, NOW) is True
    assert row.units == INT32_OVER - 1


def test_a_reservation_beyond_the_column_is_refused_by_the_constructor() -> None:
    item = _item(10, 4)
    view = ReservationView(
        id=UniqueId(uuid.UUID(int=0x71)),
        order_reference="ORD-000042",
        retailer_code="RET-9",
        units=INT32_OVER,
        status=ReservationStatus.RESERVED,
    )
    with pytest.raises(QuantityOutOfRangeError):
        stock_mapper.new_reservation_row(item, view, NOW)
