"""`require_utc`: an instant given to the aggregate is unambiguous UTC (design.md L13).

A naive `datetime` type-checks under `mypy --strict` and would be read as local time by any later
conversion, so the domain refuses it where it enters.
"""

from datetime import datetime, timedelta

from otc_orders.domain.errors import InstantNotUtcError


def require_utc(value: datetime, *, field: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise InstantNotUtcError(field, value)
