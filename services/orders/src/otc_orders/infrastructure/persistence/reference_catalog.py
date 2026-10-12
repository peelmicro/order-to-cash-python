"""`SqlAlchemyReferenceCatalog`: read-only lookups of the reference tables of `otc_orders`.

Each lookup opens its own short session and closes it (`async with`): a catalogue read is not part
of any transaction (the handler reads reference data BEFORE it opens the unit of work).

The `list_*` methods (feature 40) are plain SELECTs, never `FOR UPDATE`, ordered by `code` in the
database. A row is "enabled" when `disabled_at IS NULL`; unless `include_disabled`, the others are
left out IN THE QUERY.
"""

from collections.abc import Collection, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_orders.application.ports.reference_catalog import (
    CurrencyListing,
    PartyListing,
    PartyReference,
    ProductListing,
    ProductReference,
)
from otc_orders.infrastructure.persistence.models import Company, Currency, Product, Retailer
from otc_shared_kernel import GLN, Money


class SqlAlchemyReferenceCatalog:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def find_retailer(self, retailer_code: str) -> PartyReference | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(Retailer.code, Retailer.gln).where(Retailer.code == retailer_code)
                )
            ).first()
        return None if row is None else PartyReference(row.code, GLN(row.gln))

    async def find_company(self, company_code: str) -> PartyReference | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(Company.code, Company.gln).where(Company.code == company_code)
                )
            ).first()
        return None if row is None else PartyReference(row.code, GLN(row.gln))

    async def currency_exists(self, currency_code: str) -> bool:
        async with self._sessions() as session:
            found = await session.scalar(select(Currency.id).where(Currency.code == currency_code))
        return found is not None

    async def find_products(self, product_codes: Collection[str]) -> Mapping[str, ProductReference]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(Product.code, Product.description, Product.price, Currency.code)
                    .join(Currency, Product.currency_id == Currency.id)
                    .where(Product.code.in_(list(product_codes)))
                )
            ).all()
        return {
            code: ProductReference(code, description or None, Money(price, currency))
            for code, description, price, currency in rows
        }

    async def list_products(self, *, include_disabled: bool) -> Sequence[ProductListing]:
        query = (
            select(
                Product.code,
                Product.ean,
                Product.name,
                Product.description,
                Product.price,
                Currency.code.label("currency"),
                Product.disabled_at,
            )
            .join(Currency, Product.currency_id == Currency.id)
            .order_by(Product.code)
        )
        if not include_disabled:
            query = query.where(Product.disabled_at.is_(None))
        async with self._sessions() as session:
            rows = (await session.execute(query)).all()
        return [
            ProductListing(
                code=row.code,
                ean=row.ean,
                name=row.name,
                description=row.description,
                price=Money(row.price, row.currency),
                enabled=row.disabled_at is None,
            )
            for row in rows
        ]

    async def list_retailers(self, *, include_disabled: bool) -> Sequence[PartyListing]:
        return await self._list_parties(Retailer, include_disabled)

    async def list_companies(self, *, include_disabled: bool) -> Sequence[PartyListing]:
        return await self._list_parties(Company, include_disabled)

    async def _list_parties(
        self, table: type[Retailer] | type[Company], include_disabled: bool
    ) -> Sequence[PartyListing]:
        query = (
            select(
                table.code,
                table.name,
                table.country,
                table.vat,
                table.gln,
                Currency.code.label("currency"),
                table.disabled_at,
            )
            .join(Currency, table.currency_id == Currency.id)
            .order_by(table.code)
        )
        if not include_disabled:
            query = query.where(table.disabled_at.is_(None))
        async with self._sessions() as session:
            rows = (await session.execute(query)).all()
        return [
            PartyListing(
                code=row.code,
                name=row.name,
                country=row.country,
                vat=row.vat,
                gln=row.gln,
                currency=row.currency,
                enabled=row.disabled_at is None,
            )
            for row in rows
        ]

    async def list_currencies(self) -> Sequence[CurrencyListing]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        Currency.code, Currency.iso_number, Currency.symbol, Currency.decimal_points
                    ).order_by(Currency.code)
                )
            ).all()
        return [
            CurrencyListing(
                code=row.code,
                iso_number=row.iso_number,
                symbol=row.symbol,
                decimal_points=row.decimal_points,
            )
            for row in rows
        ]
