"""`billing.invoice.issue` through the real lifespan over real NATS and PostgreSQL (tasks F2, F4,
F6, F8; R45, BI2 - BI6, BI9, BI35, BI38).

Every issue request is built from LINES by the conftest's `issue_body`, which REFUSES a fixture
whose `amount`, `discount` and `totalAmount` are not pairwise distinct, non-zero and substring-free
(BI38; #8's D2). The plausible wrong values and why this fixture differs from each:

* gross (`amount`) 8465 = 3 x 1999 + 2 x 1234; discount 350; net (`totalAmount`, and the hold) 8115.
  A total that ignores the discount is 8465 (differs from 8115); one that subtracts it twice is
  7765; a discount transposed with the total is 8115 where 350 is expected; a unit price replaced by
  its line total is 5997 / 2468, not 1999 / 1234.
* the credit line's limit is 250 000 and another order holds 20 021, so the available credit before
  the issue is 221 864: it is not the limit, not the gross, not the net, and not the 120 000 limit
  of the unrelated second line.
* `retailerCode` `RETAIL-77` is neither `SUPPLY-CO` nor contained in it; the order id, the request
  id and the invoice id are three different UUIDs.

Every suppression asserts zero new rows WITH a control row in the same test. Every reply decode
asserts its discriminating field first (`Decode.invoice_issue`: `created`).

Loop scope: function. The host and the caller are created and closed in the test's loop.
"""

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
ORDER = "ORD-000101"
OTHER_ORDER = "ORD-000202"
THIRD_ORDER = "ORD-000303"
LIMIT = 250_000
OTHER_HOLD = 20_021
LINES = [("PRD-ZZ", 3, 1999), ("PRD-AA", 2, 1234)]  # not canonical; gross 8465
DISCOUNT = 350
NET = 8115  # the hold
AVAILABLE_BEFORE = LIMIT - OTHER_HOLD - NET  # 221 864
INSTANT_PATTERN = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def ids() -> tuple[dict[str, str], str, str]:
    correlation, request = str(uuid.uuid4()), str(uuid.uuid4())
    return {"x-correlation-id": correlation, "x-request-id": request}, correlation, request


def hold_body(order: str, amount: int) -> dict[str, Any]:
    return {
        "orderReference": order,
        "retailerCode": RETAILER,
        "companyCode": COMPANY,
        "amount": {"amount": amount, "currency": "EUR"},
    }


async def seed_world(db: Any, rpc: Any, decode: Any, *, hold_for: str | None = ORDER) -> uuid.UUID:
    """The credit line, an unrelated second line, another order's hold, and (by default) the hold
    for the order under test, placed through `billing.credit.hold` with the computed net."""
    line_id = await db.seed_line(RETAILER, COMPANY, limit=LIMIT, code=CODE)
    await db.seed_line("RETAIL-88", "SUPPLY-88", limit=120_000, code="CR-000654")
    await db.plant_entry(line_id, OTHER_ORDER, OTHER_HOLD, "hold")
    if hold_for is not None:
        headers, _, _ = ids()
        reply = await rpc("billing.credit.hold", hold_body(hold_for, NET), headers=headers)
        assert decode.hold(reply).outcome.value == "approved"
    return line_id  # type: ignore[no-any-return]


def fixture(issue_body: Any, order: str = ORDER, **overrides: Any) -> Any:
    return issue_body(
        overrides.pop("lines", LINES),
        overrides.pop("discount", DISCOUNT),
        order_reference=order,
        retailer_code=overrides.pop("retailer_code", RETAILER),
        company_code=overrides.pop("company_code", COMPANY),
        **overrides,
    )


async def available_credit(rpc: Any, decode: Any) -> int:
    reply = await rpc("billing.credit.list", {"retailerCode": RETAILER, "companyCode": COMPANY})
    listed = decode.list(reply)
    assert listed.page.total == 1
    return int(listed.items[0].available_credit)


async def rows_of_everything(db: Any) -> dict[str, int]:
    return {
        table: await db.count(table)
        for table in ("invoices", "invoice_items", "credit_items", "outbox")
    }


# ------------------------------------------------------------------------------------ R45


async def test_r45_issues_one_invoice_through_the_real_host_with_a_non_zero_discount_reaching_row_fact_and_reply(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any, issue_body: Any
) -> None:
    line_id = await seed_world(db, rpc, decode)
    built = fixture(issue_body)
    assert (built.amount, built.discount, built.total) == (8465, 350, 8115)
    before_available = await available_credit(rpc, decode)
    assert before_available == AVAILABLE_BEFORE
    assert before_available not in (LIMIT, built.amount, built.total, 120_000)
    outbox_before = await db.count("outbox")
    headers, correlation, request = ids()

    reply = await rpc("billing.invoice.issue", built.body, headers=headers)

    issued = decode.invoice_issue(reply)  # asserts `created` is present first
    assert issued.created is True
    assert issued.status.value == "issued"
    assert issued.invoice_reference == "INV-000001"
    assert issued.order_reference == ORDER
    assert (issued.currency, issued.total_amount) == ("EUR", 8115)
    # exactly one invoices row, its figures equal to the computed ones
    [row] = await db.invoices_of(ORDER)
    assert issued.invoice_id == row["id"], "the reply's invoiceId is not the stored row's id"
    assert str(row["id"]) not in (correlation, request)
    assert (row["invoice_reference"], row["status"], row["paid_at"]) == (
        "INV-000001",
        "issued",
        None,
    )
    assert (row["retailer_code"], row["company_code"], row["currency_code"]) == (
        RETAILER,
        COMPANY,
        "EUR",
    )
    assert (row["amount"], row["discount"], row["total_amount"]) == (
        built.amount,
        built.discount,
        built.total,
    )
    assert row["updated_at"] == row["created_at"]
    assert issued.invoice_date == row["invoice_date"]
    # the lines mirror the request, field by field (the unit price, not the line total)
    items = await db.invoice_items_of(row["id"])
    assert [(i["product_code"], i["units"], i["price"]) for i in items] == [
        ("PRD-AA", 2, 1234),
        ("PRD-ZZ", 3, 1999),
    ]
    # exactly one consume row of the hold's amount (and the hold itself stays)
    ledger = await db.ledger_of(ORDER)
    consumes = [r for r in ledger if r["type"] == "consume"]
    assert len(consumes) == 1, f"expected exactly one consume row, got {len(consumes)}"
    assert (consumes[0]["amount"], consumes[0]["credit_id"]) == (NET, line_id)
    assert [r["type"] for r in ledger if r["type"] != "consume"] == ["hold"]
    # the whole-table outbox delta is exactly 1 (R40's silence: the consume raises no fact)
    outbox_after = await db.outbox()
    assert len(outbox_after) - outbox_before == 1, (
        f"expected a whole-table outbox delta of exactly 1, got {len(outbox_after) - outbox_before}"
    )
    fact = outbox_after[-1]
    assert fact["event_type"] == "invoice.issued.v1"
    # the envelope: aggregateId = the invoice id, correlationId / causationId = the headers
    assert fact["aggregate_id"] == row["id"]
    assert str(fact["correlation_id"]) == correlation
    assert str(fact["causation_id"]) == request
    assert fact["occurred_at"] == row["invoice_date"]
    # the payload: EVERY field against the supplied values
    payload = dict(fact["payload"])
    invoice_date = payload.pop("invoiceDate")
    assert INSTANT_PATTERN.match(invoice_date), f"invoiceDate is not `.mmmZ`: {invoice_date}"
    assert (
        datetime.strptime(invoice_date, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        == row["invoice_date"]
    )
    assert payload == {
        "orderReference": ORDER,
        "invoiceReference": "INV-000001",
        "retailerCode": RETAILER,
        "companyCode": COMPANY,
        "currency": "EUR",
        "lines": [
            {"productCode": "PRD-ZZ", "units": 3, "unitPrice": 1999},
            {"productCode": "PRD-AA", "units": 2, "unitPrice": 1234},
        ],
        "amount": 8465,
        "discount": 350,
        "totalAmount": 8115,
    }, "a field of the invoice.issued.v1 payload is not the supplied / computed value"
    # R40: the available credit is NUMERICALLY identical before and after
    assert await available_credit(rpc, decode) == before_available, (
        "R40: an issued invoice moved the available credit"
    )


# ------------------------------------------------------------------------------- BI9 (repeat)


async def test_bi9_a_repeat_returns_the_existing_invoice_with_created_false_and_writes_nothing_whether_issued_or_paid(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any, issue_body: Any
) -> None:
    await seed_world(db, rpc, decode)
    built = fixture(issue_body)
    first_headers, _, first_request = ids()
    first = decode.invoice_issue(
        await rpc("billing.invoice.issue", built.body, headers=first_headers)
    )
    assert first.created is True
    after_first = await rows_of_everything(db)
    assert after_first["invoices"] == 1
    assert after_first["outbox"] > 0  # the control: the first issue wrote its fact

    # a repeat with a DIFFERENT x-request-id
    second_headers, _, second_request = ids()
    assert second_request != first_request
    second = decode.invoice_issue(
        await rpc("billing.invoice.issue", built.body, headers=second_headers)
    )

    assert second.created is False
    assert second.invoice_id == first.invoice_id, "BI9: the repeat did not carry the invoiceId"
    assert second.invoice_reference == first.invoice_reference
    assert second.invoice_date == first.invoice_date
    assert second.currency == first.currency
    assert second.total_amount == first.total_amount == 8115
    assert second.status.value == "issued"
    after_second = await rows_of_everything(db)
    assert after_second == after_first, "BI9: a repeat wrote a row"
    assert after_second["invoices"] == 1
    assert len([r for r in await db.ledger_of(ORDER) if r["type"] == "consume"]) == 1
    assert await db.invoice_counter() == 2, "a repeat advanced the counter"

    # the PAID variant: a stored paid invoice answers its current status, created: false
    paid_at = datetime(2026, 10, 11, 17, 45, 59, 987000, tzinfo=UTC)
    paid_id = await db.seed_invoice(
        THIRD_ORDER,
        retailer_code=RETAILER,
        company_code=COMPANY,
        reference="INV-000777",
        lines=[("PRD-AA", 4, 2000)],
        discount=500,
        invoice_date=datetime(2026, 10, 10, 8, 30, 0, 456000, tzinfo=UTC),
        status="paid",
        paid_at=paid_at,
    )
    before_paid = await rows_of_everything(db)
    paid_headers, _, _ = ids()
    paid = decode.invoice_issue(
        await rpc(
            "billing.invoice.issue",
            fixture(issue_body, THIRD_ORDER, lines=[("PRD-QQ", 1, 500)], discount=100).body,
            headers=paid_headers,
        )
    )
    assert paid.created is False
    assert paid.status.value == "paid"
    assert paid.invoice_id == paid_id
    assert paid.invoice_reference == "INV-000777"
    assert paid.total_amount == 7500, "the reply carries the STORED total, not the request's"
    assert await rows_of_everything(db) == before_paid


# ------------------------------------------------------------------------------------ refusals


async def test_bi2_answers_validation_failed_and_writes_nothing_for_an_invalid_header_or_payload(
    billing_host: Any, db: Any, rpc: Any, decode: Any, issue_body: Any
) -> None:
    # NOTE: this proves the OUTCOME through the real host (the reply and the absence of rows). It
    # does NOT prove that the refusal happens BEFORE the dispatcher: the residue of a refusal made
    # inside the transaction would look the same. Placement is proven by the unit cases that count
    # dispatcher calls (`test_invoice_requests.py` for the edge checks, `test_credit_responder.py`
    # for the headers).
    await seed_world(db, rpc, decode)
    good = fixture(issue_body)
    headers, _, _ = ids()
    baseline = await rows_of_everything(db)

    def body(**changes: Any) -> dict[str, Any]:
        return {**good.body, **changes}

    cases: dict[str, tuple[Any, dict[str, str] | None]] = {
        "no headers at all": (good.body, None),
        "no x-correlation-id": (good.body, {"x-request-id": headers["x-request-id"]}),
        "a malformed x-request-id": (
            good.body,
            {"x-correlation-id": headers["x-correlation-id"], "x-request-id": "not-a-uuid"},
        ),
        "a body that is not JSON": (b"{not json", headers),
        "empty lines": (body(lines=[]), headers),
        "a lower-case currency": (body(currency="eur"), headers),
        "a negative unit price": (
            body(lines=[{"productCode": "PRD-ZZ", "units": 1, "unitPrice": -5}]),
            headers,
        ),
        "a discount one minor unit above the sum": (body(discount=8466), headers),
        "an order reference over 20 characters": (body(orderReference="ORD-" + "1" * 18), headers),
        "units above int32": (
            body(lines=[{"productCode": "PRD-ZZ", "units": 2_147_483_648, "unitPrice": 1}]),
            headers,
        ),
    }
    for label, (payload, request_headers) in cases.items():
        reply = await rpc("billing.invoice.issue", payload, headers=request_headers)
        error = decode.error(reply)  # asserts the reply is an RpcError first
        assert error.code.value == "VALIDATION_FAILED", f"{label}: answered {error.code.value}"
        assert await rows_of_everything(db) == baseline, f"{label}: a row was written"
        assert await db.invoice_counter() is None, f"{label}: the counter was touched"

    # the control: the same request, valid, issues exactly one invoice
    control = decode.invoice_issue(await rpc("billing.invoice.issue", good.body, headers=headers))
    assert control.created is True
    assert (await rows_of_everything(db))["invoices"] == 1


async def test_bi3_replies_not_found_naming_the_pair_creating_no_invoice_appending_no_entry_and_emitting_no_fact(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any, issue_body: Any
) -> None:
    await seed_world(db, rpc, decode)
    baseline = await rows_of_everything(db)
    headers, _, _ = ids()

    reply = await rpc(
        "billing.invoice.issue",
        fixture(issue_body, retailer_code="RETAIL-99", company_code="SUPPLY-99").body,
        headers=headers,
    )

    error = decode.error(reply)
    assert error.code.value == "NOT_FOUND"
    assert error.details == {"retailerCode": "RETAIL-99", "companyCode": "SUPPLY-99"}
    assert await rows_of_everything(db) == baseline
    assert await db.invoice_counter() is None
    # the control: the seeded pair issues
    control_headers, _, _ = ids()
    control = decode.invoice_issue(
        await rpc("billing.invoice.issue", fixture(issue_body).body, headers=control_headers)
    )
    assert control.created is True


async def test_bi4_replies_validation_failed_with_the_expected_and_received_currency_writing_nothing(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any, issue_body: Any
) -> None:
    await seed_world(db, rpc, decode)
    baseline = await rows_of_everything(db)
    headers, _, _ = ids()

    reply = await rpc(
        "billing.invoice.issue", fixture(issue_body, currency="USD").body, headers=headers
    )

    error = decode.error(reply)
    assert error.code.value == "VALIDATION_FAILED"
    assert error.details == {"expected": "EUR", "received": "USD"}
    assert await rows_of_everything(db) == baseline
    assert await db.invoice_counter() is None
    control_headers, _, _ = ids()
    control = decode.invoice_issue(
        await rpc("billing.invoice.issue", fixture(issue_body).body, headers=control_headers)
    )
    assert control.created is True


async def test_bi5_replies_precondition_failed_for_no_active_hold_and_leaves_the_orders_ledger_rows_unchanged(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any, issue_body: Any
) -> None:
    await seed_world(db, rpc, decode)
    release_headers, _, _ = ids()
    released = decode.release(
        await rpc(
            "billing.credit.release",
            {"orderReference": ORDER, "retailerCode": RETAILER, "companyCode": COMPANY},
            headers=release_headers,
        )
    )
    assert released.released is True  # the order's hold is gone: nothing is active
    ledger_before = [dict(r) for r in await db.ledger_of(ORDER)]
    assert [r["type"] for r in ledger_before] == ["hold", "release"]
    counter_before = await db.invoice_counter()
    baseline = await rows_of_everything(db)
    headers, _, _ = ids()

    reply = await rpc("billing.invoice.issue", fixture(issue_body).body, headers=headers)

    error = decode.error(reply)
    assert error.code.value == "PRECONDITION_FAILED"
    assert error.details == {"code": "credit.no_active_hold"}
    # the order's two ledger rows, RE-READ, are byte-equal to what they were
    assert [dict(r) for r in await db.ledger_of(ORDER)] == ledger_before
    assert await db.invoices_of(ORDER) == []
    # A residue assertion: it cannot see a rolled-back allocation (review N4a: Q3b-int survives), so
    # it does NOT prove the refusal precedes the allocation. The placement guard is
    # unit/test_invoice_issue_service.py::test_bi5_*.
    assert await db.invoice_counter() == counter_before, "the counter was touched"
    assert await rows_of_everything(db) == baseline
    # the control: an order that holds issues
    await rpc("billing.credit.hold", hold_body(THIRD_ORDER, NET), headers=ids()[0])
    control = decode.invoice_issue(
        await rpc("billing.invoice.issue", fixture(issue_body, THIRD_ORDER).body, headers=ids()[0])
    )
    assert control.created is True


async def test_bi6_emits_no_fact_of_any_type_on_every_refusal_path(
    billing_host: Any, db: Any, rpc: Any, decode: Any, issue_body: Any
) -> None:
    await seed_world(db, rpc, decode)
    outbox_before = await db.count("outbox")
    good = fixture(issue_body)

    refusals = [
        ({**good.body, "lines": []}, ids()[0], "VALIDATION_FAILED"),  # the edge
        (fixture(issue_body, retailer_code="RETAIL-99").body, ids()[0], "NOT_FOUND"),
        (fixture(issue_body, currency="USD").body, ids()[0], "VALIDATION_FAILED"),  # the line
        (fixture(issue_body, THIRD_ORDER).body, ids()[0], "PRECONDITION_FAILED"),  # no hold
    ]
    for payload, headers, code in refusals:
        error = decode.error(await rpc("billing.invoice.issue", payload, headers=headers))
        assert error.code.value == code
    # ONE whole-table count, not scoped by correlation id or event type (#7's N7)
    assert await db.count("outbox") == outbox_before, "a refusal path emitted a fact"

    # the control: a valid issue adds EXACTLY one
    control = decode.invoice_issue(await rpc("billing.invoice.issue", good.body, headers=ids()[0]))
    assert control.created is True
    assert await db.count("outbox") == outbox_before + 1


# ------------------------------------------------------------------------------------ BI35


async def test_bi35_a_zero_hold_is_consumed_and_a_zero_total_invoice_issued(
    billing_host: Any, db: Any, rpc: Any, decode: Any, issue_body: Any
) -> None:
    await seed_world(db, rpc, decode, hold_for=None)
    zero = issue_body(
        [("PRD-ZZ", 3, 1999), ("PRD-AA", 2, 1234)],
        8465,  # the discount equals the gross: a zero total, on purpose
        order_reference=ORDER,
        retailer_code=RETAILER,
        company_code=COMPANY,
        zero_total_on_purpose=True,
    )
    assert (zero.amount, zero.discount, zero.total) == (8465, 8465, 0)
    # a zero-amount hold placed THROUGH the responder (BC38)
    hold = decode.hold(await rpc("billing.credit.hold", hold_body(ORDER, 0), headers=ids()[0]))
    assert hold.outcome.value == "approved"
    assert hold.held_amount == 0
    outbox_before = await db.count("outbox")
    headers, correlation, _ = ids()

    reply = await rpc("billing.invoice.issue", zero.body, headers=headers)

    issued = decode.invoice_issue(reply)
    assert issued.created is True
    assert issued.total_amount == 0
    [row] = await db.invoices_of(ORDER)
    assert (row["amount"], row["discount"], row["total_amount"]) == (8465, 8465, 0)
    consumes = [r for r in await db.ledger_of(ORDER) if r["type"] == "consume"]
    assert len(consumes) == 1, "expected exactly one consume row"
    assert consumes[0]["amount"] == 0
    facts = (await db.outbox())[outbox_before:]
    assert [f["event_type"] for f in facts] == ["invoice.issued.v1"]
    assert str(facts[0]["correlation_id"]) == correlation
    assert facts[0]["payload"]["totalAmount"] == 0
    assert json.dumps(facts[0]["payload"]["lines"])  # the fact carries the lines
