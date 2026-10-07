"""`SqlAlchemyReferenceCatalog`: read-only lookups of the reference tables of `otc_orders`.

Each lookup opens its own short session and closes it (`async with`): a catalogue read is not part
of any transaction (the handler reads reference data BEFORE it opens the unit of work).
"""

from collections.abc import Collection, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_orders.application.ports.reference_catalog import PartyReference, ProductReference
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
