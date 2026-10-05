"""`RawJson`: a `json` column that stores the TEXT the seed serialised, byte for byte.

SQLAlchemy's own `JSON` type would `json.dumps` the bound value again (re-spacing and re-ordering a
payload that `otc_contracts.wire.to_wire_json` already wrote). This type is passthrough, and the
column type is `json`, not `jsonb` (jsonb normalises keys and whitespace on the way in). Reads in
tests select `payload::text` for the same reason. The services carry the same class in their own
`persistence/types.py`; the seed may not import a service, so it has its own.
"""

from sqlalchemy.types import UserDefinedType


class RawJson(UserDefinedType[str]):
    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "JSON"
