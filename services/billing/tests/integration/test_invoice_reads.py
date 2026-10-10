"""`SqlAlchemyInvoiceReads`: the fast path and the paged list, against a real PostgreSQL (task D5).

BI15: the four filters, the ordering `invoice_date DESC, invoice_reference DESC`, paging and
`page.total`, the inclusive cutoff against a SUPPLIED `now` far from the wall clock, a read that
takes no lock and writes nothing.

Fixture: `now` is 2031-03-15 12:00 UTC, five years from any run, so an adapter that reads the wall
clock instead of the supplied `now` returns a different answer. Six invoices at distinct minutes
before `now` (two EXACTLY at the 60-minute cutoff, one at 59, one at 180, one at 30, one at 5),
three retailer/company combinations that cross (so the retailer filter is not the company filter),
two statuses.

Loop scope: function.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from otc_billing.application.messages import InvoicePage
from otc_billing.domain.invoice_state import InvoiceStatus
from otc_billing.infrastructure.persistence.invoice_reads import SqlAlchemyInvoiceReads

NOW = datetime(2031, 3, 15, 12, 0, 0, tzinfo=UTC)
R77, R88 = "RETAIL-77", "RETAIL-88"
S_CO, S_88 = "SUPPLY-CO", "SUPPLY-88"
LINES = [("PRD-ZZ", 3, 1999), ("PRD-AA", 2, 1234)]  # 8465

# (n, retailer, company, minutes before NOW, status)
ROWS = [
    (501, R77, S_CO, 180, "paid"),
    (502, R77, S_CO, 60, "issued"),
    (503, R88, S_CO, 60, "issued"),
    (504, R77, S_88, 59, "issued"),
    (505, R88, S_88, 30, "paid"),
    (506, R77, S_CO, 5, "issued"),
]


def at(minutes: int) -> datetime:
    return NOW - timedelta(minutes=minutes)


async def seed(db: Any) -> None:
    for n, retailer, company, minutes, status in ROWS:
        await db.seed_invoice(
            f"ORD-000{n}",
            retailer_code=retailer,
            company_code=company,
            reference=f"INV-000{n}",
            lines=LINES,
            discount=350 + n,
            invoice_date=at(minutes),
            status=status,
            paid_at=at(minutes - 1) if status == "paid" else None,
        )


async def list_refs(
    reads: SqlAlchemyInvoiceReads, now: datetime = NOW, **filters: Any
) -> tuple[int, list[str]]:
    page = await reads.list(
        **{
            "page": 1,
            "page_size": 25,
            "status": None,
            "retailer_code": None,
            "company_code": None,
            "order_reference": None,
            "issued_before_minutes": None,
            "now": now,
            **filters,
        }
    )
    return page.total, [item.invoice_reference[-3:] for item in page.items]


async def snapshot_of_everything(db: Any) -> dict[str, list[dict[str, Any]]]:
    return {
        table: [dict(r) for r in await db.fetch(f"SELECT * FROM {table} ORDER BY id")]  # noqa: S608
        for table in ("invoices", "invoice_items", "credit_items", "credits")
    } | {"outbox_count": [{"n": await db.count("outbox")}]}


async def test_bi15_the_cutoff_is_the_supplied_now_and_nothing_is_written(
    db: Any, make_invoice_store: Any
) -> None:
    await seed(db)
    store = make_invoice_store()
    reads = SqlAlchemyInvoiceReads(store.sessions)
    before = await snapshot_of_everything(db)

    # the page's total first, then the references in order (invoice_date DESC, reference DESC)
    assert await list_refs(reads) == (6, ["506", "505", "504", "503", "502", "501"])
    # the four filters, each alone
    assert await list_refs(reads, status=InvoiceStatus.PAID) == (2, ["505", "501"])
    assert await list_refs(reads, status=InvoiceStatus.ISSUED) == (4, ["506", "504", "503", "502"])
    assert await list_refs(reads, retailer_code=R77) == (4, ["506", "504", "502", "501"])
    assert await list_refs(reads, company_code=S_CO) == (4, ["506", "503", "502", "501"])
    assert await list_refs(reads, order_reference="ORD-000503") == (1, ["503"])
    # combined
    assert await list_refs(reads, retailer_code=R77, company_code=S_CO) == (
        3,
        ["506", "502", "501"],
    )
    assert await list_refs(
        reads,
        status=InvoiceStatus.ISSUED,
        retailer_code=R77,
        company_code=S_CO,
        issued_before_minutes=60,
    ) == (1, ["502"])
    # the filters are exact and case-sensitive
    assert await list_refs(reads, retailer_code="retail-77") == (0, [])
    assert await list_refs(reads, order_reference="ORD-000999") == (0, [])

    # the cutoff is INCLUSIVE and measured from the SUPPLIED now: 502 and 503 are exactly 60 minutes
    # old, 504 is 59
    assert await list_refs(reads, issued_before_minutes=60) == (3, ["503", "502", "501"])
    assert await list_refs(reads, issued_before_minutes=59) == (4, ["504", "503", "502", "501"])
    assert await list_refs(reads, issued_before_minutes=61) == (1, ["501"])
    assert await list_refs(reads, issued_before_minutes=0) == (
        6,
        ["506", "505", "504", "503", "502", "501"],
    )
    # the same query against a `now` ten minutes later moves the cutoff with it (to 50 minutes
    # before the fixture's `now`: 504, 503, 502 and 501 qualify) (the supplied one
    # decides, never the wall clock)
    assert await list_refs(reads, now=NOW + timedelta(minutes=10), issued_before_minutes=60) == (
        4,
        ["504", "503", "502", "501"],
    )

    # paging and page.total
    pages = [
        await reads.list(
            page=n,
            page_size=2,
            status=None,
            retailer_code=None,
            company_code=None,
            order_reference=None,
            issued_before_minutes=None,
            now=NOW,
        )
        for n in (1, 2, 3, 4)
    ]
    assert [p.total for p in pages] == [6, 6, 6, 6]
    assert [[i.invoice_reference[-3:] for i in p.items] for p in pages] == [
        ["506", "505"],
        ["504", "503"],
        ["502", "501"],
        [],
    ]
    assert (pages[1].page, pages[1].page_size) == (2, 2)

    # a view's every field, read back through the adapter (505 is paid, 506 issued)
    full = await reads.list(
        page=1,
        page_size=25,
        status=None,
        retailer_code=None,
        company_code=None,
        order_reference="ORD-000505",
        issued_before_minutes=None,
        now=NOW,
    )
    [paid_view] = full.items
    assert isinstance(full, InvoicePage)
    assert (paid_view.amount, paid_view.discount, paid_view.total_amount) == (8465, 855, 7610)
    assert paid_view.status is InvoiceStatus.PAID
    assert paid_view.paid_at == at(29)
    assert (paid_view.retailer_code, paid_view.company_code) == (R88, S_88)
    assert paid_view.order_reference == "ORD-000505"
    assert paid_view.invoice_date == at(30)
    [issued_view] = (
        await reads.list(
            page=1,
            page_size=25,
            status=None,
            retailer_code=None,
            company_code=None,
            order_reference="ORD-000506",
            issued_before_minutes=None,
            now=NOW,
        )
    ).items
    assert issued_view.paid_at is None

    # nothing was written by any of the above (every row of every write table is unchanged)
    assert await snapshot_of_everything(db) == before


async def test_find_by_order_reference_takes_no_lock(
    db: Any, migrated_db: Any, make_invoice_store: Any
) -> None:
    await seed(db)
    store = make_invoice_store()
    reads = SqlAlchemyInvoiceReads(store.sessions)
    holder = await asyncpg.connect(migrated_db.dsn)
    transaction = holder.transaction()
    await transaction.start()
    try:
        # the test's own connection holds the invoice row (and its lines) FOR UPDATE
        await holder.fetch(
            "SELECT id FROM invoices WHERE order_reference = 'ORD-000502' FOR UPDATE"
        )
        await holder.fetch(
            "SELECT i.id FROM invoice_items i JOIN invoices v ON v.id = i.invoice_id"
            " WHERE v.order_reference = 'ORD-000502' FOR UPDATE OF i"
        )
        try:
            async with asyncio.timeout(5):
                snapshot = await reads.find_by_order_reference("ORD-000502")
        except TimeoutError:
            raise AssertionError(
                "L9: the fast-path read blocked on a row another transaction holds FOR UPDATE: "
                "it must take no lock and wait for none"
            ) from None
        assert snapshot is not None
        assert snapshot.invoice_reference.value == "INV-000502"
        assert len(snapshot.lines) == 2
        # control: an order that does not exist reads None without waiting either
        assert await reads.find_by_order_reference("ORD-000999") is None
    finally:
        await transaction.rollback()
        await holder.close()
