"""`RawJson`: a `json` column that stores and returns the TEXT the application serialised.

SQLAlchemy's own `JSON` type calls `json.dumps` on bind and `json.loads` on read, which would
re-serialise (and therefore re-order and re-space) a payload that `otc_contracts.wire.to_wire_json`
already wrote. This type is passthrough, and the column type is `json`, not `jsonb` (jsonb
normalises keys and whitespace on the way in).

Reads select `payload::text`: SQLAlchemy's asyncpg dialect installs a `json` codec that `json.loads`
every json value into a dict (measured: the first version of this test got a `dict` back), which
would discard the byte-exact text. Casting in SQL makes asyncpg use its text codec instead. Writes
bind the `str` as it is.
"""

from typing import Any

from sqlalchemy import ColumnElement, Text, cast
from sqlalchemy.types import UserDefinedType


class RawJson(UserDefinedType[str]):
    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "JSON"

    def column_expression(self, colexpr: ColumnElement[Any]) -> ColumnElement[Any]:
        return cast(colexpr, Text)
