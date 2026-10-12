"""The `catalog_data` fixture guards itself (feature 40, review B1, the A5 class).

An ordering claim ("listed by code") is only proven if the data cannot satisfy a SIBLING ordering
by accident. For every list and every sibling column, ordering by that column must differ from
code order, with and without the disabled row; and code order must differ from insertion order and
its reverse. Each failure names the list, the column and the order it computed.
"""

from typing import Any

import pytest

pytestmark = pytest.mark.integration

# kind -> the sibling columns, by their wire names, whose order must not equal code order
SIBLINGS: dict[str, tuple[str, ...]] = {
    "products": ("name", "ean", "description"),
    "retailers": ("name", "vat", "gln", "country"),
    "companies": ("name", "vat", "gln", "country"),
    "currencies": ("isoNumber", "symbol"),
}


def codes_ordered_by(rows: list[dict[str, Any]], column: str) -> list[str]:
    return [row["code"] for row in sorted(rows, key=lambda row: str(row[column]))]


@pytest.mark.parametrize("include_disabled", [False, True])
@pytest.mark.parametrize("kind", list(SIBLINGS))
def test_no_sibling_column_orders_a_list_the_way_its_code_does(
    catalog_data: Any, kind: str, include_disabled: bool
) -> None:
    rows = catalog_data.listed(kind, include_disabled=include_disabled)
    code_order = [row["code"] for row in rows]
    assert code_order == sorted(code_order), "the fixture's own wire rows are in code order"
    for column in SIBLINGS[kind]:
        by_column = codes_ordered_by(rows, column)
        assert by_column != code_order, (
            f"{kind} (include_disabled={include_disabled}): ordering by {column} gives {by_column},"
            f" identical to code order"
        )


@pytest.mark.parametrize("include_disabled", [False, True])
@pytest.mark.parametrize("kind", list(SIBLINGS))
def test_code_order_differs_from_insertion_order_and_its_reverse(
    catalog_data: Any, kind: str, include_disabled: bool
) -> None:
    rows = catalog_data.listed(kind, include_disabled=include_disabled)
    code_order = [row["code"] for row in rows]
    inserted = [code for code in catalog_data.insertion[kind] if code in code_order]
    assert code_order != inserted, f"{kind}: code order equals insertion order {inserted}"
    assert code_order != inserted[::-1], f"{kind}: code order equals reversed insertion"


@pytest.mark.parametrize("kind", ["products", "retailers", "companies"])
def test_every_sibling_column_value_is_distinct(catalog_data: Any, kind: str) -> None:
    rows = catalog_data.listed(kind, include_disabled=True)
    for column in SIBLINGS[kind]:
        values = [str(row[column]) for row in rows]
        assert len(set(values)) == len(values), f"{kind}.{column} repeats a value: {values}"
