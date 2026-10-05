"""The write-boundary range check of the seed: every integer it writes fits its column.

`Money` is bounded to int64 and `Quantity` is not bounded at all, so the column's own width has to
be enforced where the value enters a row. The services do it with an ORM attribute listener
(`persistence/range_guards.py`); the seed is a BULK writer over Core tables and cannot import a
service, so it enforces the same contract at the one place every row passes: `ensure_row_in_range`,
called by `postgres.insert_missing` for every row of every table before any statement is built. The
limits come from the column TYPES of the seed's own table definitions (which `schema_check` proves
equal to the migrated database), not from a list of column names, so a column added to a table is
checked without anyone remembering to. `bool` and non-`int` values are refused (a `True` would be
stored as 1).
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import BigInteger, Column, Integer, SmallInteger, Table
from sqlalchemy.types import TypeEngine

from otc_shared_kernel import DomainError

_WIDTHS: Mapping[type[TypeEngine[Any]], tuple[int, int]] = {
    SmallInteger: (-(2**15), 2**15 - 1),
    Integer: (-(2**31), 2**31 - 1),
    BigInteger: (-(2**63), 2**63 - 1),
}


class SeedIntegerOutOfRangeError(DomainError):
    CODE = "storage.integer_out_of_range"

    def __init__(self, where: str, value: object, low: int, high: int) -> None:
        super().__init__(
            self.CODE, f"{value!r} does not fit {where}: the column holds {low}..{high}"
        )
        self.where = where


def integer_columns(table: Table) -> list[Column[Any]]:
    """The columns of `table` the range check covers (exact `Integer`/`BigInteger`/`SmallInteger`:
    BigInteger and SmallInteger subclass Integer, so the exact class decides)."""
    return [c for c in table.columns if type(c.type) in _WIDTHS]


def ensure_row_in_range(table: Table, row: Mapping[str, object]) -> None:
    for column in integer_columns(table):
        if column.name not in row:
            continue
        value = row[column.name]
        low, high = _WIDTHS[type(column.type)]
        if type(value) is not int or not low <= value <= high:
            raise SeedIntegerOutOfRangeError(f"{table.name}.{column.name}", value, low, high)
