"""`fulfillment.stock.reserve` through the real host: the accepted path, the rejected path (#8 D1:
its outbox row is opened field by field), FS3's stamping, FS5's short-circuit on any status, FS28,
the no-carrier branch and G2's case sensitivity (H3 - H6, H12).

Every emitted row is read back and every field asserted against a TEST-SUPPLIED, pairwise-distinct
value: the order reference, the correlation id (the order id), the request id, the carrier's stock
id, `companyCode` and `retailerCode` all differ, and no product code contains another.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

COMPANY = "ACME-CO"
RETAILER = "RET-9"
ORDER = "ORD-000042"
CORRELATION = str(uuid.UUID(int=0xC0C0))
REQUEST = str(uuid.UUID(int=0xCA05))
HEADERS = {"x-correlation-id": CORRELATION, "x-request-id": REQUEST}


def by_id(reference: dict[str, Any]) -> str:
    return str(reference["reservationId"])


def reserve_body(*lines: tuple[str, int], order: str = ORDER) -> dict[str, Any]:
    return {
        "orderReference": order,
        "retailerCode": RETAILER,
        "companyCode": COMPANY,
        "lines": [{"productCode": code, "units": units} for code, units in lines],
    }


async def stocked(db: Any) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = await db.seed_stock(
        COMPANY, [("PRD-A1", 10, 1, 3), ("PRD-B2", 20, 2, 3), ("PRD-C3", 5, 3, 1)]
    )
    return ids


async def test_r32_the_accepted_path_creates_one_reservation_per_line_raises_the_counters_and_writes_exactly_one_reserved_fact(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    ids = await stocked(db)

    reply = await rpc(
        "fulfillment.stock.reserve",
        reserve_body(("PRD-A1", 3), ("PRD-B2", 5), ("PRD-A1", 2)),
        headers=HEADERS,
    )

    rows = await db.reservations(ORDER)
    by_id = {str(r["id"]): r for r in rows}
    assert len(by_id) == 3
    # the reply lists the references in LINE order (the rows share one timestamp, so the table has
    # no order of its own); each reference is a real row with the same product and units
    refs = reply["reservations"]
    assert [(r["productCode"], r["units"]) for r in refs] == [
        ("PRD-A1", 3),
        ("PRD-B2", 5),
        ("PRD-A1", 2),
    ]
    for ref in refs:
        row = by_id[ref["reservationId"]]
        assert (row["product_code"], row["units"], row["status"]) == (
            ref["productCode"],
            ref["units"],
            "reserved",
        )
    assert {(r["company_code"], r["retailer_code"], r["order_reference"]) for r in rows} == {
        (COMPANY, RETAILER, ORDER)
    }
    assert {r["stock_id"] for r in rows} == {ids["PRD-A1"], ids["PRD-B2"]}
    assert reply == {"outcome": "accepted", "orderReference": ORDER, "reservations": refs}
    assert (await db.stock(COMPANY, "PRD-A1"))["reserved_units"] == 1 + 3 + 2
    assert (await db.stock(COMPANY, "PRD-B2"))["reserved_units"] == 2 + 5
    assert (await db.stock(COMPANY, "PRD-C3"))["reserved_units"] == 3, "C3 untouched"
    assert (await db.stock(COMPANY, "PRD-A1"))["units"] == 10, "reserving does not consume"

    # exactly ONE fact, opened field by field
    [fact] = await db.outbox()
    assert fact["event_type"] == "stock.reserved.v1"
    assert fact["aggregate_id"] == ids["PRD-A1"], "the carrier is the first line's item (FS13)"
    assert fact["payload"] == {
        "orderReference": ORDER,
        "companyCode": COMPANY,
        "retailerCode": RETAILER,
        "reservations": refs,
    }
    assert fact["published_at"] is None, "only the relay stamps it"
    assert fact["occurred_at"].tzinfo is not None


async def test_fs3_stamps_correlation_id_from_the_header_and_causation_id_from_the_request_id_on_the_emitted_fact(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    ids = await stocked(db)

    await rpc("fulfillment.stock.reserve", reserve_body(("PRD-B2", 4)), headers=HEADERS)

    [fact] = await db.outbox()
    assert str(fact["correlation_id"]) == CORRELATION
    assert str(fact["causation_id"]) == REQUEST
    # the three identifiers are pairwise distinct, so a swap could not pass
    assert len({CORRELATION, REQUEST, str(fact["aggregate_id"]), str(fact["event_id"])}) == 4
    assert fact["aggregate_id"] == ids["PRD-B2"]


async def test_h4_the_rejected_path_replies_rejected_creates_nothing_and_writes_exactly_one_rejected_fact(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    ids = await stocked(db)
    before = [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY product_code")]

    reply = await rpc(
        "fulfillment.stock.reserve",
        reserve_body(("PRD-A1", 4), ("PRD-C3", 5), ("PRD-C3", 3)),  # C3: 8 wanted, 2 free
        headers=HEADERS,
    )

    assert reply == {
        "outcome": "rejected",
        "orderReference": ORDER,
        "shortages": [{"productCode": "PRD-C3", "requested": 8, "available": 2}],
    }
    assert await db.reservations(ORDER) == [], "no reservation at all (F3)"
    after = [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY product_code")]
    assert after == before, "counters unchanged"
    [fact] = await db.outbox()
    assert fact["event_type"] == "stock.rejected.v1"
    assert fact["aggregate_id"] == ids["PRD-A1"]
    assert str(fact["correlation_id"]) == CORRELATION
    assert str(fact["causation_id"]) == REQUEST
    assert fact["payload"] == {
        "orderReference": ORDER,
        "companyCode": COMPANY,
        "retailerCode": RETAILER,
        "shortages": [{"productCode": "PRD-C3", "requested": 8, "available": 2}],
        "reason": "insufficient_stock",
    }


async def test_h4_an_unstocked_product_is_rejected_with_reason_unknown_product(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    ids = await stocked(db)

    reply = await rpc(
        "fulfillment.stock.reserve",
        reserve_body(("PRD-A1", 4), ("PRD-Z9", 5)),
        headers=HEADERS,
    )

    assert reply["outcome"] == "rejected"
    assert reply["shortages"] == [{"productCode": "PRD-Z9", "requested": 5, "available": 0}]
    [fact] = await db.outbox()
    assert fact["payload"]["reason"] == "unknown_product"
    assert fact["payload"]["shortages"] == reply["shortages"]
    assert fact["aggregate_id"] == ids["PRD-A1"]
    assert await db.reservations(ORDER) == []


async def test_fs5_answers_already_reserved_with_the_existing_reservations_changing_no_counter_and_emitting_no_second_fact_when_reissued(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await stocked(db)
    first = await rpc(
        "fulfillment.stock.reserve", reserve_body(("PRD-A1", 3), ("PRD-B2", 5)), headers=HEADERS
    )
    counters = [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY product_code")]

    # the lost reply is re-issued with the same bytes and the same headers
    again = await rpc(
        "fulfillment.stock.reserve", reserve_body(("PRD-A1", 3), ("PRD-B2", 5)), headers=HEADERS
    )

    assert again["outcome"] == "already_reserved"
    # the EXISTING rows, same ids (listed in id order: a re-issue has no line order to follow)
    assert sorted(again["reservations"], key=by_id) == sorted(first["reservations"], key=by_id)
    assert [
        dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY product_code")
    ] == counters
    assert len(await db.reservations(ORDER)) == 2
    [only] = await db.outbox()
    assert only["event_type"] == "stock.reserved.v1", "no second fact"


async def test_fs5_answers_already_reserved_for_an_order_whose_only_reservation_is_already_released_reserving_nothing_new(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    ids = await stocked(db)
    now = datetime.now(UTC)
    released = uuid.UUID(int=0x71)
    await db.execute(
        "INSERT INTO reservations (id, stock_id, company_code, retailer_code, product_code,"
        " order_reference, units, status, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, 'PRD-A1', $5, 3, 'released', $6, $6)",
        released,
        ids["PRD-A1"],
        COMPANY,
        RETAILER,
        ORDER,
        now,
    )
    before = [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY product_code")]
    reissue = {
        "x-correlation-id": str(uuid.UUID(int=0xC1)),
        "x-request-id": str(uuid.UUID(int=0xC2)),
    }

    # ample units (10 available, 4 requested): a status-filtering handler WOULD reserve
    reply = await rpc("fulfillment.stock.reserve", reserve_body(("PRD-A1", 4)), headers=reissue)

    assert reply["outcome"] == "already_reserved"
    assert reply["reservations"] == [
        {"reservationId": str(released), "productCode": "PRD-A1", "units": 3}
    ]
    rows = await db.reservations(ORDER)
    assert [(r["id"], r["status"]) for r in rows] == [(released, "released")], "nothing new"
    assert [dict(r) for r in await db.fetch("SELECT * FROM stock ORDER BY product_code")] == before
    assert await db.outbox() == [], "no fact for the re-issue"

    # control row: another order's reserve in the same test DOES write, so the read can see rows
    await rpc(
        "fulfillment.stock.reserve",
        reserve_body(("PRD-B2", 1), order="ORD-000043"),
        headers=HEADERS,
    )
    [control] = await db.outbox()
    assert str(control["correlation_id"]) == CORRELATION
    assert control["payload"]["orderReference"] == "ORD-000043"


async def test_fs5_answers_already_reserved_for_a_reissue_naming_a_different_product(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await stocked(db)
    first = await rpc("fulfillment.stock.reserve", reserve_body(("PRD-A1", 3)), headers=HEADERS)

    # the same order, now naming ANOTHER product: the existing reservation (on PRD-A1, a product
    # outside this request) is still found, because the read is not scoped to the locked rows
    again = await rpc("fulfillment.stock.reserve", reserve_body(("PRD-B2", 4)), headers=HEADERS)

    assert again["outcome"] == "already_reserved"
    assert again["reservations"] == first["reservations"]  # a single reference: no order to lose
    assert (await db.stock(COMPANY, "PRD-B2"))["reserved_units"] == 2, "B2 was not reserved"
    assert len(await db.reservations(ORDER)) == 1
    assert len(await db.outbox()) == 1


async def test_fs28_reserves_for_ord_000000_which_the_kernel_parse_refuses(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await stocked(db)

    reply = await rpc(
        "fulfillment.stock.reserve",
        reserve_body(("PRD-A1", 3), order="ORD-000000"),
        headers=HEADERS,
    )

    assert reply["outcome"] == "accepted", reply
    assert reply["orderReference"] == "ORD-000000"
    [row] = await db.reservations("ORD-000000")
    assert row["units"] == 3
    [fact] = await db.outbox()
    assert fact["payload"]["orderReference"] == "ORD-000000"


async def test_a_reserve_naming_no_stocked_product_answers_not_found_and_writes_nothing(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await stocked(db)

    reply = await rpc(
        "fulfillment.stock.reserve",
        reserve_body(("PRD-Z9", 1), ("PRD-Y8", 2)),
        headers=HEADERS,
    )

    assert reply["code"] == "NOT_FOUND"
    assert reply["details"] == {"orderReference": ORDER}
    assert await db.reservations(ORDER) == []
    assert await db.outbox() == [], "no fact: there is no aggregate to carry one"

    # control row: a reserve in the same test writes, so the empty outbox above means something
    ok = await rpc(
        "fulfillment.stock.reserve",
        reserve_body(("PRD-A1", 1), order="ORD-000043"),
        headers=HEADERS,
    )
    assert ok["outcome"] == "accepted"
    assert len(await db.outbox()) == 1


async def test_a_code_differing_only_in_letter_case_is_a_different_product(
    fulfillment_host: Any, db: Any, rpc: Any
) -> None:
    await stocked(db)

    reply = await rpc("fulfillment.stock.reserve", reserve_body(("prd-a1", 1)), headers=HEADERS)

    # `prd-a1` names no item: with no known line there is no carrier, so it is NOT_FOUND ...
    assert reply["code"] == "NOT_FOUND"
    # ... and next to a known line it is an unknown product, rejected
    mixed = await rpc(
        "fulfillment.stock.reserve",
        reserve_body(("PRD-A1", 1), ("prd-a1", 1), order="ORD-000043"),
        headers=HEADERS,
    )
    assert mixed["outcome"] == "rejected"
    assert mixed["shortages"] == [{"productCode": "prd-a1", "requested": 1, "available": 0}]
    [fact] = await db.outbox()
    assert fact["payload"]["reason"] == "unknown_product"
