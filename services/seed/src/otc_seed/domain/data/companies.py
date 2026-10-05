"""The 22 seeded companies (suppliers), varied countries (acceptance: "20+ companies").

GLN sequences start at 21: the 7 retailers own 1..7, and GLNs must be unique across the whole
seeded catalogue.
"""

from dataclasses import dataclass

from otc_seed.domain.deterministic import deterministic_id, make_gln


@dataclass(frozen=True, slots=True)
class CompanySeed:
    id: str
    code: str
    name: str
    country: str
    vat: str
    gln: str
    currency_code: str


# (code, name, country, vat, currency); the GLN sequence is 21 + the 0-based position.
_RAW: tuple[tuple[str, str, str, str, str], ...] = (
    ("IBERFOODS", "Iberian Foods Distribution SA", "ES", "ESA80907397", "EUR"),
    ("SPANATURAL", "Hispania Natural Foods SL", "ES", "ESB82591744", "EUR"),
    ("TOOLIBERIA", "Herramientas Ibéricas SA", "ES", "ESA84606310", "EUR"),
    ("MEDFRESH", "Mediterráneo Fresh Goods SL", "ES", "ESB63022260", "EUR"),
    ("FRESHFR", "Fraîcheur de France SARL", "FR", "FR76403355947", "EUR"),
    ("OUTILFRANCE", "Outillage de France SAS", "FR", "FR89552120222", "EUR"),
    ("GALLIAGOODS", "Gallia Goods Distribution SA", "FR", "FR23334028554", "EUR"),
    ("GERMANFOODS", "Deutsche Lebensmittel GmbH", "DE", "DE136695970", "EUR"),
    ("BAUWERK", "Bauwerk Werkzeuge GmbH", "DE", "DE811115660", "EUR"),
    ("RHEINGOODS", "Rheingold Handels GmbH", "DE", "DE147426685", "EUR"),
    ("UKDISTRIB", "British Isles Distribution Ltd", "GB", "GB434031494", "GBP"),
    ("LONDONTOOLS", "London Tools Supply Ltd", "GB", "GB113292750", "GBP"),
    ("ALBIONFOODS", "Albion Foods Ltd", "GB", "GB980780684", "GBP"),
    ("ITALPASTA", "Pastificio Italiano SRL", "IT", "IT00743110157", "EUR"),
    ("ROMATOOLS", "Attrezzi di Roma SRL", "IT", "IT01654060157", "EUR"),
    ("MILANOGOODS", "Milano Distribuzione SRL", "IT", "IT12842760151", "EUR"),
    ("LUSOFOODS", "Luso Alimentos Lda", "PT", "PT502757191", "EUR"),
    ("PORTOTOOLS", "Porto Ferramentas Lda", "PT", "PT503504457", "EUR"),
    ("DUTCHGOODS", "Nederlandse Groothandel BV", "NL", "NL805806053B01", "EUR"),
    ("HOLLANDTOOLS", "Holland Gereedschap BV", "NL", "NL818838663B01", "EUR"),
    ("BENELUXFOODS", "Benelux Voeding NV", "BE", "BE0429646425", "EUR"),
    ("BRUSSELSTOOLS", "Brussels Outillage NV", "BE", "BE0475747019", "EUR"),
)

COMPANIES: tuple[CompanySeed, ...] = tuple(
    CompanySeed(
        id=deterministic_id(f"company:{code}"),
        code=code,
        name=name,
        country=country,
        vat=vat,
        gln=make_gln(21 + index),
        currency_code=currency,
    )
    for index, (code, name, country, vat, currency) in enumerate(_RAW)
)


def company_by_code(code: str) -> CompanySeed:
    for company in COMPANIES:
        if company.code == code:
            return company
    raise KeyError(f"unknown company code {code!r}")
