"""The write-boundary range guard for every integer column of a service write model.

`Money` is bounded to int64 and `Quantity` is unbounded by design (review_shared_kernel.md D8), so
the column's own width has to be enforced where the value enters the row. The guard is a SQLAlchemy
attribute `set` listener installed on EVERY `Integer`/`BigInteger` column of every mapped class, by
walking the mapper registry rather than by listing columns: a column added later is guarded without
anyone remembering to. A listener raises at assignment, before any statement exists, so the caller
sees a `DomainError` with a stable code and never a wrapped asyncpg `DataError`.

Residual (the guard is an ORM attribute event, so it covers ONLY attribute assignment on a mapped
instance: the constructor, `obj.col = value`, and `session.merge`). Every ORM-enabled DML statement
that takes the mapped class bypasses it and surfaces as the engine's own `DBAPIError`:
`session.execute(insert(Model).values(...))`, `session.execute(insert(Model), [dicts])` (SQLAlchemy
2's bulk insert), `update(Model)` (with `.where().values()` or bulk-by-primary-key), and
`session.bulk_insert_mappings` / `bulk_update_mappings`. So does raw `text()` SQL. They are not
"Core only": taking the mapped class does not put the statement on the guarded path.
`test_residual_orm_enabled_dml_paths_bypass_the_guard_and_only_the_engine_refuses` pins the bypass;
`test_every_integer_column_of_the_live_database_is_guarded` closes the population of COLUMNS, not
the population of write paths.

A SQL expression assigned to a guarded attribute (`row.attempts = Row.attempts + 1`, SQLAlchemy's
atomic server-side increment) is a `ClauseElement`, not a value, so it passes through: there is
nothing to range-check until the database evaluates it, and an overflow there is the engine's
refusal (the same residual).

The module is identical in every service that carries it (`tests/architecture/
test_range_guard_parity.py`): the service-specific part, which columns get the quantity code, is
passed to `install_range_guards` by that service's `models.py`.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import BigInteger, Column, Integer, SmallInteger, event
from sqlalchemy.orm import Mapper
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.elements import ClauseElement
from sqlalchemy.types import TypeEngine

from otc_shared_kernel import DomainError

INT32_MAX = 2**31 - 1
INT32_MIN = -(2**31)
INT64_MAX = 2**63 - 1
INT64_MIN = -(2**63)
_WIDTHS: Mapping[type[TypeEngine[Any]], tuple[int, int]] = {
    SmallInteger: (-(2**15), 2**15 - 1),
    Integer: (INT32_MIN, INT32_MAX),
    BigInteger: (INT64_MIN, INT64_MAX),
}


class IntegerOutOfRangeError(DomainError):
    CODE = "storage.integer_out_of_range"

    def __init__(self, where: str, value: object, low: int, high: int) -> None:
        super().__init__(
            self.CODE, f"{value!r} does not fit {where}: the column holds {low}..{high}"
        )
        self.where = where


class QuantityOutOfRangeError(IntegerOutOfRangeError):
    CODE = "quantity.out_of_range"


def ensure_in_range(
    value: object,
    low: int,
    high: int,
    where: str,
    error: type[IntegerOutOfRangeError] = IntegerOutOfRangeError,
) -> None:
    """Refuse a value the column cannot hold. `bool` and non-int values are refused too."""
    if type(value) is not int or not low <= value <= high:
        raise error(where, value, low, high)


def _width(column_type: TypeEngine[Any]) -> tuple[int, int] | None:
    # BigInteger and SmallInteger subclass Integer, so the exact class decides.
    return _WIDTHS.get(type(column_type))


def install_range_guards(
    mappers: list[Mapper[Any]],
    specific_errors: Mapping[tuple[str, str], type[IntegerOutOfRangeError]],
) -> list[tuple[str, str]]:
    """Attach the guard to every integer column; return the (table, column) pairs guarded.

    `specific_errors` maps (table, column) to the more specific refusal; every other integer column
    raises the generic `IntegerOutOfRangeError`.
    """
    guarded: list[tuple[str, str]] = []
    for mapper in mappers:
        for attr in mapper.column_attrs:
            column = attr.columns[0]
            width = _width(column.type)
            if width is None or not isinstance(column, Column):
                continue
            low, high = width
            table, name = str(column.table.name), column.name
            error = specific_errors.get((table, name), IntegerOutOfRangeError)
            instrumented: InstrumentedAttribute[Any] = getattr(mapper.class_, attr.key)

            def _check(
                target: object,
                value: object,
                old: object,
                initiator: object,
                *,
                _where: str = f"{table}.{name}",
                _low: int = low,
                _high: int = high,
                _error: type[IntegerOutOfRangeError] = error,
            ) -> None:
                # NULL is the column's nullability, not its range; a SQL expression is not a value
                # (the engine evaluates it), so it passes through.
                if value is not None and not isinstance(value, ClauseElement):
                    ensure_in_range(value, _low, _high, _where, _error)

            event.listen(instrumented, "set", _check)
            guarded.append((table, name))
    return guarded


__all__ = [
    "IntegerOutOfRangeError",
    "QuantityOutOfRangeError",
    "ensure_in_range",
    "install_range_guards",
]
