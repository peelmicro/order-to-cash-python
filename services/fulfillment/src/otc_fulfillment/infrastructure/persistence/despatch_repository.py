"""`SqlAlchemyDespatchRepository`: the despatch advice, its lines and its fact (R36; F6, F7, F8).

* `find_by_order_reference` is a plain SELECT. Called INSIDE the transaction after the SA-4 lock it
  is F8's in-lock re-read: the transaction is pinned `READ COMMITTED` (`stock_transactions.run`), so
  each statement takes a fresh snapshot and sees what a concurrent despatch committed while this one
  waited (#8 id 54: #8's un-hinted re-read was correct only because RCSI made the snapshot
  statement-scoped; here the pin is explicit and armed). Called outside a transaction through
  `SqlAlchemyStockReads.despatch_of_order` it is F8's fast path.
* `save` is plain INSERTs (never an upsert): an advice is created once and never updated. The
  `despatches.order_reference` UNIQUE constraint is F8's last line of defence: a second advice for
  one order fails with `23505`, rolls the whole transaction back, and surfaces as
  `INTERNAL_ERROR` (transient: the caller asks again and the fast path answers).
* The lines are returned in the canonical order `(product_code, line id)` sorted in PYTHON, not by
  the database: the line table has no position column and a collation could order differently.
* The advice's events become outbox rows through the writer in THIS session and transaction (R13).
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from otc_fulfillment.application.ports.clock import Clock
from otc_fulfillment.domain.despatch_advice import DespatchAdvice, line_order_key
from otc_fulfillment.domain.snapshot import DespatchLineSnapshot, DespatchSnapshot
from otc_fulfillment.infrastructure.outbox.writer import OutboxWriter
from otc_fulfillment.infrastructure.persistence.models import Despatch, DespatchItem
from otc_shared_kernel import DespatchReference, UniqueId


def _unique_id(value: UUID) -> UniqueId:
    """asyncpg hands back its own `UUID` subclass, which the domain's `type(...) is uuid.UUID` check
    refuses (the same pitfall `stock_mapper` documents); rebuild a plain `uuid.UUID`."""
    return UniqueId(UUID(int=value.int))


async def load_despatch(session: AsyncSession, order_reference: str) -> DespatchSnapshot | None:
    """The advice of the order with its lines, or None: ONE statement for the header, one for the
    lines, on the caller's session (the repository's in-lock re-read and the reads' fast path)."""
    row = await session.scalar(select(Despatch).where(Despatch.order_reference == order_reference))
    if row is None:
        return None
    items = list(
        await session.scalars(select(DespatchItem).where(DespatchItem.despatch_id == row.id))
    )
    lines = tuple(
        sorted(
            (
                DespatchLineSnapshot(
                    id=_unique_id(item.id), product_code=item.product_code, units=item.units
                )
                for item in items
            ),
            key=lambda ln: line_order_key(ln.product_code, ln.id),
        )
    )
    return DespatchSnapshot(
        id=_unique_id(row.id),
        despatch_reference=DespatchReference(row.despatch_reference),
        despatch_date=row.despatch_date,
        order_reference=row.order_reference,
        company_code=row.company_code,
        retailer_code=row.retailer_code,
        lines=lines,
    )


class SqlAlchemyDespatchRepository:
    def __init__(self, session: AsyncSession, outbox: OutboxWriter, clock: Clock) -> None:
        self._session = session
        self._outbox = outbox
        self._clock = clock
        self._saved: list[DespatchAdvice] = []

    async def find_by_order_reference(self, order_reference: str) -> DespatchSnapshot | None:
        return await load_despatch(self._session, order_reference)

    async def save(self, advice: DespatchAdvice) -> None:
        now = self._clock.now()
        self._session.add(
            Despatch(
                id=advice.id.value,
                despatch_reference=advice.despatch_reference.value,
                despatch_date=advice.despatch_date,
                company_code=advice.company_code,
                retailer_code=advice.retailer_code,
                order_reference=advice.order_reference,
                created_at=now,
                updated_at=now,
            )
        )
        await self._session.flush()  # the header first: the lines' foreign key needs it
        for line in advice.lines:
            self._session.add(
                DespatchItem(
                    id=line.id.value,
                    despatch_id=advice.id.value,
                    product_code=line.product_code,
                    units=line.units.value,
                    created_at=now,
                    updated_at=now,
                )
            )
        await self._session.flush()
        # The outbox rows join THIS session and transaction (R13); the writer flushes per row.
        await self._outbox.write(self._session, advice.domain_events)
        self._saved.append(advice)

    def clear_saved_events(self) -> None:
        """Forget the events of every saved advice. Called by `run()` only AFTER the commit."""
        for advice in self._saved:
            advice.clear_domain_events()
