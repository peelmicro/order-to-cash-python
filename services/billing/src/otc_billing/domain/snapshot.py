"""What `BuyerCredit.rehydrate` takes and `to_snapshot` returns: a stored credit line as business
values, built by the repository's row mapper (infrastructure); keyword-constructed.

The entries are only those of the ONE order the command names (as in #7 and #8); the line's
`committed_exposure` is the whole line's, computed in SQL (`BC5`), and reaches the domain as an
exact `int` (`BC37`). Timestamps of the rows are not here: `created_at` / `updated_at` are the
mapper's (the domain reads no clock).
"""

from dataclasses import dataclass
from datetime import datetime

from otc_billing.domain.credit_entry_type import CreditEntryType
from otc_shared_kernel import Money, UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CreditLedgerEntrySnapshot:
    entry_id: UniqueId
    order_reference: str
    amount: Money
    type: CreditEntryType
    entry_date: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class BuyerCreditSnapshot:
    id: UniqueId
    code: str
    retailer_code: str
    company_code: str
    currency: str
    credit_limit: int
    committed_exposure: int
    entries: tuple[CreditLedgerEntrySnapshot, ...]
