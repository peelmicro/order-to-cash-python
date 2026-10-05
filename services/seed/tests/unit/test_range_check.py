"""The seed's write-boundary range check: every integer it writes fits its column.

R-map (feature_list.json id 12; backlog 204(a) applied to the seed): the check is a function of the
column TYPES of the seed's own tables (which `schema_check` proves equal to the migrated database),
called by the one insert path before a statement exists. The population of guarded columns is a
literal below, derived by `grep -c "BigInteger\\|Integer" tables.py` AND by the live database in
`integration/test_seed_tables_match_migration.py`.
"""

import re
from typing import Any

import pytest

from otc_seed.infrastructure import tables
from otc_seed.infrastructure.postgres import insert_missing
from otc_seed.infrastructure.range_check import (
    SeedIntegerOutOfRangeError,
    ensure_row_in_range,
    integer_columns,
)

EXPECTED_INTEGER_COLUMNS = {
    "currencies": {"decimal_points"},
    "products": {"price"},
    "orders": {"initial_amount", "initial_discount", "total_amount"},
    "order_items": {"price", "quantity", "discount"},
    "stock": {"units", "reserved_units", "low_stock_threshold"},
    "reservations": {"units"},
    "despatch_items": {"units"},
    "credits": {"credit_limit"},
    "credit_items": {"amount"},
    "invoices": {"amount", "discount", "total_amount"},
    "invoice_items": {"units", "price"},
    "payments": {"amount"},
    "outbox": {"seq"},
}


def test_the_guarded_columns_are_exactly_the_integer_columns_of_every_seed_table() -> None:
    found: dict[str, set[str]] = {}
    for metadata in (
        tables.ORDERS_METADATA,
        tables.FULFILLMENT_METADATA,
        tables.BILLING_METADATA,
    ):
        for table in metadata.sorted_tables:
            names = {c.name for c in integer_columns(table)}
            if names:
                found.setdefault(table.name, set()).update(names)
    assert found == EXPECTED_INTEGER_COLUMNS


@pytest.mark.parametrize(
    ("table", "column", "ok", "too_big"),
    [
        (tables.STOCK, "units", 2**31 - 1, 2**31),  # Integer
        (tables.ORDERS, "total_amount", 2**63 - 1, 2**63),  # BigInteger
    ],
)
def test_a_value_at_the_limit_passes_and_one_past_it_is_refused(
    table: Any, column: str, ok: int, too_big: int
) -> None:
    ensure_row_in_range(table, {column: ok})
    ensure_row_in_range(table, {column: -ok - 1})
    with pytest.raises(SeedIntegerOutOfRangeError, match=re.escape(f"{table.name}.{column}")):
        ensure_row_in_range(table, {column: too_big})
    with pytest.raises(SeedIntegerOutOfRangeError, match=re.escape(f"{table.name}.{column}")):
        ensure_row_in_range(table, {column: -too_big - 1})


@pytest.mark.parametrize("bad", [True, 1.0, "1", None])
def test_a_bool_a_float_a_string_and_none_are_refused_for_an_integer_column(bad: object) -> None:
    with pytest.raises(SeedIntegerOutOfRangeError):
        ensure_row_in_range(tables.STOCK, {"units": bad})


def test_the_error_is_a_domain_error_with_a_stable_code() -> None:
    with pytest.raises(SeedIntegerOutOfRangeError) as raised:
        ensure_row_in_range(tables.INVOICES, {"amount": 2**63})
    assert raised.value.code == "storage.integer_out_of_range"
    assert raised.value.where == "invoices.amount"


class _NoStatementConnection:
    """A connection that fails the test if any statement reaches it."""

    async def execute(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("a statement was built for a row that is out of range")


async def test_the_one_insert_path_checks_the_range_before_any_statement_exists() -> None:
    row = {"id": "x", "units": 2**31}
    with pytest.raises(SeedIntegerOutOfRangeError, match=r"stock\.units"):
        await insert_missing(_NoStatementConnection(), tables.STOCK, [row])
