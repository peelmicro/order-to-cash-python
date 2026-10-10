"""Rows <-> snapshots, and the ONLY constructor of `CreditItem` rows (`design.md` 9.2).

`credit_items.amount` is written ONLY through the `CreditItem(...)` constructor here, with a plain
`int`: that is what fires the range guard (`range_guards.install_range_guards`, the ORM attribute
event). An `insert(...).values(...)`, a `text()` or a SQL expression bypasses it and surfaces as the
engine's own `DBAPIError`. `tests/architecture/test_write_path_population.py` makes any other write
path an unclassified hit.

`credit_date` is kept as the aware `datetime` asyncpg returned, untouched (BC24, L14): asyncpg's
binary decode of `timestamptz` is UTC whatever the session `TimeZone` is, and this module neither
re-attaches nor converts a zone. `updated_at` is written equal to `created_at` and never changed
(the ledger is append-only, `design.md` 1).
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from otc_billing.domain.credit_entry_type import parse_credit_entry_type
from otc_billing.domain.ledger_entry import CreditLedgerEntry
from otc_billing.domain.snapshot import BuyerCreditSnapshot, CreditLedgerEntrySnapshot
from otc_billing.infrastructure.persistence.models import Credit, CreditItem
from otc_shared_kernel import Money, UniqueId


def _unique_id(value: UUID) -> UniqueId:
    """asyncpg hands back its own `UUID` subclass (`asyncpg.pgproto.pgproto.UUID`), which the
    domain's `type(...) is uuid.UUID` check refuses (measured in Orders' mapper); rebuild a plain
    `uuid.UUID`."""
    return UniqueId(UUID(int=value.int))


def entry_snapshot(row: CreditItem, currency: str) -> CreditLedgerEntrySnapshot:
    return CreditLedgerEntrySnapshot(
        entry_id=_unique_id(row.id),
        order_reference=row.order_reference,
        amount=Money(row.amount, currency),
        type=parse_credit_entry_type(row.type),
        entry_date=row.credit_date,
    )


def credit_snapshot(
    row: Credit, committed_exposure: int, items: Sequence[CreditItem]
) -> BuyerCreditSnapshot:
    return BuyerCreditSnapshot(
        id=_unique_id(row.id),
        code=row.code,
        retailer_code=row.retailer_code,
        company_code=row.company_code,
        currency=row.currency_code,
        credit_limit=row.credit_limit,
        committed_exposure=committed_exposure,
        entries=tuple(entry_snapshot(item, row.currency_code) for item in items),
    )


def new_item_row(entry: CreditLedgerEntry, credit_id: UniqueId, created_at: datetime) -> CreditItem:
    return CreditItem(
        id=entry.entry_id.value,
        credit_id=credit_id.value,
        order_reference=entry.order_reference,
        amount=entry.amount.amount,
        type=entry.type.value,
        credit_date=entry.entry_date,
        created_at=created_at,
        updated_at=created_at,
    )
