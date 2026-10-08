"""`fulfillment.stock.replenish` through the real host (H10): R61, FS14 (all-or-nothing), FS20."""

import uuid
from typing import Any

COMPANY = "ACME-CO"
HEADERS = {"x-correlation-id": str(uuid.UUID(int=0xC0)), "x-request-id": str(uuid.UUID(int=0xCA))}


def replenish_body(*lines: tuple[str, int], company: str = COMPANY) -> dict[str, Any]:
    return {
        "companyCode": company,
        "lines": [{"productCode": code, "units": units} for code, units in lines],
    }


async def test_r61_replenish_raises_units_by_the_sums_leaves_reserved_units_and_reservations_and_writes_no_fact(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 0, 3), ("PRD-B2", 20, 2, 4)])
    # a reservation exists, and its fact is the control row for the outbox read below
    await rpc(
        "fulfillment.stock.reserve",
        {
            "orderReference": "ORD-000042",
            "retailerCode": "RET-9",
            "companyCode": COMPANY,
            "lines": [{"productCode": "PRD-A1", "units": 4}],
        },
        headers=HEADERS,
    )
    reservations_before = [dict(r) for r in await db.reservations("ORD-000042")]
    outbox_before = len(await db.outbox())

    reply = await rpc(
        "fulfillment.stock.replenish",
        replenish_body(("PRD-A1", 7), ("PRD-B2", 5), ("PRD-A1", 3)),
    )

    assert reply == {
        "items": [
            {
                "companyCode": COMPANY,
                "productCode": "PRD-A1",
                "units": 20,
                "reservedUnits": 4,
                "availableUnits": 16,
                "lowStockThreshold": 3,
            },
            {
                "companyCode": COMPANY,
                "productCode": "PRD-B2",
                "units": 25,
                "reservedUnits": 2,
                "availableUnits": 23,
                "lowStockThreshold": 4,
            },
        ]
    }
    a, b = await db.stock(COMPANY, "PRD-A1"), await db.stock(COMPANY, "PRD-B2")
    assert (a["units"], a["reserved_units"]) == (20, 4), "units up by the SUM, reserved untouched"
    assert (b["units"], b["reserved_units"]) == (25, 2)
    assert [dict(r) for r in await db.reservations("ORD-000042")] == reservations_before
    outbox_after = await db.outbox()
    assert outbox_before == 1, "control: the reserve's fact is visible to the outbox read"
    assert len(outbox_after) == outbox_before, "a top-up writes no fact (R61)"


async def test_fs14_replies_not_found_and_replenishes_no_line_when_any_line_names_an_unknown_product(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 0, 3), ("PRD-B2", 20, 0, 3)])

    # the KNOWN lines come first: a handler that applies as it goes would already have added units
    reply = await rpc(
        "fulfillment.stock.replenish",
        replenish_body(("PRD-A1", 7), ("PRD-B2", 5), ("PRD-Z9", 2)),
    )

    assert reply["code"] == "NOT_FOUND"
    assert reply["details"] == {"companyCode": COMPANY, "productCode": "PRD-Z9"}
    assert (await db.stock(COMPANY, "PRD-A1"))["units"] == 10
    assert (await db.stock(COMPANY, "PRD-B2"))["units"] == 20
    assert await db.outbox() == []

    # control: the same request without the unknown line applies both
    ok = await rpc("fulfillment.stock.replenish", replenish_body(("PRD-A1", 7), ("PRD-B2", 5)))
    assert [i["units"] for i in ok["items"]] == [17, 25]


async def test_fs20_refuses_a_replenishment_that_would_overflow_the_unit_column_with_a_domain_error_and_changes_nothing(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 2_147_483_000, 0, 3), ("PRD-B2", 20, 0, 3)])

    reply = await rpc(
        "fulfillment.stock.replenish", replenish_body(("PRD-B2", 5), ("PRD-A1", 1000))
    )

    assert reply["code"] == "DOMAIN_ERROR"
    assert reply["details"] == {"code": "quantity.out_of_range"}
    assert (await db.stock(COMPANY, "PRD-A1"))["units"] == 2_147_483_000, "the row is unchanged"
    assert (await db.stock(COMPANY, "PRD-B2"))["units"] == 20, "and so is the other line's"

    # control: the boundary itself (2**31 - 1) is accepted
    ok = await rpc("fulfillment.stock.replenish", replenish_body(("PRD-A1", 647)))
    assert ok["items"][0]["units"] == 2_147_483_647
