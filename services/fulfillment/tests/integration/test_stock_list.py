"""`fulfillment.stock.list` through the real host (H11, FS15): derived `availableUnits`, the order
of `(companyCode, productCode)`, paging with `total` across pages, the filters, `belowThreshold`,
and that it holds no lock and writes nothing."""

import asyncio
from typing import Any


async def seed(db: Any) -> None:
    # Company order and product order DISAGREE: sorted by product alone, BBB-CO/PRD-A1 would be
    # first; sorted by (company, product) it is last.
    await db.seed_stock("AAA-CO", [("PRD-Z9", 10, 8, 3), ("PRD-M5", 10, 0, 3)])  # Z9: available 2
    await db.seed_stock("BBB-CO", [("PRD-A1", 5, 2, 3)])  # available 3, threshold 3: NOT below


def keys(reply: dict[str, Any]) -> list[tuple[str, str]]:
    return [(i["companyCode"], i["productCode"]) for i in reply["items"]]


async def test_fs15_lists_stock_views_with_derived_available_units_pages_filters_and_below_threshold_without_locking_or_mutating(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await seed(db)
    before = [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY id")]

    everything = await rpc("fulfillment.stock.list", {})
    assert keys(everything) == [("AAA-CO", "PRD-M5"), ("AAA-CO", "PRD-Z9"), ("BBB-CO", "PRD-A1")]
    assert everything["page"] == {"page": 1, "pageSize": 25, "total": 3}
    z9 = everything["items"][1]
    assert z9 == {
        "companyCode": "AAA-CO",
        "productCode": "PRD-Z9",
        "units": 10,
        "reservedUnits": 8,
        "availableUnits": 2,
        "lowStockThreshold": 3,
    }

    # paging: `total` counts across pages
    first = await rpc("fulfillment.stock.list", {"page": 1, "pageSize": 2})
    second = await rpc("fulfillment.stock.list", {"page": 2, "pageSize": 2})
    assert keys(first) == [("AAA-CO", "PRD-M5"), ("AAA-CO", "PRD-Z9")]
    assert keys(second) == [("BBB-CO", "PRD-A1")]
    assert first["page"] == {"page": 1, "pageSize": 2, "total": 3}
    assert second["page"] == {"page": 2, "pageSize": 2, "total": 3}

    # filters
    assert keys(await rpc("fulfillment.stock.list", {"companyCode": "BBB-CO"})) == [
        ("BBB-CO", "PRD-A1")
    ]
    only = await rpc("fulfillment.stock.list", {"productCode": "PRD-Z9"})
    assert keys(only) == [("AAA-CO", "PRD-Z9")]
    assert only["page"]["total"] == 1

    # belowThreshold: strictly available < threshold (A1: 3 < 3 is false)
    below = await rpc("fulfillment.stock.list", {"belowThreshold": True})
    assert keys(below) == [("AAA-CO", "PRD-Z9")]
    assert below["page"]["total"] == 1
    everything_again = await rpc("fulfillment.stock.list", {"belowThreshold": False})
    assert len(everything_again["items"]) == 3, "false is no filter"

    # nothing mutated, nothing emitted
    assert [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY id")] == before
    assert await db.outbox() == []


async def test_a_list_is_answered_while_a_test_transaction_holds_a_listed_row_for_update(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await seed(db)
    hold = await db.hold([("AAA-CO", "PRD-Z9")])
    try:
        reply = await asyncio.wait_for(rpc("fulfillment.stock.list", {}), timeout=10)
        assert len(reply["items"]) == 3
    finally:
        await hold.rollback()


async def test_bi37_a_page_past_int64_answers_an_empty_page_with_the_true_total(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await seed(db)
    past_int64 = (1 << 63) // 25 + 2  # offset (page - 1) x 25 is above 2**63 - 1

    far = await rpc("fulfillment.stock.list", {"page": past_int64, "pageSize": 25})

    assert "page" in far, f"BI37: expected an empty page, got {far}"  # not an RpcError
    assert far["page"]["total"] == 3, "the page is empty but the total is the true one"
    assert far["items"] == []
    # the control: page 1 returns the three rows
    first = await rpc("fulfillment.stock.list", {"page": 1, "pageSize": 25})
    assert first["page"]["total"] == 3
    assert len(first["items"]) == 3
