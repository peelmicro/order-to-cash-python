"""The whole dataset as one value: what a target is asked to write."""

from dataclasses import dataclass

from otc_seed.domain.data.companies import COMPANIES, CompanySeed
from otc_seed.domain.data.credits import CREDITS, CreditSeed
from otc_seed.domain.data.currencies import CURRENCIES, CurrencySeed
from otc_seed.domain.data.products import PRODUCTS, ProductSeed
from otc_seed.domain.data.retailers import RETAILERS, RetailerSeed
from otc_seed.domain.data.sagas import SAGAS, OrderSagaFixture
from otc_seed.domain.data.stock import STOCK, StockSeed


@dataclass(frozen=True, slots=True)
class SeedDataset:
    currencies: tuple[CurrencySeed, ...]
    products: tuple[ProductSeed, ...]
    retailers: tuple[RetailerSeed, ...]
    companies: tuple[CompanySeed, ...]
    credits: tuple[CreditSeed, ...]
    stock: tuple[StockSeed, ...]
    sagas: tuple[OrderSagaFixture, ...]


def default_dataset() -> SeedDataset:
    """The dataset #7 and #8 seed: 3 currencies, 12 products, 7 retailers, 22 companies, 154 credit
    lines, 215 stock rows and 6 sagas (5 completed, 1 cancelled)."""
    return SeedDataset(CURRENCIES, PRODUCTS, RETAILERS, COMPANIES, CREDITS, STOCK, SAGAS)
