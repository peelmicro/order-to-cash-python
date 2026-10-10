"""`CreditEntryType`: the closed set of ledger entry kinds (`hold`, `consume`, `release`).

A plain `Enum` (not `StrEnum`): a raw `"hold"` read from a row never compares equal to
`CreditEntryType.HOLD` and must be parsed. Tokens are written out, never derived from member names
(the Orders `OrderStatus` convention). The parse is exact: case- and whitespace-sensitive, and a
`str` subclass is refused (`type(...) is str`), so an unknown token is loud (`BC37`, L15).
"""

from enum import Enum

from otc_billing.domain.errors import UnknownCreditEntryTypeError


class CreditEntryType(Enum):
    HOLD = "hold"
    CONSUME = "consume"
    RELEASE = "release"


_BY_TOKEN: dict[str, CreditEntryType] = {
    "hold": CreditEntryType.HOLD,
    "consume": CreditEntryType.CONSUME,
    "release": CreditEntryType.RELEASE,
}


def parse_credit_entry_type(token: object) -> CreditEntryType:
    if type(token) is not str or token not in _BY_TOKEN:
        raise UnknownCreditEntryTypeError(token)
    return _BY_TOKEN[token]
