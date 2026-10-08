"""`SqlAlchemyStockReads`: availability, the paged list, SA-4's step-0 pre-read (`design.md` 6.1,
9.3) and F8's despatch fast path (feature 18).

Each call opens and closes its own short session. A plain `SELECT` under `READ COMMITTED` never
waits for a row lock and takes none, which is R31's "non-locking"; nothing here writes.
"""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_fulfillment.application.messages import (
    LineAvailability,
    StockAvailability,
    StockPage,
    StockViewData,
)
from otc_fulfillment.domain.snapshot import DespatchSnapshot
from otc_fulfillment.infrastructure.persistence.despatch_repository import load_despatch
from otc_fulfillment.infrastructure.persistence.models import Reservation as ReservationRow
from otc_fulfillment.infrastructure.persistence.models import Stock


class SqlAlchemyStockReads:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def availability(
        self, company_code: str, lines: Sequence[tuple[str, int]]
    ) -> StockAvailability:
        codes = list(dict.fromkeys(code for code, _ in lines))
        async with self._sessions() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            rows = (
                await session.execute(
                    select(Stock.product_code, Stock.units, Stock.reserved_units).where(
                        Stock.company_code == company_code, Stock.product_code.in_(codes)
                    )
                )
            ).all()
        available_by_code = {row.product_code: row.units - row.reserved_units for row in rows}
        # An unknown product is `available: 0, sufficient: false`, never an error (FS22).
        results = tuple(
            LineAvailability(
                product_code=code,
                requested=requested,
                available=available_by_code.get(code, 0),
                sufficient=requested <= available_by_code.get(code, 0),
            )
            for code, requested in lines
        )
        return StockAvailability(available=all(r.sufficient for r in results), lines=results)

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        company_code: str | None,
        product_code: str | None,
        below_threshold: bool | None,
    ) -> StockPage:
        filters = []
        if company_code is not None:
            filters.append(Stock.company_code == company_code)
        if product_code is not None:
            filters.append(Stock.product_code == product_code)
        if below_threshold:
            filters.append(Stock.units - Stock.reserved_units < Stock.low_stock_threshold)
        async with self._sessions() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            total = await session.scalar(select(func.count()).select_from(Stock).where(*filters))
            rows = (
                await session.scalars(
                    select(Stock)
                    .where(*filters)
                    .order_by(Stock.company_code, Stock.product_code)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        return StockPage(
            items=tuple(
                StockViewData(
                    company_code=row.company_code,
                    product_code=row.product_code,
                    units=row.units,
                    reserved_units=row.reserved_units,
                    low_stock_threshold=row.low_stock_threshold,
                )
                for row in rows
            ),
            page=page,
            page_size=page_size,
            total=total or 0,
        )

    async def stock_keys_of_order(self, order_reference: str) -> tuple[tuple[str, str], ...]:
        async with self._sessions() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            rows = (
                await session.execute(
                    select(Stock.company_code, Stock.product_code)
                    .join(ReservationRow, ReservationRow.stock_id == Stock.id)
                    .where(ReservationRow.order_reference == order_reference)
                    .distinct()
                )
            ).all()
        return tuple((row.company_code, row.product_code) for row in rows)

    async def despatch_of_order(self, order_reference: str) -> DespatchSnapshot | None:
        async with self._sessions() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            return await load_despatch(session, order_reference)
