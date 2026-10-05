"""ISO 4217 minor-unit exponent per currency code (SA-5, `specs/shared/openapi.yaml` Money section).

The exponent is a property of the currency code, never of a locale (CLDR display digits disagree
with ISO 4217 for AFN, ALL, HUF, ... - measured in #8). Only the currencies whose exponent is not 2
are listed; every other code defaults to 2 (EUR, GBP and USD among them). The same table is
committed as `apps/web/src/lib/currency-exponents.json` for the web; a test fails on any divergence.
"""

from collections.abc import Mapping
from types import MappingProxyType

DEFAULT_EXPONENT = 2

NON_DEFAULT_EXPONENTS: Mapping[str, int] = MappingProxyType(
    {
        # Zero decimal digits.
        "BIF": 0,
        "CLP": 0,
        "DJF": 0,
        "GNF": 0,
        "ISK": 0,
        "JPY": 0,
        "KMF": 0,
        "KRW": 0,
        "PYG": 0,
        "RWF": 0,
        "UGX": 0,
        "VND": 0,
        "VUV": 0,
        "XAF": 0,
        "XOF": 0,
        "XPF": 0,
        # Three decimal digits.
        "BHD": 3,
        "IQD": 3,
        "JOD": 3,
        "KWD": 3,
        "LYD": 3,
        "OMR": 3,
        "TND": 3,
        # Four decimal digits.
        "CLF": 4,
        "UYW": 4,
        # Fund code with an ISO 4217 exponent of zero.
        "UYI": 0,
    }
)


def exponent_of(currency: str) -> int:
    """The ISO 4217 minor-unit exponent of `currency`; an unlisted code defaults to 2."""
    return NON_DEFAULT_EXPONENTS.get(currency, DEFAULT_EXPONENT)
