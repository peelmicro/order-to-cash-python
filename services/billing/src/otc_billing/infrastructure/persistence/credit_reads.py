"""`SqlAlchemyCreditReads`: the paged credit list (`design.md` 6.1, 9.3).

Each call opens and closes its own short session. A plain `SELECT` under `READ COMMITTED` never
waits for a row lock and takes none (L13); nothing here writes. Three statements: the page of lines,
the count, and the page's ledger ROWS, folded per line through the same `summarise` the aggregate
uses (reading rows avoids PostgreSQL's `numeric` `SUM` altogether). `available_credit` is the limit
minus the committed exposure, never read from a column.
"""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_billing.application.messages import CreditPage, CreditViewData
from otc_billing.domain.credit_entry_type import parse_credit_entry_type
from otc_billing.domain.exposure import LedgerLine, summarise
from otc_billing.infrastructure.persistence.models import Credit, CreditItem

MAX_OFFSET = (1 << 63) - 1  # PostgreSQL's bigint OFFSET; asyncpg refuses anything above (G1, BI37)


class SqlAlchemyCreditReads:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        retailer_code: str | None,
        company_code: str | None,
    ) -> CreditPage:
        filters = []
        if retailer_code is not None:
            filters.append(Credit.retailer_code == retailer_code)
        if company_code is not None:
            filters.append(Credit.company_code == company_code)
        async with self._sessions() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            total = await session.scalar(select(func.count()).select_from(Credit).where(*filters))
            lines = (
                await session.scalars(
                    select(Credit)
                    .where(*filters)
                    .order_by(Credit.retailer_code, Credit.company_code)
                    .offset(min((page - 1) * page_size, MAX_OFFSET))
                    .limit(page_size)
                )
            ).all()
            ledger: dict[object, list[LedgerLine]] = defaultdict(list)
            if lines:
                rows = (
                    await session.execute(
                        select(
                            CreditItem.credit_id,
                            CreditItem.order_reference,
                            CreditItem.amount,
                            CreditItem.type,
                        ).where(CreditItem.credit_id.in_([line.id for line in lines]))
                    )
                ).all()
                for row in rows:
                    ledger[row.credit_id].append(
                        LedgerLine(
                            row.order_reference, parse_credit_entry_type(row.type), row.amount
                        )
                    )
        items: list[CreditViewData] = []
        for line in lines:
            summary = summarise(ledger[line.id])
            items.append(
                CreditViewData(
                    credit_code=line.code,
                    retailer_code=line.retailer_code,
                    company_code=line.company_code,
                    currency=line.currency_code,
                    credit_limit=line.credit_limit,
                    active_holds=summary.active_holds,
                    open_exposure=summary.open_exposure,
                    available_credit=line.credit_limit - summary.committed_exposure,
                )
            )
        return CreditPage(items=tuple(items), page=page, page_size=page_size, total=total or 0)
