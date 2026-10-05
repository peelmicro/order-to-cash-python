"""The three seeded currencies (acceptance: "3 currencies").

ISO 4217 alpha-3 codes; `decimal_points` is metadata for RENDERING only (arithmetic stays integer
minor units everywhere).
"""

from dataclasses import dataclass

from otc_seed.domain.deterministic import deterministic_id


@dataclass(frozen=True, slots=True)
class CurrencySeed:
    id: str
    code: str
    iso_number: str
    symbol: str
    decimal_points: int


def _currency(code: str, iso_number: str, symbol: str) -> CurrencySeed:
    return CurrencySeed(deterministic_id(f"currency:{code}"), code, iso_number, symbol, 2)


CURRENCIES: tuple[CurrencySeed, ...] = (
    _currency("USD", "840", "$"),
    _currency("EUR", "978", "€"),
    _currency("GBP", "826", "£"),
)


def currency_id_by_code(code: str) -> str:
    for currency in CURRENCIES:
        if currency.code == code:
            return currency.id
    raise KeyError(f"unknown currency code {code!r}")
