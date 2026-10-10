"""`billing.credit.list` through the real lifespan (task H6; BC6, BC32).

Four credit lines carry the four ledger shapes the system can write, planted as ledger rows; the
reply must reconcile on EVERY line: `activeHolds + openExposure = creditLimit - availableCredit`.
The listing reads plain rows (no lock, no write) and filters and pages at SQL level.

Loop scope: function. The host and the caller are created and closed in the test's loop.
"""

from typing import Any

LIMIT = 100_000
# (retailer, company, code, entries as (order, amount, type)) -> activeHolds, openExposure
LINES = [
    ("RETAIL-A1", "SUPPLY-CO", "CR-000411", [("ORD-000101", 4210, "hold")], 4210, 0),
    (
        "RETAIL-B2",
        "SUPPLY-CO",
        "CR-000422",
        [("ORD-000101", 3120, "hold"), ("ORD-000101", 3120, "consume")],
        0,
        3120,
    ),
    (
        "RETAIL-C3",
        "SUPPLY-CO",
        "CR-000433",
        [("ORD-000101", 2030, "hold"), ("ORD-000101", 2030, "release")],
        0,
        0,
    ),
    (
        "RETAIL-D4",
        "SUPPLY-CO",
        "CR-000444",
        [
            ("ORD-000101", 1540, "hold"),
            ("ORD-000101", 1540, "consume"),
            ("ORD-000101", 1540, "release"),
            ("ORD-000202", 770, "hold"),
        ],
        770,
        0,
    ),
]


async def plant_lines(db: Any) -> None:
    for retailer, company, code, entries, _, _ in LINES:
        line_id = await db.seed_line(retailer, company, limit=LIMIT, code=code)
        for order, amount, kind in entries:
            await db.plant_entry(line_id, order, amount, kind)


async def test_bc6_every_listed_line_reconciles_to_its_credit_limit(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await plant_lines(db)

    reply = await rpc("billing.credit.list", {})

    listed = decode.list(reply)  # asserts the reply's own `page.total` first
    assert listed.page.total == 4
    assert (listed.page.page, listed.page.page_size) == (1, 25)
    by_code = {item.credit_code: item for item in listed.items}
    assert sorted(by_code) == ["CR-000411", "CR-000422", "CR-000433", "CR-000444"]
    for retailer, company, code, _, active, open_exposure in LINES:
        item = by_code[code]
        assert (item.retailer_code, item.company_code, item.currency) == (retailer, company, "EUR")
        assert item.credit_limit == LIMIT
        assert (item.active_holds, item.open_exposure) == (active, open_exposure), code
        assert item.available_credit == LIMIT - active - open_exposure, (
            f"BC6: {code} does not reconcile: available credit {item.available_credit}"
        )
        assert item.active_holds + item.open_exposure == item.credit_limit - item.available_credit


async def test_the_list_filters_and_pages_at_sql_level(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await plant_lines(db)

    filtered = decode.list(await rpc("billing.credit.list", {"retailerCode": "RETAIL-C3"}))
    assert filtered.page.total == 1
    assert [i.credit_code for i in filtered.items] == ["CR-000433"]

    by_company = decode.list(await rpc("billing.credit.list", {"companyCode": "SUPPLY-CO"}))
    assert by_company.page.total == 4
    none = decode.list(await rpc("billing.credit.list", {"companyCode": "SUPPLY-XX"}))
    assert none.page.total == 0
    assert none.items == []

    second = decode.list(await rpc("billing.credit.list", {"page": 2, "pageSize": 3}))
    assert (second.page.page, second.page.page_size, second.page.total) == (2, 3, 4)
    assert [i.credit_code for i in second.items] == ["CR-000444"], "ordered by retailer, company"
    first = decode.list(await rpc("billing.credit.list", {"page": 1, "pageSize": 3}))
    assert [i.credit_code for i in first.items] == ["CR-000411", "CR-000422", "CR-000433"]


async def test_the_list_needs_no_header_and_writes_nothing(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await plant_lines(db)
    rows, facts = await db.count("credit_items"), await db.count("outbox")

    listed = decode.list(await rpc("billing.credit.list", {}, headers=None))

    assert listed.page.total == 4
    assert await db.count("credit_items") == rows
    assert await db.count("outbox") == facts


async def test_bi37_a_page_past_int64_answers_an_empty_page_with_the_true_total(
    billing_host: Any, db: Any, rpc: Any, decode: Any
) -> None:
    await plant_lines(db)
    past_int64 = (1 << 63) // 25 + 2  # offset (page - 1) x 25 is above 2**63 - 1

    far = decode.list(await rpc("billing.credit.list", {"page": past_int64, "pageSize": 25}))

    assert far.page.total == 4, "the page is empty but the total is the true one"
    assert far.items == []
    # the control: page 1 returns the four lines
    first = decode.list(await rpc("billing.credit.list", {"page": 1, "pageSize": 25}))
    assert first.page.total == 4
    assert len(first.items) == 4
