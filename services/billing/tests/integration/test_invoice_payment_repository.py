"""The invoice repository's payment half against a real PostgreSQL (feature 22; R47, R48).

`mark_paid` is the service's one UPDATE: it must move `status`, `paid_at` and `updated_at` of an
`issued` invoice and nothing else, insert the `payments` row, write the invoice's fact, and refuse
(as a transient failure) an invoice that is no longer `issued`. The reads return the stored values
through the mapper, never a raw row.

Fixtures: invoice `INV-000301` of order `ORD-000301` (lines PRD-ZZ 3 x 1999 + PRD-AA 2 x 1234,
discount 350, total 8115); the payment is of the NET and carries a value date that differs from
every other instant.

Loop scope: function. The engines come from the conftest's `make_invoice_store` and are disposed
there.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_billing.application.errors import PaymentReferenceReusedError
from otc_billing.application.ports.credit_store import CreditTransaction, StoreUnavailableError
from otc_billing.domain.invoice import Invoice, InvoiceContext, PaymentInput
from otc_billing.domain.invoice_events import PaymentSource
from otc_billing.domain.invoice_snapshot import PaymentSnapshot
from otc_billing.infrastructure.persistence.invoice_reads import SqlAlchemyInvoiceReads
from otc_shared_kernel import Money, UniqueId

RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
ORDER = "ORD-000301"
LINES = [("PRD-ZZ", 3, 1999), ("PRD-AA", 2, 1234)]
INVOICE_DATE = datetime(2026, 10, 9, 10, 15, 30, 123000, tzinfo=UTC)
PAID_AT = datetime(2026, 10, 11, 17, 45, 59, 987000, tzinfo=UTC)
VALUE_DATE = datetime(2026, 10, 9, 13, 45, 10, 123000, tzinfo=UTC)
NET = 8115

MakeStore = Callable[..., Any]


async def seed(db: Any, order: str = ORDER, reference: str = "INV-000301") -> uuid.UUID:
    return await db.seed_invoice(  # type: ignore[no-any-return]
        order,
        retailer_code=RETAILER,
        company_code=COMPANY,
        reference=reference,
        lines=LINES,
        discount=350,
        invoice_date=INVOICE_DATE,
    )


def payment_for(
    invoice_id: uuid.UUID, reference: str = "BANK-REF-7731", currency: str = "EUR"
) -> PaymentSnapshot:
    return PaymentSnapshot(
        id=UniqueId(uuid.uuid4()),
        payment_reference=reference,
        invoice_id=UniqueId(invoice_id),
        amount=Money(NET, currency),
        value_date=VALUE_DATE,
        source=PaymentSource.OPERATOR,
    )


async def mark_paid_in_tx(store: Any, invoice_id: uuid.UUID, payment: PaymentSnapshot) -> None:
    async def work(tx: CreditTransaction) -> None:
        snapshot = await tx.invoices.find_by_id(UniqueId(invoice_id))
        assert snapshot is not None
        invoice = Invoice.rehydrate(snapshot)
        n = iter(range(1, 50))
        invoice.mark_paid(
            PaymentInput(
                payment_reference=payment.payment_reference,
                amount=payment.amount,
                value_date=payment.value_date,
                source=payment.source,
                correlation_id=UniqueId(uuid.uuid4()),
            ),
            InvoiceContext(occurred_at=PAID_AT, causation_id=UniqueId(uuid.uuid4())),
            lambda: UniqueId(uuid.UUID(int=next(n))),
        )
        await tx.invoices.mark_paid(invoice, payment)

    await store.transactions.run(work)


async def test_r47_mark_paid_updates_only_status_paid_at_and_updated_at_and_inserts_the_payment_and_the_fact(  # noqa: E501
    db: Any, make_invoice_store: MakeStore
) -> None:
    invoice_id = await seed(db)
    other = await seed(db, "ORD-000302", "INV-000302")  # the control: another invoice stays issued
    before = await db.invoice_row(invoice_id)
    other_before = await db.invoice_row(other)
    store = make_invoice_store()
    payment = payment_for(invoice_id)

    await mark_paid_in_tx(store, invoice_id, payment)

    after = await db.invoice_row(invoice_id)
    assert (after["status"], after["paid_at"]) == ("paid", PAID_AT)
    assert after["updated_at"] > before["updated_at"], "updated_at was not moved"
    changed = {k for k in dict(after) if after[k] != before[k]}
    assert changed == {"status", "paid_at", "updated_at"}, f"the update touched {changed}"
    assert dict(await db.invoice_row(other)) == dict(other_before), "another invoice changed"
    [row] = await db.payments_of(invoice_id)
    assert row["id"] == payment.id.value
    assert (row["payment_reference"], row["amount"], row["currency_code"]) == (
        "BANK-REF-7731",
        NET,
        "EUR",
    )
    assert (row["value_date"], row["source"]) == (VALUE_DATE, "operator")
    [fact] = await db.outbox()
    assert fact["event_type"] == "payment.received.v1"
    assert fact["aggregate_id"] == invoice_id
    assert fact["payload"]["valueDate"] == "2026-10-09T13:45:10.123Z"


async def test_mark_paid_on_an_invoice_that_is_not_issued_is_a_transient_failure_and_writes_nothing(
    db: Any, make_invoice_store: MakeStore
) -> None:
    invoice_id = await seed(db)
    store = make_invoice_store()
    snapshots: list[Any] = []

    async def read(tx: CreditTransaction) -> None:
        snapshots.append(await tx.invoices.find_by_id(UniqueId(invoice_id)))

    await store.transactions.run(read)  # the stale snapshot: `issued`
    await db.execute(
        "UPDATE invoices SET status = 'paid', paid_at = $2 WHERE id = $1", invoice_id, PAID_AT
    )
    baseline = (await db.count("payments"), await db.count("outbox"))

    async def stale(tx: CreditTransaction) -> None:
        invoice = Invoice.rehydrate(snapshots[0])
        n = iter(range(1, 50))
        payment = payment_for(invoice_id)
        invoice.mark_paid(
            PaymentInput(
                payment_reference=payment.payment_reference,
                amount=payment.amount,
                value_date=payment.value_date,
                source=payment.source,
                correlation_id=UniqueId(uuid.uuid4()),
            ),
            InvoiceContext(occurred_at=PAID_AT, causation_id=UniqueId(uuid.uuid4())),
            lambda: UniqueId(uuid.UUID(int=next(n))),
        )
        await tx.invoices.mark_paid(invoice, payment)

    with pytest.raises(StoreUnavailableError):
        await store.transactions.run(stale)

    assert (await db.count("payments"), await db.count("outbox")) == baseline


async def test_r48_the_unique_constraint_on_the_payment_reference_is_the_reused_reference_refusal(
    db: Any, make_invoice_store: MakeStore
) -> None:
    first = await seed(db)
    second = await seed(db, "ORD-000302", "INV-000302")
    store = make_invoice_store()
    await mark_paid_in_tx(store, first, payment_for(first))
    baseline = (await db.count("payments"), await db.count("outbox"))

    with pytest.raises(PaymentReferenceReusedError) as caught:
        await mark_paid_in_tx(store, second, payment_for(second))

    assert caught.value.payment_reference == "BANK-REF-7731"
    assert (await db.count("payments"), await db.count("outbox")) == baseline
    assert (await db.invoice_row(second))["status"] == "issued", "the update was not rolled back"


async def test_r48_the_reads_return_the_stored_payment_and_invoice_through_the_mapper(
    db: Any, make_invoice_store: MakeStore
) -> None:
    invoice_id = await seed(db)
    store = make_invoice_store()
    await mark_paid_in_tx(store, invoice_id, payment_for(invoice_id))
    reads = SqlAlchemyInvoiceReads(store.sessions)

    stored = await reads.find_payment_by_reference("BANK-REF-7731")
    by_id = await reads.find_by_id(UniqueId(invoice_id))
    by_reference = await reads.find_by_invoice_reference("INV-000301")

    assert stored is not None, "R48: the payment read by its reference found nothing"
    assert stored.invoice_id == UniqueId(invoice_id)
    assert stored.amount == Money(NET, "EUR")
    assert (stored.value_date, stored.source) == (VALUE_DATE, PaymentSource.OPERATOR)
    assert by_id is not None, "R48: the invoice read by its id found nothing"
    assert by_reference is not None, "R48: the invoice read by its INV- reference found nothing"
    assert by_id == by_reference
    assert by_id.order_reference == ORDER
    assert await reads.find_payment_by_reference("BANK-REF-NONE") is None
    assert await reads.find_by_id(UniqueId(uuid.uuid4())) is None
    assert await reads.find_by_invoice_reference("INV-999999") is None


async def test_r48_a_stored_payment_carries_its_own_currency_not_a_default(
    db: Any, make_invoice_store: MakeStore
) -> None:
    invoice_id = await db.seed_invoice(
        "ORD-000401",
        retailer_code=RETAILER,
        company_code=COMPANY,
        reference="INV-000401",
        lines=LINES,
        discount=350,
        invoice_date=INVOICE_DATE,
        currency="USD",
    )
    store = make_invoice_store()
    payment = payment_for(invoice_id, "BANK-REF-USD", "USD")
    await mark_paid_in_tx(store, invoice_id, payment)
    reads = SqlAlchemyInvoiceReads(store.sessions)

    stored = await reads.find_payment_by_reference("BANK-REF-USD")

    assert stored is not None
    assert stored.amount == Money(NET, "USD"), f"the payment came back as {stored.amount}"
    [row] = await db.payments_of(invoice_id)
    assert row["currency_code"] == "USD"


async def test_the_in_transaction_payment_read_finds_the_stored_reference_and_only_it(
    db: Any, make_invoice_store: MakeStore
) -> None:
    invoice_id = await seed(db)
    store = make_invoice_store()
    payment = payment_for(invoice_id)
    await mark_paid_in_tx(store, invoice_id, payment)
    seen: dict[str, Any] = {}

    async def read(tx: CreditTransaction) -> None:
        seen["stored"] = await tx.invoices.find_payment_by_reference("BANK-REF-7731")
        seen["none"] = await tx.invoices.find_payment_by_reference("BANK-REF-NONE")

    await store.transactions.run(read)

    assert seen["stored"] == payment
    assert seen["none"] is None
