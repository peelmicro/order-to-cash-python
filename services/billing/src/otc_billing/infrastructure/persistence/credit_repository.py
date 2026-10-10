"""`SqlAlchemyCreditRepository`: the lock protocol, `save`, and the outbox drain (design 6, 9.1).

The order of the three reads is load-bearing (BC35, L7 - L12), at a pinned `READ COMMITTED` (the
transaction pins it):

1. the line row, ORM `select(Credit)...with_for_update()` (plain `FOR UPDATE`, not `key share`: it
   also blocks an unlocked ledger insert through the foreign key, measured), waits for the line's
   writer and returns the LATEST committed version;
2. THEN the committed-exposure scalar. PostgreSQL refuses `FOR UPDATE` with an aggregate, so this
   statement cannot lock: it is a NEW statement with a fresh snapshot issued after the lock was
   granted, so it sees what the previous holder committed. Swapped with step 1 it would read a stale
   sum; under `REPEATABLE READ` it would read a stale sum SILENTLY. It is the only textual SQL, a
   `SELECT`: `CAST(... AS bigint)` makes it an `int` (PostgreSQL's `SUM(bigint)` is `numeric`, which
   asyncpg decodes as `Decimal`), an out-of-range sum raises SQLSTATE `22003` on THIS statement only
   and becomes `CreditLedgerOverflowError`, and a `type` outside the closed set is counted rather
   than summed as zero (BC37);
3. THEN the order's entries.

No `update(`, `delete(`, `on_conflict_*` or textual DML exists in this service outside
`invoice_number_allocator.py`'s counter statements and the outbox relay's `update(Outbox)` stamp
(`outbox/relay.py`, review N5): every row written is a new ledger or outbox row
(L19), and the loaded `Credit` row is never assigned.
"""

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from otc_billing.application.ports.clock import Clock
from otc_billing.domain.buyer_credit import BuyerCredit
from otc_billing.domain.errors import CreditLedgerOverflowError, UnknownCreditEntryTypeError
from otc_billing.infrastructure.outbox.relay import sqlstate_of
from otc_billing.infrastructure.outbox.writer import OutboxWriter
from otc_billing.infrastructure.persistence import credit_mapper
from otc_billing.infrastructure.persistence.models import Credit, CreditItem

NUMERIC_VALUE_OUT_OF_RANGE = "22003"

_COMMITTED_EXPOSURE = text(
    "SELECT CAST(COALESCE(SUM(CASE type WHEN 'hold' THEN amount WHEN 'release' THEN -amount "
    "ELSE 0 END), 0) AS bigint) AS committed_exposure, "
    "count(*) FILTER (WHERE type NOT IN ('hold', 'consume', 'release')) AS unknown_types "
    "FROM credit_items WHERE credit_id = :credit_id"
)


class SqlAlchemyCreditRepository:
    def __init__(self, session: AsyncSession, outbox: OutboxWriter, clock: Clock) -> None:
        self._session = session
        self._outbox = outbox
        self._clock = clock
        self._loaded: BuyerCredit | None = None

    async def _committed_exposure(self, line: Credit) -> int:
        try:
            result = await self._session.execute(_COMMITTED_EXPOSURE, {"credit_id": line.id})
        except DBAPIError as error:
            if sqlstate_of(error) == NUMERIC_VALUE_OUT_OF_RANGE:
                raise CreditLedgerOverflowError(
                    f"committed exposure of credit line {line.code}"
                ) from error
            raise
        committed, unknown_types = result.one()
        if unknown_types:
            raise UnknownCreditEntryTypeError(
                f"{unknown_types} row(s) of credit line {line.code} carry a type outside "
                "hold/consume/release"
            )
        committed_exposure: int = committed
        return committed_exposure

    async def lock_for_order(
        self, retailer_code: str, company_code: str, order_reference: str
    ) -> BuyerCredit | None:
        line = await self._session.scalar(
            select(Credit)
            .where(Credit.retailer_code == retailer_code, Credit.company_code == company_code)
            .with_for_update()
        )
        if line is None:
            return None
        committed_exposure = await self._committed_exposure(line)
        items = list(
            await self._session.scalars(
                select(CreditItem)
                .where(
                    CreditItem.credit_id == line.id, CreditItem.order_reference == order_reference
                )
                .order_by(CreditItem.created_at, CreditItem.id)
            )
        )
        credit = BuyerCredit.rehydrate(
            credit_mapper.credit_snapshot(line, committed_exposure, items)
        )
        self._loaded = credit
        return credit

    async def save(self, credit: BuyerCredit) -> None:
        now = self._clock.now()
        for entry in credit.appended_entries:
            self._session.add(credit_mapper.new_item_row(entry, credit.id, now))
        # The outbox rows join THIS session and transaction (R13); the writer flushes per row.
        await self._outbox.write(self._session, credit.domain_events)
        await self._session.flush()

    def clear_saved_events(self) -> None:
        """Forget the events of the loaded line. Called by `run()` only AFTER the commit."""
        if self._loaded is not None:
            self._loaded.clear_domain_events()
