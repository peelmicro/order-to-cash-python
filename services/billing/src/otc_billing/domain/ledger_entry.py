"""`CreditLedgerEntry`: one append-only row of a credit line's ledger (B2).

A frozen value with no mutator: attribute assignment raises `FrozenInstanceError`, and the
aggregate exposes its entries only as a tuple. It refuses a NEGATIVE amount (it would raise the
available credit) and accepts zero (`BC38`, gate point G1 as recommended). `order_reference` stays a
`str`, never parsed by the kernel's canonical `OrderNumber` (Fulfillment's L23 / FS28).
"""

from dataclasses import dataclass
from datetime import datetime

from otc_billing.domain.credit_entry_type import CreditEntryType
from otc_billing.domain.errors import NegativeLedgerAmountError
from otc_shared_kernel import Money, UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CreditLedgerEntry:
    entry_id: UniqueId
    order_reference: str
    amount: Money
    type: CreditEntryType
    entry_date: datetime

    def __post_init__(self) -> None:
        if self.amount.is_negative:
            raise NegativeLedgerAmountError(self.amount.amount, self.amount.currency)
