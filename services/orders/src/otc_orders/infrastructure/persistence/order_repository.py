"""`SqlAlchemyOrderRepository`: the Order aggregate over one `AsyncSession` (R13).

* `save` inserts an order this repository did not load and updates one it did (`order_items`
  diffed by line id: insert new, update changed, delete removed), through the ORM unit of work so
  `install_range_guards` fires on every integer column. It then hands the aggregate's domain events
  to the `OutboxWriter`, in the same session and so the same transaction.
* It reads `order.domain_events` (non-destructive) and never clears them: the unit of work clears
  them AFTER the commit (L16), so a retry from the same instance after a rollback writes the events
  again, exactly once per transaction that commits.
* An event this repository already wrote in this transaction is not written twice (`event_id` is
  unique in `outbox`): saving the same aggregate twice in one transaction is an update.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from otc_orders.domain.order import Order
from otc_orders.infrastructure.outbox.payloads import narrow
from otc_orders.infrastructure.outbox.writer import OutboxWriter
from otc_orders.infrastructure.persistence.models import Company, Currency, Product, Retailer
from otc_orders.infrastructure.persistence.models import Order as OrderRow
from otc_orders.infrastructure.persistence.models import OrderItem as OrderItemRow
from otc_orders.infrastructure.persistence.order_mapper import (
    OrderReferences,
    ResolvedIds,
    apply_to_order_item_row,
    apply_to_order_row,
    order_item_row_of,
    order_of,
    order_row_of,
)
from otc_shared_kernel import OrderNumber, UniqueId


class ReferenceDataMissingError(Exception):
    """A code the order carries has no row in its reference table (an infrastructure fault: the
    use case validates codes before it builds an order)."""

    def __init__(self, table: str, code: str) -> None:
        super().__init__(f"{table} has no row with code {code!r}")
        self.table = table
        self.code = code


class SqlAlchemyOrderRepository:
    def __init__(self, session: AsyncSession, outbox: OutboxWriter) -> None:
        self._session = session
        self._outbox = outbox
        self._loaded: set[UUID] = set()  # orders loaded or inserted through THIS repository
        self._saved: list[Order] = []  # in save order; the unit of work clears them after commit
        self._written_events: set[UUID] = set()

    @property
    def saved(self) -> tuple[Order, ...]:
        return tuple(self._saved)

    async def save(self, order: Order) -> None:
        if order.id.value in self._loaded:
            await self._update(order)
        else:
            await self._insert(order)
            self._loaded.add(order.id.value)
        pending = [
            event
            for event in order.domain_events
            if narrow(event).event_id.value not in self._written_events
        ]
        await self._outbox.write(self._session, pending)
        self._written_events.update(narrow(event).event_id.value for event in pending)
        if order not in self._saved:
            self._saved.append(order)

    async def get_by_id(self, order_id: UniqueId) -> Order | None:
        return await self._load(OrderRow.id == order_id.value)

    async def get_by_id_for_update(self, order_id: UniqueId) -> Order | None:
        """The order's row is locked to the end of the transaction (SO17): `FOR UPDATE OF orders`.

        `of=OrderRow` is load-bearing. A bare `FOR UPDATE` over the four-table join locks a row of
        EVERY table in the `FROM` clause, so it would hold the retailer's, company's and currency's
        rows too and serialise every saga step of every order of that retailer. Lines are written
        only through the aggregate, whose root row is locked first, so the root lock serialises
        them.
        """
        return await self._load(OrderRow.id == order_id.value, for_update=True)

    async def get_by_reference(self, reference: OrderNumber) -> Order | None:
        return await self._load(OrderRow.order_reference == reference.value)

    # ----------------------------------------------------------------------------------- writes

    async def _insert(self, order: Order) -> None:
        ids = ResolvedIds(
            retailer_id=await self._id_of(Retailer, order.retailer_code),
            company_id=await self._id_of(Company, order.company_code),
            currency_id=await self._id_of(Currency, order.currency),
        )
        self._session.add(order_row_of(order, ids))
        await self._session.flush()  # the parent row exists before its items
        for line in order.lines:
            product_id = await self._id_of(Product, line.product_code)
            self._session.add(order_item_row_of(order, line, product_id))
        await self._session.flush()

    async def _update(self, order: Order) -> None:
        row = await self._session.get(OrderRow, order.id.value)
        if row is None:
            raise ReferenceDataMissingError("orders", str(order.id))
        apply_to_order_row(row, order)
        stored = {
            item.id: item
            for item in (
                await self._session.scalars(
                    select(OrderItemRow).where(OrderItemRow.order_id == order.id.value)
                )
            ).all()
        }
        kept: set[UUID] = set()
        for line in order.lines:
            kept.add(line.id.value)
            existing = stored.get(line.id.value)
            if existing is None:
                product_id = await self._id_of(Product, line.product_code)
                self._session.add(order_item_row_of(order, line, product_id))
            else:
                apply_to_order_item_row(existing, order, line)
        for item_id, item in stored.items():
            if item_id not in kept:
                await self._session.delete(item)
        await self._session.flush()

    async def _id_of(
        self, model: type[Currency] | type[Company] | type[Retailer] | type[Product], code: str
    ) -> UUID:
        found = await self._session.scalar(select(model.id).where(model.code == code))
        if found is None:
            raise ReferenceDataMissingError(model.__tablename__, code)
        return found

    # ------------------------------------------------------------------------------------ reads

    async def _load(self, where: ColumnElement[bool], *, for_update: bool = False) -> Order | None:
        statement = (
            select(OrderRow, Retailer, Company, Currency)
            .join(Retailer, OrderRow.retailer_id == Retailer.id)
            .join(Company, OrderRow.company_id == Company.id)
            .join(Currency, OrderRow.currency_id == Currency.id)
            .where(where)
        )
        if for_update:
            statement = statement.with_for_update(of=OrderRow)
        found = (await self._session.execute(statement)).first()
        if found is None:
            return None
        row, retailer, company, currency = found
        items = (
            await self._session.execute(
                select(OrderItemRow, Product.code)
                .join(Product, OrderItemRow.product_id == Product.id)
                .where(OrderItemRow.order_id == row.id)
            )
        ).all()
        order = order_of(
            row,
            [(item, code) for item, code in items],
            OrderReferences(
                retailer_code=retailer.code,
                buyer_gln=retailer.gln,
                company_code=company.code,
                supplier_gln=company.gln,
                currency=currency.code,
            ),
        )
        self._loaded.add(order.id.value)
        return order
