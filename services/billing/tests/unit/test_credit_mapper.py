"""Rows <-> snapshots, field by field (task D2). The mapper is the only constructor of `CreditItem`
rows; `updated_at == created_at` on a new row (the ledger is append-only).

Loop scope: nothing here is async.
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone

from otc_billing.domain.credit_entry_type import CreditEntryType
from otc_billing.domain.ledger_entry import CreditLedgerEntry
from otc_billing.infrastructure.persistence import credit_mapper
from otc_billing.infrastructure.persistence.models import Credit, CreditItem
from otc_shared_kernel import Money, UniqueId

WHEN = datetime(2026, 10, 8, 9, 30, 15, 123000, tzinfo=UTC)
CREATED = datetime(2026, 10, 8, 9, 31, 0, 456000, tzinfo=UTC)


def _uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(int=n))


def test_a_new_item_row_carries_every_field_and_updated_at_equals_created_at() -> None:
    entry = CreditLedgerEntry(
        entry_id=_uid(0xE1),
        order_reference="ORD-000101",
        amount=Money(4210, "EUR"),
        type=CreditEntryType.RELEASE,
        entry_date=WHEN,
    )
    row = credit_mapper.new_item_row(entry, _uid(0x1D), CREATED)
    assert row.id == uuid.UUID(int=0xE1)
    assert row.credit_id == uuid.UUID(int=0x1D)
    assert (row.order_reference, row.amount, row.type) == ("ORD-000101", 4210, "release")
    assert row.credit_date == WHEN
    assert row.created_at == CREATED
    assert row.updated_at == CREATED, "updated_at must be the same instant as created_at"
    assert type(row.amount) is int


def test_rows_map_to_a_snapshot_field_by_field_keeping_the_aware_instant() -> None:
    line = Credit(
        id=uuid.UUID(int=0x1D),
        code="CR-000321",
        retailer_code="RETAIL-77",
        company_code="SUPPLY-CO",
        credit_limit=1000,
        currency_code="EUR",
        created_at=CREATED,
        updated_at=CREATED,
    )
    madrid = timezone(timedelta(hours=2))
    item = CreditItem(
        id=uuid.UUID(int=0xE1),
        credit_id=line.id,
        order_reference="ORD-000101",
        amount=250,
        type="hold",
        credit_date=WHEN.astimezone(madrid),
        created_at=CREATED,
        updated_at=CREATED,
    )
    snapshot = credit_mapper.credit_snapshot(line, 250, [item])
    assert (snapshot.id, snapshot.code, snapshot.retailer_code, snapshot.company_code) == (
        _uid(0x1D),
        "CR-000321",
        "RETAIL-77",
        "SUPPLY-CO",
    )
    assert (snapshot.currency, snapshot.credit_limit, snapshot.committed_exposure) == (
        "EUR",
        1000,
        250,
    )
    [entry] = snapshot.entries
    assert (entry.entry_id, entry.order_reference, entry.amount, entry.type) == (
        _uid(0xE1),
        "ORD-000101",
        Money(250, "EUR"),
        CreditEntryType.HOLD,
    )
    assert entry.entry_date == WHEN
