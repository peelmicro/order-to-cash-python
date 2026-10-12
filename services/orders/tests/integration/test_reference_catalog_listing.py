"""`SqlAlchemyReferenceCatalog.list_*` against a real PostgreSQL (feature 40, acceptance item 2).

The fixture (`catalog_data`, conftest) seeds three enabled rows and one disabled row per kind that
has the notion; INSERTION order differs from code order and from its reverse in every list, with
and without the disabled row. Every field of every row is asserted, so a column read into the
wrong field, a price from the wrong currency or a swapped retailer/company table fails by name.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from otc_orders.application.ports.reference_catalog import PartyListing, ProductListing
from otc_orders.infrastructure.persistence.reference_catalog import SqlAlchemyReferenceCatalog

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(loop_scope="function")
async def statements(engine: AsyncEngine) -> AsyncIterator[list[str]]:
    seen: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    yield seen
    event.remove(engine.sync_engine, "before_cursor_execute", record)


@pytest.fixture
def catalog(sessions: async_sessionmaker[AsyncSession]) -> SqlAlchemyReferenceCatalog:
    return SqlAlchemyReferenceCatalog(sessions)


def product_wire(listing: ProductListing) -> dict[str, Any]:
    return {
        "code": listing.code,
        "ean": listing.ean,
        "name": listing.name,
        "description": listing.description,
        "price": listing.price.amount,
        "currency": listing.price.currency,
        "enabled": listing.enabled,
    }


def party_wire(listing: PartyListing) -> dict[str, Any]:
    return {
        "code": listing.code,
        "name": listing.name,
        "country": listing.country,
        "vat": listing.vat,
        "gln": listing.gln,
        "currency": listing.currency,
        "enabled": listing.enabled,
    }


@pytest.mark.parametrize("include_disabled", [False, True])
async def test_products_are_listed_field_for_field_in_code_order(
    catalog: SqlAlchemyReferenceCatalog, catalog_data: Any, include_disabled: bool
) -> None:
    listed = await catalog.list_products(include_disabled=include_disabled)

    assert [product_wire(p) for p in listed] == catalog_data.listed(
        "products", include_disabled=include_disabled
    )


@pytest.mark.parametrize("include_disabled", [False, True])
async def test_retailers_are_listed_field_for_field_in_code_order(
    catalog: SqlAlchemyReferenceCatalog, catalog_data: Any, include_disabled: bool
) -> None:
    listed = await catalog.list_retailers(include_disabled=include_disabled)

    assert [party_wire(p) for p in listed] == catalog_data.listed(
        "retailers", include_disabled=include_disabled
    )


@pytest.mark.parametrize("include_disabled", [False, True])
async def test_companies_are_listed_field_for_field_in_code_order(
    catalog: SqlAlchemyReferenceCatalog, catalog_data: Any, include_disabled: bool
) -> None:
    listed = await catalog.list_companies(include_disabled=include_disabled)

    assert [party_wire(p) for p in listed] == catalog_data.listed(
        "companies", include_disabled=include_disabled
    )


async def test_currencies_are_listed_field_for_field_in_code_order(
    catalog: SqlAlchemyReferenceCatalog, catalog_data: Any
) -> None:
    listed = await catalog.list_currencies()

    assert [
        {
            "code": c.code,
            "isoNumber": c.iso_number,
            "symbol": c.symbol,
            "decimalPoints": c.decimal_points,
        }
        for c in listed
    ] == catalog_data.currencies


async def test_the_disabled_row_of_each_kind_is_listed_only_when_asked_for_and_marked_disabled(
    catalog: SqlAlchemyReferenceCatalog, catalog_data: Any
) -> None:
    hidden: Sequence[Sequence[Any]] = [
        await catalog.list_products(include_disabled=False),
        await catalog.list_retailers(include_disabled=False),
        await catalog.list_companies(include_disabled=False),
    ]
    shown: Sequence[Sequence[Any]] = [
        await catalog.list_products(include_disabled=True),
        await catalog.list_retailers(include_disabled=True),
        await catalog.list_companies(include_disabled=True),
    ]

    assert [len(rows) for rows in hidden] == [3, 3, 3]
    assert [len(rows) for rows in shown] == [4, 4, 4]
    assert [[r.enabled for r in rows] for rows in hidden] == [[True] * 3] * 3
    assert [[r.enabled for r in rows] for rows in shown] == [[True, True, True, False]] * 3


async def test_the_listings_issue_reads_only_and_hold_no_lock(
    catalog: SqlAlchemyReferenceCatalog,
    catalog_data: Any,
    statements: list[str],
    engine: AsyncEngine,
) -> None:
    await catalog.list_products(include_disabled=True)
    await catalog.list_retailers(include_disabled=True)
    await catalog.list_companies(include_disabled=False)
    await catalog.list_currencies()

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 4, statements
    writes = [s for s in statements if s.lstrip().upper().split(None, 1)[0] in WRITE_VERBS]
    assert writes == []
    assert [s for s in statements if "FOR UPDATE" in s.upper() or "FOR SHARE" in s.upper()] == []
    # each listing owned its session and closed it: nothing is checked out of the pool
    assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]


WRITE_VERBS = frozenset({"INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "ALTER", "DROP"})
