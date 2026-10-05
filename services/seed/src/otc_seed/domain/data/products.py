"""The 12 seeded products (acceptance: "10+ products").

PRD-0001's price (24999 = 249.99) is chosen on purpose: one unit already totals `.99`, which is
the credit simulator's `simulated_cents_rule` affordance, and is the line the cancelled sample
order uses. Prices are `int` minor units.
"""

from dataclasses import dataclass

from otc_seed.domain.deterministic import deterministic_id, make_ean13


@dataclass(frozen=True, slots=True)
class ProductSeed:
    id: str
    code: str
    ean: str
    name: str
    description: str
    price: int
    currency_code: str


# (code, name, description, price in minor units, currency)
_RAW: tuple[tuple[str, str, str, int, str], ...] = (
    ("PRD-0001", "Ration Pack Bundle", "Mixed grocery ration pack, 1 unit", 24999, "EUR"),
    ("PRD-0002", "Pasta 500g Case (24u)", "Case of 24 x 500g dried pasta", 1849, "EUR"),
    ("PRD-0003", "Olive Oil 1L Case (12u)", "Case of 12 x 1L extra virgin olive oil", 2295, "EUR"),
    ("PRD-0004", "Claw Hammer 16oz", "Forged steel claw hammer, 16oz head", 1450, "EUR"),
    ("PRD-0005", "Screwdriver Set 6pc", "6-piece flathead/Phillips screwdriver set", 825, "EUR"),
    ("PRD-0006", "Paint Roller Kit", "Roller, tray and 2 refill sleeves", 645, "EUR"),
    ("PRD-0007", "Garden Hose 20m", "Reinforced PVC garden hose, 20 metres", 3275, "EUR"),
    (
        "PRD-0008",
        "Laundry Detergent 5L",
        "5L concentrated liquid laundry detergent",
        1489,
        "EUR",
    ),
    (
        "PRD-0009",
        "English Breakfast Tea 250g",
        "250g loose-leaf English breakfast tea",
        379,
        "GBP",
    ),
    ("PRD-0010", "Digestive Biscuits 400g", "400g pack of digestive biscuits", 165, "GBP"),
    ("PRD-0011", "Maple Syrup 1L", "1L pure maple syrup", 1749, "USD"),
    ("PRD-0012", "Almond Butter 500g", "500g smooth almond butter", 895, "USD"),
)

PRODUCTS: tuple[ProductSeed, ...] = tuple(
    ProductSeed(
        id=deterministic_id(f"product:{code}"),
        code=code,
        ean=make_ean13(index + 1),
        name=name,
        description=description,
        price=price,
        currency_code=currency,
    )
    for index, (code, name, description, price, currency) in enumerate(_RAW)
)


def product_by_code(code: str) -> ProductSeed:
    for product in PRODUCTS:
        if product.code == code:
            return product
    raise KeyError(f"unknown product code {code!r}")
