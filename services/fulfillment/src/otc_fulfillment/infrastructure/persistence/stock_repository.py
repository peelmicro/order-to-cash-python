"""`SqlAlchemyStockRepository`: the lock protocol, `save`, and the outbox drain (design 6, 9.1).

Every deciding read is an ORM `select(...).with_for_update()` at a pinned `READ COMMITTED` (the
transaction pins it): a locking read waits for the row's writer and then returns the LATEST
committed version, and each later statement takes a FRESH snapshot, so a reservation read issued
AFTER the stock lock sees what the writer committed. The ORDER of the two reads is therefore
load-bearing (L1): stock rows first, one statement each in `distinct_stock_keys` order (FS19), then
all of the order's reservations `ORDER BY id`.

The rows are tracked instances, so a change is an attribute assignment at flush (`stock_mapper`
is the only writer of the guarded columns); the repository itself writes no column.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from otc_fulfillment.application.ports.clock import Clock
from otc_fulfillment.application.ports.stock_store import (
    ConcurrentReservationChangeError,
    LockedStock,
    distinct_stock_keys,
)
from otc_fulfillment.domain.stock_item import StockItem
from otc_fulfillment.infrastructure.outbox.writer import OutboxWriter
from otc_fulfillment.infrastructure.persistence import stock_mapper
from otc_fulfillment.infrastructure.persistence.models import Reservation as ReservationRow
from otc_fulfillment.infrastructure.persistence.models import Stock


@dataclass(slots=True)
class _Loaded:
    item: StockItem
    row: Stock
    reservations: dict[UUID, ReservationRow] = field(default_factory=dict)


class SqlAlchemyStockRepository:
    def __init__(self, session: AsyncSession, outbox: OutboxWriter, clock: Clock) -> None:
        self._session = session
        self._outbox = outbox
        self._clock = clock
        self._loaded: dict[UUID, _Loaded] = {}

    # ------------------------------------------------------------------------------ the locks

    async def _lock_stock_rows(self, keys: Sequence[tuple[str, str]]) -> list[Stock]:
        rows: list[Stock] = []
        for company_code, product_code in distinct_stock_keys(keys):
            row = await self._session.scalar(
                select(Stock)
                .where(Stock.company_code == company_code, Stock.product_code == product_code)
                .with_for_update()
            )
            if row is not None:
                rows.append(row)
        return rows

    async def _lock_reservations_of(self, order_reference: str) -> list[ReservationRow]:
        # ALL of the order's reservations, any status, any product (FS5). `ORDER BY id` so two
        # transactions locking the same rows lock them in one order.
        return list(
            await self._session.scalars(
                select(ReservationRow)
                .where(ReservationRow.order_reference == order_reference)
                .order_by(ReservationRow.id)
                .with_for_update()
            )
        )

    def _load(
        self, rows: Sequence[Stock], reservations: Sequence[ReservationRow]
    ) -> dict[str, StockItem]:
        items: dict[str, StockItem] = {}
        for row in rows:
            item = StockItem.rehydrate(stock_mapper.item_snapshot(row, reservations))
            self._loaded[row.id] = _Loaded(
                item=item,
                row=row,
                reservations={r.id: r for r in reservations if r.stock_id == row.id},
            )
            items[row.product_code] = item
        return items

    async def lock_for_reserve(
        self, company_code: str, product_codes: Sequence[str], order_reference: str
    ) -> LockedStock:
        rows = await self._lock_stock_rows([(company_code, code) for code in product_codes])
        reservations = await self._lock_reservations_of(order_reference)
        return LockedStock(
            items=self._load(rows, reservations),
            reservations_of_order=tuple(stock_mapper.reservation_snapshot(r) for r in reservations),
        )

    async def lock_order_items(
        self, order_reference: str, keys: Sequence[tuple[str, str]]
    ) -> LockedStock:
        rows = await self._lock_stock_rows(keys)
        reservations = await self._lock_reservations_of(order_reference)
        locked_ids = {row.id for row in rows}
        if any(r.stock_id not in locked_ids for r in reservations):
            raise ConcurrentReservationChangeError(order_reference)
        return LockedStock(
            items=self._load(rows, reservations),
            reservations_of_order=tuple(stock_mapper.reservation_snapshot(r) for r in reservations),
        )

    async def lock_for_replenish(
        self, company_code: str, product_codes: Sequence[str]
    ) -> dict[str, StockItem]:
        rows = await self._lock_stock_rows([(company_code, code) for code in product_codes])
        return self._load(rows, [])

    # ------------------------------------------------------------------------------- the write

    async def save(self) -> None:
        now = self._clock.now()
        events: list[object] = []
        for loaded in self._loaded.values():
            stock_mapper.apply_item(loaded.item, loaded.row, now)
            for view in loaded.item.reservations:
                row = loaded.reservations.get(view.id.value)
                if row is None:
                    created = stock_mapper.new_reservation_row(loaded.item, view, now)
                    self._session.add(created)
                    loaded.reservations[view.id.value] = created
                else:
                    stock_mapper.apply_reservation(view, row, now)
            events.extend(loaded.item.domain_events)
        # The outbox rows join THIS session and transaction (R13); the writer flushes per row.
        await self._outbox.write(self._session, events)
        await self._session.flush()

    def clear_saved_events(self) -> None:
        """Forget the events of every loaded item. Called by `run()` only AFTER the commit."""
        for loaded in self._loaded.values():
            loaded.item.clear_domain_events()
