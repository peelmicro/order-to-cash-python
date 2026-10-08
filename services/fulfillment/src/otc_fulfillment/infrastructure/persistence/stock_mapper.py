"""Rows <-> snapshots, and the ONLY writer of the guarded integer columns (`design.md` 9.2).

`stock.units`, `stock.reserved_units` and `reservations.units` are written ONLY by attribute
assignment on a mapped instance (`row.units = item.units`) or by the `Reservation(...)`
constructor, both here, with a plain `int`. That is what fires the range guard
(`range_guards.install_range_guards`): an `update(Stock).values(...)`, an `insert(...).values(...)`,
a `text()` or a SQL expression (`Stock.units + n`) bypasses it and surfaces as the engine's own
`DBAPIError`. The rows are already locked, so a value assignment is exact; no server-side increment
is needed. `tests/architecture/test_write_path_population.py` makes any other write path an
unclassified hit.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from otc_fulfillment.domain.reservation import ReservationView, parse_reservation_status
from otc_fulfillment.domain.snapshot import ReservationSnapshot, StockItemSnapshot
from otc_fulfillment.domain.stock_item import StockItem
from otc_fulfillment.infrastructure.persistence.models import Reservation as ReservationRow
from otc_fulfillment.infrastructure.persistence.models import Stock
from otc_shared_kernel import UniqueId


def _unique_id(value: UUID) -> UniqueId:
    """asyncpg hands back its own `UUID` subclass (`asyncpg.pgproto.pgproto.UUID`), which the
    domain's `type(...) is uuid.UUID` check refuses (measured in Orders' mapper); rebuild a plain
    `uuid.UUID`."""
    return UniqueId(UUID(int=value.int))


def reservation_snapshot(row: ReservationRow) -> ReservationSnapshot:
    return ReservationSnapshot(
        id=_unique_id(row.id),
        stock_id=_unique_id(row.stock_id),
        product_code=row.product_code,
        order_reference=row.order_reference,
        retailer_code=row.retailer_code,
        units=row.units,
        status=parse_reservation_status(row.status),
    )


def item_snapshot(row: Stock, reservations: Sequence[ReservationRow]) -> StockItemSnapshot:
    """The stored item with the reservations of `reservations` that sit on THIS stock row."""
    return StockItemSnapshot(
        id=_unique_id(row.id),
        company_code=row.company_code,
        product_code=row.product_code,
        units=row.units,
        reserved_units=row.reserved_units,
        low_stock_threshold=row.low_stock_threshold,
        reservations=tuple(reservation_snapshot(r) for r in reservations if r.stock_id == row.id),
    )


def apply_item(item: StockItem, row: Stock, now: datetime) -> bool:
    """Assign the item's counters to its (locked) row; True when anything changed."""
    changed = False
    if row.units != item.units:
        row.units = item.units
        changed = True
    if row.reserved_units != item.reserved_units:
        row.reserved_units = item.reserved_units
        changed = True
    if changed:
        row.updated_at = now
    return changed


def new_reservation_row(item: StockItem, view: ReservationView, now: datetime) -> ReservationRow:
    return ReservationRow(
        id=view.id.value,
        stock_id=item.id.value,
        company_code=item.company_code,
        retailer_code=view.retailer_code,
        product_code=item.product_code,
        order_reference=view.order_reference,
        units=view.units,
        status=view.status.value,
        created_at=now,
        updated_at=now,
    )


def apply_reservation(view: ReservationView, row: ReservationRow, now: datetime) -> bool:
    """A loaded reservation changes only its status (never its units); True when it moved."""
    if row.status == view.status.value:
        return False
    row.status = view.status.value
    row.updated_at = now
    return True
