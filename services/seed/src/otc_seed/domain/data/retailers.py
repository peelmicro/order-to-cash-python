"""The 7 seeded retailers (acceptance: "7 retailers").

GLNs are `make_gln(1..7)` (genuine GS1 check digit); VATs are shape-plausible per country and not
domain-validated (there is no VAT value object in this model).
"""

from dataclasses import dataclass

from otc_seed.domain.deterministic import deterministic_id, make_gln


@dataclass(frozen=True, slots=True)
class RetailerSeed:
    id: str
    code: str
    name: str
    country: str
    vat: str
    gln: str
    currency_code: str


# (code, name, country, vat, currency); the GLN sequence is the 1-based position.
_RAW: tuple[tuple[str, str, str, str, str], ...] = (
    ("CarrefourEs", "Carrefour España", "ES", "ESA28425270", "EUR"),
    ("CarrefourFr", "Carrefour France", "FR", "FR45652014051", "EUR"),
    ("LeroyMerlinEs", "Leroy Merlin España", "ES", "ESA28398950", "EUR"),
    ("LeroyMerlinFr", "Leroy Merlin France", "FR", "FR32384657943", "EUR"),
    ("AldiEs", "Aldi España", "ES", "ESA65037725", "EUR"),
    ("AldiDe", "Aldi Deutschland", "DE", "DE812631079", "EUR"),
    ("AldiGb", "Aldi UK", "GB", "GB245012348", "GBP"),
)

RETAILERS: tuple[RetailerSeed, ...] = tuple(
    RetailerSeed(
        id=deterministic_id(f"retailer:{code}"),
        code=code,
        name=name,
        country=country,
        vat=vat,
        gln=make_gln(index + 1),
        currency_code=currency,
    )
    for index, (code, name, country, vat, currency) in enumerate(_RAW)
)


def retailer_by_code(code: str) -> RetailerSeed:
    for retailer in RETAILERS:
        if retailer.code == code:
            return retailer
    raise KeyError(f"unknown retailer code {code!r}")
