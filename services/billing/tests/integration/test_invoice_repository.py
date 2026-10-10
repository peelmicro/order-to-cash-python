"""The invoice repository and its transaction against a real PostgreSQL (tasks D3, F3).

BI7 (one transaction, both aggregates, one outbox row, one rollback), BI10's store half (a stored
row whose `status` and `paid_at` disagree is refused by the mapper), BI24 (instants through the
mapper under a non-UTC session, `NULL` stays `NULL`) and the canonical reload order of the lines
(L15).

Fixtures: the order `ORD-000101`, retailer `RETAIL-77`, company `SUPPLY-CO`; the lines are sent in
the order PRD-ZZ, PRD-AA (NOT canonical); amount 8465, discount 350, total 8115 (the hold).

Loop scope: function. The engines are created by the conftest's `make_invoice_store` and disposed
there, in the loop that made them.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from otc_billing.application import invoice_issue
from otc_billing.application.messages import InvoiceIssueResult, IssueInvoiceCommand, IssueLine
from otc_billing.application.ports.credit_store import CreditTransaction, CreditTransactions
from otc_billing.application.scope import BillingScope
from otc_billing.domain.invoice_errors import InvalidInvoiceSnapshotError, UnknownInvoiceStatusError
from otc_billing.domain.invoice_snapshot import InvoiceSnapshot
from otc_billing.domain.invoice_state import Issued, Paid
from otc_billing.infrastructure.clock import SystemClock
from otc_billing.infrastructure.credit.always_approve import AlwaysApproveCreditDecision
from otc_billing.infrastructure.ids import UuidIdSource
from otc_billing.infrastructure.persistence.credit_reads import SqlAlchemyCreditReads
from otc_billing.infrastructure.persistence.invoice_reads import SqlAlchemyInvoiceReads
from otc_shared_kernel import UniqueId

RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
ORDER = "ORD-000101"
SECOND = "ORD-000202"
HOLD = 8115
INVOICE_DATE = datetime(2026, 10, 9, 10, 15, 30, 123000, tzinfo=UTC)
PAID_AT = datetime(2026, 10, 11, 17, 45, 59, 987000, tzinfo=UTC)
LINES = [("PRD-ZZ", 3, 1999), ("PRD-AA", 2, 1234)]  # 8465; not in canonical order

MakeStore = Callable[..., Any]


def _command(order: str = ORDER) -> IssueInvoiceCommand:
    return IssueInvoiceCommand(
        order_reference=order,
        retailer_code=RETAILER,
        company_code=COMPANY,
        currency="EUR",
        lines=tuple(IssueLine(product_code=c, units=u, unit_price=p) for c, u, p in LINES),
        discount=350,
        correlation_id=UniqueId(uuid.uuid4()),
        request_id=UniqueId(uuid.uuid4()),
    )


class FailAfterWork:
    """The real transactions object, but the unit of work raises after it returned: both aggregates
    have saved, the commit has not happened (a forced rollback)."""

    def __init__(self, inner: CreditTransactions) -> None:
        self._inner = inner

    async def run[T](self, work: Callable[[CreditTransaction], Awaitable[T]]) -> T:
        async def wrapped(tx: CreditTransaction) -> T:
            await work(tx)
            raise RuntimeError("injected after both saves, before commit")

        return await self._inner.run(wrapped)


def _scope(store: Any, *, fail_after_work: bool = False) -> BillingScope:
    transactions: CreditTransactions = (
        FailAfterWork(store.transactions) if fail_after_work else store.transactions
    )
    return BillingScope(
        transactions=transactions,
        reads=SqlAlchemyCreditReads(store.sessions),
        invoice_reads=SqlAlchemyInvoiceReads(store.sessions),
        clock=SystemClock(),
        ids=UuidIdSource(),
        credit_decision=AlwaysApproveCreditDecision(),
    )


async def _read(store: Any, order: str) -> InvoiceSnapshot | None:
    seen: list[InvoiceSnapshot | None] = []

    async def read(tx: CreditTransaction) -> None:
        seen.append(await tx.invoices.find_by_order_reference(order))

    await store.transactions.run(read)
    return seen[0]


async def _snapshot_of_run(store: Any, order: str) -> BaseException | InvoiceSnapshot | None:
    try:
        return await _read(store, order)
    except Exception as error:
        return error


# ------------------------------------------------------------------------------- BI10 (store)


async def test_bi10_a_stored_row_whose_status_and_paid_at_disagree_is_refused_by_the_mapper(
    db: Any, make_invoice_store: MakeStore
) -> None:
    kwargs: dict[str, Any] = {
        "retailer_code": RETAILER,
        "company_code": COMPANY,
        "lines": LINES,
        "discount": 350,
        "invoice_date": INVOICE_DATE,
    }
    await db.seed_invoice(
        "ORD-000301", reference="INV-000301", status="paid", paid_at=None, **kwargs
    )
    await db.seed_invoice(
        "ORD-000302", reference="INV-000302", status="issued", paid_at=PAID_AT, **kwargs
    )
    await db.seed_invoice(
        "ORD-000303", reference="INV-000303", status="Paid", paid_at=PAID_AT, **kwargs
    )
    await db.seed_invoice(
        "ORD-000304", reference="INV-000304", status="issued", **kwargs
    )  # control
    store = make_invoice_store()

    paid_without = await _snapshot_of_run(store, "ORD-000301")
    assert isinstance(paid_without, InvalidInvoiceSnapshotError), (
        f"BI10: a `paid` row with a NULL paid_at became {paid_without!r}"
    )
    assert "INV-000301" in paid_without.message, "BI10: the error does not name the invoice"
    issued_with = await _snapshot_of_run(store, "ORD-000302")
    assert isinstance(issued_with, InvalidInvoiceSnapshotError), (
        f"BI10: an `issued` row with a paid_at became {issued_with!r}"
    )
    capitalised = await _snapshot_of_run(store, "ORD-000303")
    assert isinstance(capitalised, UnknownInvoiceStatusError), (
        f"BI27: a hand-written 'Paid' row became {capitalised!r}"
    )
    # the control row loads
    control = await _snapshot_of_run(store, "ORD-000304")
    assert isinstance(control, InvoiceSnapshot), f"the control row did not load: {control!r}"
    assert control.state == Issued()


# ------------------------------------------------------------------------------------- BI24


async def test_bi24_invoice_date_and_paid_at_read_back_unchanged_through_the_mapper_under_a_non_utc_session_and_null_stays_null(  # noqa: E501
    db: Any, make_invoice_store: MakeStore
) -> None:
    kwargs: dict[str, Any] = {
        "retailer_code": RETAILER,
        "company_code": COMPANY,
        "lines": LINES,
        "discount": 350,
        "invoice_date": INVOICE_DATE,
    }
    await db.seed_invoice(
        "ORD-000401", reference="INV-000401", status="paid", paid_at=PAID_AT, **kwargs
    )
    await db.seed_invoice("ORD-000402", reference="INV-000402", status="issued", **kwargs)
    store = make_invoice_store(server_settings={"TimeZone": "Europe/Madrid"})
    async with store.sessions() as session:
        zone = await session.scalar(text("SHOW TimeZone"))
    assert zone == "Europe/Madrid", "the session time zone was not applied"

    paid = await _snapshot_of_run(store, "ORD-000401")
    assert isinstance(paid, InvoiceSnapshot), f"BI24: the paid row did not load: {paid!r}"
    assert paid.invoice_date == INVOICE_DATE, (
        f"BI24: wrote {INVOICE_DATE}, read {paid.invoice_date}"
    )
    assert paid.invoice_date.utcoffset() == timedelta(0)
    assert isinstance(paid.state, Paid)
    assert paid.state.paid_at == PAID_AT, f"BI24: wrote {PAID_AT}, read {paid.state.paid_at}"
    assert paid.state.paid_at.utcoffset() == timedelta(0), (
        f"BI24: read back {paid.state.paid_at}, offset {paid.state.paid_at.utcoffset()}, not UTC"
    )
    # the nullable case: NULL stays NULL (an issued invoice has no paid_at)
    issued = await _snapshot_of_run(store, "ORD-000402")
    assert isinstance(issued, InvoiceSnapshot), (
        f"BI24: a NULL paid_at did not stay NULL, the read raised {issued!r}"
    )
    assert issued.state == Issued()


# --------------------------------------------------------------------------- L15 (line order)


async def test_a_reload_returns_the_lines_in_canonical_order_for_an_invoice_saved_in_another_order(
    db: Any, make_invoice_store: MakeStore
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=500_000, code=CODE)
    await db.plant_entry((await db.fetch("SELECT id FROM credits"))[0]["id"], ORDER, HOLD, "hold")
    store = make_invoice_store()
    result = await invoice_issue.issue(_command(), _scope(store))
    assert result.created is True

    snapshot = await _read(store, ORDER)
    assert snapshot is not None
    assert [(ln.product_code, ln.units.value, ln.unit_price.amount) for ln in snapshot.lines] == [
        ("PRD-AA", 2, 1234),
        ("PRD-ZZ", 3, 1999),
    ], "L15: the reload is not in canonical (product_code, id) order"
    # the request's order was the other one (the fixture is not canonical)
    assert [c for c, _, _ in LINES] == ["PRD-ZZ", "PRD-AA"]


# ------------------------------------------------------------------------------------- BI7


async def _counts(db: Any) -> dict[str, int]:
    return {
        table: await db.count(table)
        for table in ("invoices", "invoice_items", "credit_items", "outbox")
    }


async def test_bi7_commits_invoice_lines_consume_entry_and_one_outbox_row_together_and_leaves_none_after_a_rollback(  # noqa: E501
    db: Any, make_invoice_store: MakeStore
) -> None:
    credit_id = await db.seed_line(RETAILER, COMPANY, limit=500_000, code=CODE)
    await db.plant_entry(credit_id, ORDER, HOLD, "hold")
    await db.plant_entry(credit_id, SECOND, 4321, "hold")
    store = make_invoice_store()
    before = await _counts(db)
    assert before == {"invoices": 0, "invoice_items": 0, "credit_items": 2, "outbox": 0}
    [line_before] = await db.fetch("SELECT updated_at FROM credits WHERE id = $1", credit_id)
    assert await db.invoice_counter() is None

    # ---- the commit: both aggregates through ONE real run
    result = await invoice_issue.issue(_command(), _scope(store))

    assert isinstance(result, InvoiceIssueResult)
    assert result.created is True
    after = await _counts(db)
    assert after["invoices"] - before["invoices"] == 1, "expected exactly one new invoices row"
    assert after["invoice_items"] - before["invoice_items"] == 2, "expected the two line rows"
    assert after["credit_items"] - before["credit_items"] == 1, "expected exactly one consume row"
    assert after["outbox"] - before["outbox"] == 1, (
        "expected a whole-table outbox delta of exactly 1"
    )
    consumes = await db.fetch("SELECT * FROM credit_items WHERE type = 'consume'")
    assert len(consumes) == 1
    assert (consumes[0]["order_reference"], consumes[0]["amount"]) == (ORDER, HOLD)
    [invoice] = await db.invoices_of(ORDER)
    assert (invoice["amount"], invoice["discount"], invoice["total_amount"]) == (8465, 350, 8115)
    assert await db.invoice_counter() == 2, "the counter advanced exactly once"
    [event] = await db.outbox()
    assert event["event_type"] == "invoice.issued.v1"
    [line_after] = await db.fetch("SELECT updated_at FROM credits WHERE id = $1", credit_id)
    assert line_after["updated_at"] == line_before["updated_at"], "the credits row was written"

    # ---- the rollback: a second order, the same run, forced to fail after BOTH saves
    committed = await _counts(db)
    counter = await db.invoice_counter()
    with pytest.raises(RuntimeError, match="injected after both saves"):
        await invoice_issue.issue(_command(SECOND), _scope(store, fail_after_work=True))
    assert await _counts(db) == committed, (
        "BI7: a rolled-back issue left an invoice, a line, a consume row or an outbox row"
    )
    assert await db.invoices_of(SECOND) == []
    assert await db.invoice_counter() == counter, "a rolled-back issue burned an invoice number"
    [line_final] = await db.fetch("SELECT updated_at FROM credits WHERE id = $1", credit_id)
    assert line_final["updated_at"] == line_before["updated_at"]

    # ---- the control: the same second order, committed, leaves one of each
    again = await invoice_issue.issue(_command(SECOND), _scope(store))
    assert again.created is True
    final = await _counts(db)
    assert final["invoices"] - committed["invoices"] == 1
    assert final["credit_items"] - committed["credit_items"] == 1
    assert final["outbox"] - committed["outbox"] == 1
    assert again.invoice.invoice_reference == "INV-000002"
