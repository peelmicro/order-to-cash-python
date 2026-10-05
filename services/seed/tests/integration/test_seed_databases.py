"""The seed against the real migrated databases of orders, fulfillment and billing.

R-map (feature_list.json id 12): acceptance 2 (every row of every table equals what #7 wrote),
acceptance 3 (five completed orders and one cancelled order, with their outbox facts), acceptance 4
(idempotent: running twice is a no-op, proved by full row dumps and `xmin`, not by counts) and the
outbox claims (already published, payloads in `json` columns, byte form of the one serializer).

Expected rows are built HERE from #7's executed dataset (`seed_dataset_from_number7.json`), with the
column semantics of #7's own writers (`apps/seed/src/writers/*.ts`), not from this port's builders.
The population is every row of every table.
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import asyncpg
import pytest

from otc_contracts import from_wire_json, to_wire_json
from otc_seed.application import run_seed
from otc_seed.composition import SeedRuntime
from otc_seed.infrastructure.payloads import payload_model

pytestmark = pytest.mark.integration

EXPECTED_COUNTS = {
    "orders": {
        "currencies": 3,
        "products": 12,
        "retailers": 7,
        "companies": 22,
        "orders": 6,
        "order_items": 11,
        "outbox": 17,
    },
    "fulfillment": {
        "stock": 215,
        "reservations": 11,
        "despatches": 5,
        "despatch_items": 10,
        "outbox": 12,
    },
    "billing": {
        "credits": 154,
        "credit_items": 15,
        "invoices": 5,
        "invoice_items": 10,
        "payments": 5,
        "outbox": 21,
    },
}


def _t(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


async def _rows(dsn: str, table: str) -> list[dict[str, Any]]:
    conn = await asyncpg.connect(dsn)
    try:
        return [dict(r) for r in await conn.fetch(f'SELECT * FROM "{table}" ORDER BY id')]  # noqa: S608
    finally:
        await conn.close()


def _by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(r["id"]): r for r in rows}


async def _check(dsn: str, table: str, expected: list[dict[str, Any]]) -> None:
    """Every column of every row equals the expected one (the row sets are equal, in full)."""
    actual = _by_id(await _rows(dsn, table))
    want = {e["id"]: e for e in expected}
    assert sorted(actual) == sorted(want), f"{table}: the set of ids differs"
    for key, row in want.items():
        got = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in actual[key].items()}
        assert got == row, f"{table} {key}"


def _outbox(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": r["id"],
            "event_id": r["eventId"],
            "event_type": r["eventType"],
            "aggregate_id": r["aggregateId"],
            "correlation_id": r["correlationId"],
            "causation_id": r["causationId"],
            "payload": r["payload"],
            "occurred_at": _t(r["occurredAt"]),
            "published_at": _t(r["publishedAt"]),
            "created_at": _t(r["occurredAt"]),
            "seq": None,  # checked separately: the database assigns it
            "trace_parent": None,
        }
        for r in rows
    ]


async def _check_outbox(dsn: str, expected: list[dict[str, Any]]) -> None:
    rows = await _rows(dsn, "outbox")
    by_seq = sorted(rows, key=lambda r: r["seq"])
    # insertion order = identity order, and the database assigned 1..n
    assert [str(r["id"]) for r in by_seq] == [e["id"] for e in expected]
    assert [r["seq"] for r in by_seq] == list(range(1, len(expected) + 1))
    want = {e["id"]: e for e in expected}
    for row in rows:
        got = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in row.items()}
        got["payload"] = json.loads(got["payload"])
        got["seq"] = None
        assert got == want[got["id"]], f"outbox {got['id']}"


def _saga_rows(d: dict[str, Any]) -> dict[str, Any]:
    """The expected relational rows of #7's dataset, with #7's writers' column semantics."""
    sagas = d["sagas"]
    currency_id = {c["code"]: c["id"] for c in d["currencies"]}
    company_id = {c["code"]: c["id"] for c in d["companies"]}
    retailer_id = {c["code"]: c["id"] for c in d["retailers"]}
    product_id = {p["code"]: p["id"] for p in d["products"]}
    master = _t("2026-01-01T00:00:00.000Z")
    out: dict[str, Any] = {}
    out["currencies"] = [
        {
            "id": c["id"],
            "code": c["code"],
            "iso_number": c["isoNumber"],
            "symbol": c["symbol"],
            "decimal_points": c["decimalPoints"],
            "created_at": master,
            "updated_at": master,
        }
        for c in d["currencies"]
    ]
    out["products"] = [
        {
            "id": p["id"],
            "code": p["code"],
            "ean": p["ean"],
            "name": p["name"],
            "description": p["description"],
            "price": p["price"],
            "currency_id": currency_id[p["currencyCode"]],
            "disabled_at": None,
            "created_at": master,
            "updated_at": master,
        }
        for p in d["products"]
    ]
    for key in ("retailers", "companies"):
        out[key] = [
            {
                "id": p["id"],
                "code": p["code"],
                "name": p["name"],
                "country": p["country"],
                "vat": p["vat"],
                "gln": p["gln"],
                "currency_id": currency_id[p["currencyCode"]],
                "disabled_at": None,
                "created_at": master,
                "updated_at": master,
            }
            for p in d[key]
        ]
    out["orders"] = [
        {
            "id": s["orderId"],
            "order_reference": s["orderReference"],
            "request_id": None,
            "order_date": _t(s["orderDate"]),
            "company_id": company_id[s["companyCode"]],
            "retailer_id": retailer_id[s["retailerCode"]],
            "currency_id": currency_id[s["currency"]],
            "initial_amount": s["initialAmount"],
            "initial_discount": s["initialDiscount"],
            "total_amount": s["totalAmount"],
            "status": s["status"],
            "cancellation_reason": s["cancellationReason"],
            "notes": "demo — compensation path (credit_rejected, .99 rule)"
            if s["status"] == "cancelled"
            else None,
            "created_at": _t(s["orderDate"]),
            "updated_at": _t(s["updatedAt"]),
        }
        for s in sagas
    ]
    out["order_items"] = [
        {
            "id": _item_id(s["sequence"], line["productCode"]),
            "order_id": s["orderId"],
            "product_id": product_id[line["productCode"]],
            "description": line["description"],
            "price": line["unitPrice"],
            "quantity": line["quantity"],
            "discount": line["lineDiscount"],
            "created_at": _t(s["orderDate"]),
            "updated_at": _t(s["orderDate"]),
        }
        for s in sagas
        for line in s["lines"]
    ]
    out["orders_outbox"] = _outbox([r for s in sagas for r in s["ordersOutbox"]])
    out["stock"] = [
        {
            "id": s["id"],
            "company_code": s["companyCode"],
            "product_code": s["productCode"],
            "units": s["units"],
            "reserved_units": s["reservedUnits"],
            "low_stock_threshold": s["lowStockThreshold"],
            "created_at": master,
            "updated_at": master,
        }
        for s in d["stock"]
    ]
    stock_id = {(s["companyCode"], s["productCode"]): s["id"] for s in d["stock"]}
    out["reservations"] = [
        {
            "id": r["id"],
            "stock_id": stock_id[(r["companyCode"], r["productCode"])],
            "company_code": r["companyCode"],
            "retailer_code": r["retailerCode"],
            "product_code": r["productCode"],
            "order_reference": s["orderReference"],
            "units": r["units"],
            "status": r["status"],
            "created_at": _t(r["createdAt"]),
            "updated_at": _t(r["updatedAt"]),
        }
        for s in sagas
        for r in s["reservations"]
    ]
    out["despatches"] = [
        {
            "id": s["despatch"]["id"],
            "despatch_reference": s["despatch"]["despatchReference"],
            "despatch_date": _t(s["despatch"]["despatchDate"]),
            "company_code": s["despatch"]["companyCode"],
            "retailer_code": s["despatch"]["retailerCode"],
            "order_reference": s["orderReference"],
            "created_at": _t(s["despatch"]["despatchDate"]),
            "updated_at": _t(s["despatch"]["despatchDate"]),
        }
        for s in sagas
        if s["despatch"]
    ]
    out["despatch_items"] = [
        {
            "id": _sub_id(s["sequence"], "despatch-item", i["productCode"]),
            "despatch_id": s["despatch"]["id"],
            "product_code": i["productCode"],
            "units": i["units"],
            "created_at": _t(s["despatch"]["despatchDate"]),
            "updated_at": _t(s["despatch"]["despatchDate"]),
        }
        for s in sagas
        if s["despatch"]
        for i in s["despatch"]["items"]
    ]
    out["fulfillment_outbox"] = _outbox([r for s in sagas for r in s["fulfillmentOutbox"]])
    out["credits"] = [
        {
            "id": c["id"],
            "code": c["code"],
            "retailer_code": c["retailerCode"],
            "company_code": c["companyCode"],
            "credit_limit": c["creditLimit"],
            "currency_code": c["currencyCode"],
            "created_at": master,
            "updated_at": master,
        }
        for c in d["credits"]
    ]
    out["credit_items"] = [
        {
            "id": e["id"],
            "credit_id": e["creditId"],
            "order_reference": e["orderReference"],
            "amount": e["amount"],
            "type": e["type"],
            "credit_date": _t(e["creditDate"]),
            "created_at": _t(e["creditDate"]),
            "updated_at": _t(e["creditDate"]),
        }
        for s in sagas
        for e in s["creditLedgerEntries"]
    ]
    out["invoices"] = [
        {
            "id": s["invoice"]["id"],
            "invoice_reference": s["invoice"]["invoiceReference"],
            "invoice_date": _t(s["invoice"]["invoiceDate"]),
            "company_code": s["companyCode"],
            "retailer_code": s["retailerCode"],
            "order_reference": s["orderReference"],
            "amount": s["invoice"]["amount"],
            "discount": s["invoice"]["discount"],
            "total_amount": s["invoice"]["totalAmount"],
            "currency_code": s["currency"],
            "status": s["invoice"]["status"],
            "paid_at": _t(s["invoice"]["paidAt"]),
            "created_at": _t(s["invoice"]["invoiceDate"]),
            "updated_at": _t(s["invoice"]["paidAt"]),
        }
        for s in sagas
        if s["invoice"]
    ]
    out["invoice_items"] = [
        {
            "id": _sub_id(s["sequence"], "invoice-item", i["productCode"]),
            "invoice_id": s["invoice"]["id"],
            "product_code": i["productCode"],
            "units": i["units"],
            "price": i["price"],
            "created_at": _t(s["invoice"]["invoiceDate"]),
            "updated_at": _t(s["invoice"]["invoiceDate"]),
        }
        for s in sagas
        if s["invoice"]
        for i in s["invoice"]["items"]
    ]
    out["payments"] = [
        {
            "id": s["invoice"]["payment"]["id"],
            "payment_reference": s["invoice"]["payment"]["paymentReference"],
            "invoice_id": s["invoice"]["id"],
            "amount": s["invoice"]["payment"]["amount"],
            "currency_code": s["currency"],
            "value_date": _t(s["invoice"]["payment"]["valueDate"]),
            "source": s["invoice"]["payment"]["source"],
            "created_at": _t(s["invoice"]["payment"]["valueDate"]),
        }
        for s in sagas
        if s["invoice"]
    ]
    out["billing_outbox"] = _outbox([r for s in sagas for r in s["billingOutbox"]])
    return out


def _sub_id(sequence: int, kind: str, product_code: str) -> str:
    """The id #7's writers derive: `deterministicId('order:<seq>:<kind>:<code>')`, typed by hand
    through #7's own vectors file (the namespace strings are #7's, the hash is computed by the
    seed's own function, which `test_deterministic_parity.py` pins to #7's output)."""
    from otc_seed.domain.deterministic import deterministic_id

    return deterministic_id(f"order:{sequence}:{kind}:{product_code}")


def _item_id(sequence: int, product_code: str) -> str:
    return _sub_id(sequence, "item", product_code)


async def test_every_row_of_every_table_equals_the_one_7_wrote(
    runtime: SeedRuntime, stack: Any, number7_dataset: dict[str, Any]
) -> None:
    report = await run_seed(runtime.targets)
    assert dict(report.added["orders"]) == EXPECTED_COUNTS["orders"]
    assert dict(report.added["fulfillment"]) == EXPECTED_COUNTS["fulfillment"]
    assert dict(report.added["billing"]) == EXPECTED_COUNTS["billing"]
    assert dict(report.added["mongo"]) == {"order_timeline": 6}
    assert sum(c["outbox"] for c in EXPECTED_COUNTS.values()) == 50
    expected = _saga_rows(number7_dataset)
    # the ids of every table are compared as SETS (so the counts are exact), and every outbox row's
    # `seq` is checked to be 1..n in saga order (`_check_outbox`)
    for table in EXPECTED_COUNTS["orders"]:
        if table == "outbox":
            await _check_outbox(stack.orders.dsn, expected["orders_outbox"])
        else:
            await _check(stack.orders.dsn, table, expected[table])
    for table in EXPECTED_COUNTS["fulfillment"]:
        if table == "outbox":
            await _check_outbox(stack.fulfillment.dsn, expected["fulfillment_outbox"])
        else:
            await _check(stack.fulfillment.dsn, table, expected[table])
    for table in EXPECTED_COUNTS["billing"]:
        if table == "outbox":
            await _check_outbox(stack.billing.dsn, expected["billing_outbox"])
        else:
            await _check(stack.billing.dsn, table, expected[table])


async def test_running_the_seed_twice_changes_nothing(
    runtime: SeedRuntime,
    stack: Any,
    dump_database: Callable[[str], Awaitable[dict[str, list[tuple[str, str]]]]],
) -> None:
    """Acceptance 4. Compared: every row of every table (whole-row text) AND the transaction id
    that wrote each row version, before and after; the second report adds zero everywhere."""
    await run_seed(runtime.targets)
    first = {
        d.name: await dump_database(d.dsn) for d in (stack.orders, stack.fulfillment, stack.billing)
    }
    assert sum(len(rows) for dump in first.values() for rows in dump.values()) > 400  # not vacuous

    second_report = await run_seed(runtime.targets)

    assert second_report.total_added == 0
    assert all(count == 0 for tables in second_report.added.values() for count in tables.values())
    second = {
        d.name: await dump_database(d.dsn) for d in (stack.orders, stack.fulfillment, stack.billing)
    }
    assert second == first


async def test_a_second_run_does_not_reset_state_a_live_order_changed(
    runtime: SeedRuntime, stack: Any
) -> None:
    """ "Do nothing" rather than "update": units, status and credit limits are live state."""
    await run_seed(runtime.targets)
    conn = await asyncpg.connect(stack.fulfillment.dsn)
    try:
        await conn.execute("UPDATE stock SET units = 1 WHERE company_code = 'IBERFOODS'")
    finally:
        await conn.close()
    await run_seed(runtime.targets)
    conn = await asyncpg.connect(stack.fulfillment.dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM stock WHERE units = 1") == 3
    finally:
        await conn.close()


async def test_every_seeded_outbox_row_is_already_published_so_no_relay_picks_one_up(
    runtime: SeedRuntime, stack: Any
) -> None:
    """#8's `TheRelayFindsNoUnpublishedRecordInAnySeededWriteModel`: the relay claims rows WHERE
    published_at IS NULL, so a seeded row without a stamp would be published to Kafka a second
    time."""
    await run_seed(runtime.targets)
    for database in (stack.orders, stack.fulfillment, stack.billing):
        conn = await asyncpg.connect(database.dsn)
        try:
            assert (
                await conn.fetchval("SELECT count(*) FROM outbox WHERE published_at IS NULL") == 0
            )
            assert (
                await conn.fetchval("SELECT count(*) FROM outbox WHERE published_at <> occurred_at")
                == 0
            )
        finally:
            await conn.close()


async def test_the_stored_payloads_are_the_one_serializers_text_in_json_columns(
    runtime: SeedRuntime, stack: Any
) -> None:
    await run_seed(runtime.targets)
    conn = await asyncpg.connect(stack.orders.dsn)
    try:
        assert (
            await conn.fetchval(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'outbox' AND column_name = 'payload'"
            )
            == "json"
        )  # `json`, not `jsonb`: jsonb would normalise the text on the way in
        rows = await conn.fetch("SELECT event_type, payload::text AS text FROM outbox ORDER BY seq")
    finally:
        await conn.close()
    assert len(rows) == 17
    for row in rows:
        model = from_wire_json(payload_model(row["event_type"]), row["text"])
        assert to_wire_json(model) == row["text"]  # stored bytes == the contract's wire form
    cancelled = next(r["text"] for r in rows if '"notes"' in r["text"])
    assert "—" in cancelled  # non-ASCII written raw
