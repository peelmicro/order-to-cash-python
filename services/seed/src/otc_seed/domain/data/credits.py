"""A credit line for every (retailer, company) pair: 7 primary + 7 x 21 baseline = 154.

Domain-model 5.1: one credit line per (retailer, company) pair. Each retailer's PRIMARY supplier is
the pair the sample sagas place their orders against (`CR-000001`..`CR-000007`, in RETAILERS
order); every other pair gets a BASELINE line at the same limit in the retailer's currency
(`CR-000008`.. in RETAILERS order, then COMPANIES order), so any retailer can order against any
company (the stock baseline already covers every company). Limits are `int` minor units: 500 000
is 5 000,00 in EUR or GBP, the figure the `credit.rejected.v1` example in the spec uses.
"""

from dataclasses import dataclass

from otc_seed.domain.data.companies import COMPANIES
from otc_seed.domain.data.retailers import RETAILERS
from otc_seed.domain.deterministic import deterministic_id
from otc_shared_kernel import CreditLineReference

CREDIT_LIMIT_MINOR_UNITS = 500_000

PRIMARY_SUPPLIER_BY_RETAILER: dict[str, str] = {
    "CarrefourEs": "IBERFOODS",
    "CarrefourFr": "FRESHFR",
    "LeroyMerlinEs": "TOOLIBERIA",
    "LeroyMerlinFr": "OUTILFRANCE",
    "AldiEs": "SPANATURAL",
    "AldiDe": "GERMANFOODS",
    "AldiGb": "UKDISTRIB",
}


@dataclass(frozen=True, slots=True)
class CreditSeed:
    id: str
    code: str
    retailer_code: str
    company_code: str
    credit_limit: int
    currency_code: str


_PRIMARY: tuple[CreditSeed, ...] = tuple(
    CreditSeed(
        id=deterministic_id(
            f"credit:{retailer.code}:{PRIMARY_SUPPLIER_BY_RETAILER[retailer.code]}"
        ),
        code=str(CreditLineReference.from_sequence(index + 1)),
        retailer_code=retailer.code,
        company_code=PRIMARY_SUPPLIER_BY_RETAILER[retailer.code],
        credit_limit=CREDIT_LIMIT_MINOR_UNITS,
        currency_code=retailer.currency_code,
    )
    for index, retailer in enumerate(RETAILERS)
)

_BASELINE: tuple[CreditSeed, ...] = tuple(
    CreditSeed(
        id=deterministic_id(f"credit:baseline:{retailer.code}:{company.code}"),
        code=str(
            CreditLineReference.from_sequence(
                len(_PRIMARY) + retailer_index * (len(COMPANIES) - 1) + company_index + 1
            )
        ),
        retailer_code=retailer.code,
        company_code=company.code,
        credit_limit=CREDIT_LIMIT_MINOR_UNITS,
        currency_code=retailer.currency_code,
    )
    for retailer_index, retailer in enumerate(RETAILERS)
    for company_index, company in enumerate(
        c for c in COMPANIES if c.code != PRIMARY_SUPPLIER_BY_RETAILER[retailer.code]
    )
)

CREDITS: tuple[CreditSeed, ...] = _PRIMARY + _BASELINE


def credit_by_retailer_and_company(retailer_code: str, company_code: str) -> CreditSeed:
    for credit in CREDITS:
        if credit.retailer_code == retailer_code and credit.company_code == company_code:
            return credit
    raise KeyError(f"no credit line for {retailer_code}/{company_code}")
