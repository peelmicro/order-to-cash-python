"""`billing.invoice.list` through the real lifespan (tasks G1, G2, G4; BI15, BI32, BI37).

Invoices are seeded at known instants relative to the HOST's clock (the handler reads the clock
port once and hands `now` to the adapter): two older than 60 minutes (120 and 90), three newer
(5, 3 and 1), none within a minute of the 60-minute cutoff, so a clock that moves while the test
runs cannot change the answer. Two retailer/company combinations that cross, two statuses.

Loop scope: function. The host and the caller are created and closed in the test's loop.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

R77, R88 = "RETAIL-77", "RETAIL-88"
S_CO, S_88 = "SUPPLY-CO", "SUPPLY-88"
LINES = [("PRD-ZZ", 3, 1999), ("PRD-AA", 2, 1234)]  # 8465

# (n, retailer, company, minutes before the host's clock, status)
ROWS = [
    (601, R77, S_CO, 120, "paid"),
    (602, R88, S_CO, 90, "issued"),
    (603, R77, S_88, 5, "issued"),
    (604, R88, S_88, 3, "paid"),
    (605, R77, S_CO, 1, "issued"),
]


async def seed(db: Any) -> datetime:
    start = datetime.now(UTC).replace(microsecond=0)
    for n, retailer, company, minutes, status in ROWS:
        date = start - timedelta(minutes=minutes)
        await db.seed_invoice(
            f"ORD-000{n}",
            retailer_code=retailer,
            company_code=company,
            reference=f"INV-000{n}",
            lines=LINES,
            discount=350 + n,
            invoice_date=date,
            status=status,
            paid_at=date + timedelta(minutes=1) if status == "paid" else None,
        )
    return start


def refs(listed: Any) -> list[str]:
    return [i.invoice_reference[-3:] for i in listed.items]


async def test_bi15_filters_pages_orders_and_applies_issued_before_minutes_against_the_supplied_now(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await seed(db)
    before = {
        table: [dict(r) for r in await db.fetch(f"SELECT * FROM {table} ORDER BY id")]  # noqa: S608
        for table in ("invoices", "invoice_items")
    }

    everything = decode.invoice_list(await rpc("billing.invoice.list", {}))
    assert everything.page.total == 5  # the page's own total FIRST
    assert refs(everything) == ["605", "604", "603", "602", "601"], "newest first"
    assert (everything.page.page, everything.page.page_size) == (1, 25)

    by_status = decode.invoice_list(await rpc("billing.invoice.list", {"status": "paid"}))
    assert by_status.page.total == 2
    assert refs(by_status) == ["604", "601"]
    issued = decode.invoice_list(await rpc("billing.invoice.list", {"status": "issued"}))
    assert issued.page.total == 3
    assert refs(issued) == ["605", "603", "602"]

    by_retailer = decode.invoice_list(await rpc("billing.invoice.list", {"retailerCode": R77}))
    assert by_retailer.page.total == 3
    assert refs(by_retailer) == ["605", "603", "601"]
    by_company = decode.invoice_list(await rpc("billing.invoice.list", {"companyCode": S_CO}))
    assert by_company.page.total == 3
    assert refs(by_company) == ["605", "602", "601"]
    by_order = decode.invoice_list(
        await rpc("billing.invoice.list", {"orderReference": "ORD-000604"})
    )
    assert by_order.page.total == 1
    assert refs(by_order) == ["604"]

    combined = decode.invoice_list(
        await rpc(
            "billing.invoice.list", {"status": "issued", "retailerCode": R77, "companyCode": S_CO}
        )
    )
    assert combined.page.total == 1
    assert refs(combined) == ["605"]

    # issuedBeforeMinutes: 60 returns exactly the two older than an hour
    old = decode.invoice_list(await rpc("billing.invoice.list", {"issuedBeforeMinutes": 60}))
    assert old.page.total == 2
    assert refs(old) == ["602", "601"]
    older = decode.invoice_list(
        await rpc("billing.invoice.list", {"issuedBeforeMinutes": 100, "status": "paid"})
    )
    assert refs(older) == ["601"]

    # paging
    second = decode.invoice_list(await rpc("billing.invoice.list", {"page": 2, "pageSize": 2}))
    assert (second.page.page, second.page.page_size, second.page.total) == (2, 2, 5)
    assert refs(second) == ["603", "602"]
    last = decode.invoice_list(await rpc("billing.invoice.list", {"page": 3, "pageSize": 2}))
    assert refs(last) == ["601"]

    # each item carries its own figures (three distinct totals, the discount per invoice)
    first = everything.items[0]
    assert (first.amount, first.discount, first.total_amount) == (8465, 955, 7510)
    assert (first.retailer_code, first.company_code, first.order_reference) == (
        R77,
        S_CO,
        "ORD-000605",
    )

    # every row, re-read afterwards, is unchanged: a list writes nothing
    after = {
        table: [dict(r) for r in await db.fetch(f"SELECT * FROM {table} ORDER BY id")]  # noqa: S608
        for table in ("invoices", "invoice_items")
    }
    assert after == before


async def test_bi32_an_issued_view_writes_paid_at_null_and_a_paid_view_the_instant_in_the_raw_reply(
    billing_host: Any, db: Any, nats_client: Any
) -> None:
    issued_date = datetime(2026, 10, 9, 8, 15, 30, 123000, tzinfo=UTC)
    paid_date = datetime(2026, 10, 10, 9, 20, 40, 456000, tzinfo=UTC)
    await db.seed_invoice(
        "ORD-000701",
        retailer_code=R77,
        company_code=S_CO,
        reference="INV-000701",
        lines=LINES,
        discount=351,
        invoice_date=issued_date,
    )
    await db.seed_invoice(
        "ORD-000702",
        retailer_code=R88,
        company_code=S_88,
        reference="INV-000702",
        lines=LINES,
        discount=352,
        invoice_date=paid_date,
        status="paid",
        paid_at=datetime(2026, 10, 11, 17, 45, 59, 987000, tzinfo=UTC),
    )

    async def raw(body: dict[str, Any]) -> str:
        message = await nats_client.request(
            "billing.invoice.list", json.dumps(body).encode(), timeout=15
        )
        return str(message.data.decode("utf-8"))

    # the RAW bytes of a list holding one issued and one paid invoice
    both = await raw({})
    assert json.loads(both)["page"]["total"] == 2  # the discriminating field, first
    assert both.count('"paidAt":null') == 1, 'BI32: expected exactly one `"paidAt":null`'
    assert both.count('"paidAt":"2026-10-11T17:45:59.987Z"') == 1, (
        "BI32: the paid view does not carry the instant it was paid"
    )
    assert both.count("null") == 1, "BI32: no other null may appear in an invoice reply"

    # each state alone, parsed: the key is present for both
    only_issued = json.loads(await raw({"status": "issued"}))
    assert only_issued["page"]["total"] == 1
    assert "paidAt" in only_issued["items"][0]
    assert only_issued["items"][0]["paidAt"] is None
    only_paid = json.loads(await raw({"status": "paid"}))
    assert only_paid["page"]["total"] == 1
    assert only_paid["items"][0]["paidAt"] == "2026-10-11T17:45:59.987Z"


async def test_bi37_a_page_past_int64_and_an_age_before_year_one_answer_an_empty_page_with_the_true_total(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await seed(db)
    past_int64 = (1 << 63) // 25 + 2  # offset (page - 1) x 25 is above 2**63 - 1

    far = await rpc("billing.invoice.list", {"page": past_int64, "pageSize": 25})

    listed = decode.invoice_list(far)  # asserts `page.total` is present: NOT an RpcError
    assert listed.items == []
    assert listed.page.total == 5, "the page is empty but the total is the true one"
    assert (listed.page.page, listed.page.page_size) == (past_int64, 25)

    ancient = decode.invoice_list(
        await rpc("billing.invoice.list", {"issuedBeforeMinutes": 2_000_000_000})
    )
    assert ancient.items == []
    assert ancient.page.total == 0, "no invoice is older than year 1"

    # the controls: page 1 returns the rows, and an in-range age filter still filters
    first = decode.invoice_list(await rpc("billing.invoice.list", {"page": 1, "pageSize": 25}))
    assert first.page.total == 5
    assert len(first.items) == 5
    sane = decode.invoice_list(await rpc("billing.invoice.list", {"issuedBeforeMinutes": 60}))
    assert refs(sane) == ["602", "601"]
