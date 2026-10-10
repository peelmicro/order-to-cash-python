"""`billing.payment.register` through the real lifespan over real NATS and PostgreSQL (feature 22;
R47, R48, R49, BI8, #8 id 57, #8's N3).

Every invoice is `issued` by the REAL host (`make_world`: `billing.credit.hold` then
`billing.invoice.issue`), never planted. The plausible wrong values and why this fixture differs
from each:

* the invoice carries a NON-ZERO discount: gross (`amount`) 8465 = 3 x 1999 + 2 x 1234, discount
  350, net (`totalAmount`) 8115. The payment equals the NET; a payment of the gross is the R49
  amount mismatch; one that subtracts the discount twice is 7765.
* the credit line's limit is 250 000 and ANOTHER order holds 20 021, so the available credit is
  221 864 before the payment and 229 979 after: neither is the limit, the gross, the net or the
  120 000 of an unrelated line.
* the order's own `hold` and `consume` entries exist before the payment, so every count is compared
  to its PRE-ATTEMPT baseline, never to a bare zero.
* the correlation id (the order id), the request id, the invoice id and the credit line id are four
  different UUIDs, so a fact caused by or keyed to the wrong one is seen.

Every reply decode asserts its discriminating field first (`Decode.payment_register`: `outcome`;
`Decode.error`: `code`). Loop scope: function. The host and the caller are created and closed in the
test's loop.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

VALUE_DATE = "2026-10-09T13:45:10.123Z"
REFERENCE = "BANK-REF-7731"


def pay_headers(world: Any) -> dict[str, str]:
    return {"x-correlation-id": world.correlation, "x-request-id": str(uuid.uuid4())}


def pay_body(
    world: Any,
    *,
    reference: str = REFERENCE,
    amount: int | None = None,
    currency: str = "EUR",
    by: str = "id",
    value_date: str = VALUE_DATE,
    source: str = "robot",
) -> dict[str, Any]:
    identity = (
        {"invoiceId": str(world.invoice_id)}
        if by == "id"
        else {"invoiceReference": world.invoice_reference}
    )
    return {
        **identity,
        "paymentReference": reference,
        "amount": {"amount": world.total if amount is None else amount, "currency": currency},
        "valueDate": value_date,
        "source": source,
    }


async def state_of(db: Any, world: Any) -> dict[str, Any]:
    """Everything a payment could change, read from the database: the table counts, the invoice
    row, the order's ledger and the credit line's ledger as a whole."""
    return {
        "payments": await db.count("payments"),
        "outbox": await db.count("outbox"),
        "credit_items": await db.count("credit_items"),
        "invoices": await db.count("invoices"),
        "invoice": dict(await db.invoice_row(world.invoice_id)),
        "ledger": [dict(r) for r in await db.ledger_of(world.order_reference)],
    }


async def available_credit(rpc: Any, decode: Any, world: Any) -> int:
    reply = await rpc(
        "billing.credit.list",
        {"retailerCode": world.retailer_code, "companyCode": world.company_code},
    )
    listed = decode.list(reply)
    assert listed.page.total == 1
    return int(listed.items[0].available_credit)


# ------------------------------------------------------------------------------------ R47


async def test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()
    assert (world.amount, world.discount, world.total) == (8465, 350, 8115)
    before = await state_of(db, world)
    assert before["invoice"]["status"] == "issued"
    assert before["invoice"]["paid_at"] is None
    available_before = await available_credit(rpc, decode, world)
    assert available_before == world.available_before == 221_864
    assert available_before not in (world.limit, world.amount, world.total, 120_000)
    # the invoice row, hold and consume of the order exist before: the baselines are not zero
    assert before["payments"] == 0
    assert before["credit_items"] == 3  # the other order's hold, this order's hold and consume
    outbox_before = await db.count("outbox")
    headers = pay_headers(world)
    request = headers["x-request-id"]

    reply = await rpc("billing.payment.register", pay_body(world), headers=headers)

    paid = decode.payment_register(reply)  # asserts `outcome` is present first
    assert paid.outcome.value == "accepted"
    assert paid.payment_reference == REFERENCE
    assert (paid.invoice_reference, paid.order_reference) == (
        world.invoice_reference,
        world.order_reference,
    )
    assert paid.invoice_status.value == "paid"
    assert paid.paid_at is not None
    # the invoice row: paid, paid_at the reply's instant, updated_at moved off created_at
    row = await db.invoice_row(world.invoice_id)
    assert row["status"] == "paid"
    assert row["paid_at"] == paid.paid_at
    assert row["updated_at"] > row["created_at"], "R47: updated_at was not moved by the update"
    assert row["created_at"] == before["invoice"]["created_at"]
    for column in ("amount", "discount", "total_amount", "invoice_reference", "invoice_date"):
        assert row[column] == before["invoice"][column], f"R47: {column} changed"
    # exactly one payments row, equal to the REQUEST field by field (#8's N2: valueDate)
    payments = await db.payments_of(world.invoice_id)
    assert len(payments) == 1, f"R47: {len(payments)} payments rows for the paid invoice, not one"
    [payment] = payments
    assert await db.count("payments") == before["payments"] + 1
    assert payment["payment_reference"] == REFERENCE
    assert payment["amount"] == world.total
    assert payment["currency_code"] == "EUR"
    assert payment["value_date"] == datetime(2026, 10, 9, 13, 45, 10, 123000, tzinfo=UTC), (
        f"R47: payments.value_date is {payment['value_date']}, not the request's valueDate"
    )
    assert payment["source"] == "robot"
    # the outbox: exactly two new rows, payment.received.v1 then credit.released.v1, in seq order
    facts = (await db.outbox())[outbox_before:]
    assert [f["event_type"] for f in facts] == ["payment.received.v1", "credit.released.v1"], (
        f"R47: expected payment.received.v1 then credit.released.v1 in seq order, got "
        f"{[f['event_type'] for f in facts]}"
    )
    received, released = facts
    assert received["seq"] < released["seq"]
    assert str(received["correlation_id"]) == str(released["correlation_id"]) == world.correlation
    assert received["aggregate_id"] == world.invoice_id
    assert released["aggregate_id"] == world.line_id
    assert len({world.correlation, request, str(world.invoice_id), str(world.line_id)}) == 4
    # #8 id 57: the release is caused by the payment FACT, the payment by the request
    assert str(received["causation_id"]) == request
    assert released["causation_id"] == received["event_id"], (
        "#8 id 57: credit.released.v1's causationId is not payment.received.v1's eventId"
    )
    assert received["occurred_at"] == released["occurred_at"] == paid.paid_at
    assert received["payload"] == {
        "orderReference": world.order_reference,
        "invoiceReference": world.invoice_reference,
        "paymentReference": REFERENCE,
        "currency": "EUR",
        "amount": world.total,
        "valueDate": VALUE_DATE,
        "source": "robot",
    }
    assert released["payload"] == {
        "orderReference": world.order_reference,
        "retailerCode": world.retailer_code,
        "companyCode": world.company_code,
        "creditCode": "CR-000321",
        "currency": "EUR",
        "releasedAmount": world.total,
        "availableCreditAfter": world.available_after,
        "reason": "invoice_paid",
    }
    # the ledger: one new `release` of the hold, and the available credit is back where the order
    # found it, which is neither the limit nor the pre-payment figure
    ledger = [dict(r) for r in await db.ledger_of(world.order_reference)]
    assert [r["type"] for r in ledger] == ["hold", "consume", "release"]
    assert ledger[2]["amount"] == world.total
    assert ledger[:2] == before["ledger"], "R47: the order's earlier entries changed"
    after = await available_credit(rpc, decode, world)
    assert after == world.available_after == 229_979
    assert after not in (world.limit, available_before, world.total, world.amount)
    assert await db.count("credit_items") == before["credit_items"] + 1


async def test_r47_the_invoice_can_be_named_by_its_reference_alone(
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()

    reply = await rpc(
        "billing.payment.register",
        pay_body(world, by="reference", source="operator"),
        headers=pay_headers(world),
    )

    assert decode.payment_register(reply).outcome.value == "accepted"
    assert (await db.invoice_row(world.invoice_id))["status"] == "paid"
    [payment] = await db.payments_of(world.invoice_id)
    assert payment["source"] == "operator"


# ------------------------------------------------------------------------------------ R48


async def test_r48_a_repeated_reference_answers_the_original_outcome_and_writes_nothing(
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()
    first = decode.payment_register(
        await rpc("billing.payment.register", pay_body(world), headers=pay_headers(world))
    )
    assert first.outcome.value == "accepted"
    baseline = await state_of(db, world)
    assert baseline["payments"] == 1  # the control: the first call did write

    for by in ("id", "reference"):
        reply = await rpc(
            "billing.payment.register", pay_body(world, by=by), headers=pay_headers(world)
        )

        again = decode.payment_register(reply)
        assert again.outcome.value == "duplicate", f"R48: a repeat by {by} answered {reply}"
        assert again.payment_reference == REFERENCE
        assert (again.invoice_reference, again.order_reference) == (
            world.invoice_reference,
            world.order_reference,
        )
        assert again.invoice_status.value == "paid"
        assert again.paid_at == first.paid_at, (
            "R48: the duplicate did not carry the original paidAt"
        )
        assert await state_of(db, world) == baseline, f"R48: a repeat by {by} changed the state"


async def test_r48_a_reference_reused_for_another_invoice_is_refused_and_writes_nothing(
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()
    # the SAME net (8115) from another gross and discount: only the invoice differs, so the
    # refusal cannot be produced by the amounts differing
    other = await make_world(second=True, same_total=True)
    assert other.total == world.total
    assert (other.amount, other.discount) != (world.amount, world.discount)
    paid = decode.payment_register(
        await rpc("billing.payment.register", pay_body(world), headers=pay_headers(world))
    )
    assert paid.outcome.value == "accepted"
    baseline = await state_of(db, other)
    paid_baseline = await state_of(db, world)

    reply = await rpc(
        "billing.payment.register",
        pay_body(other, reference=REFERENCE),
        headers=pay_headers(other),
    )

    error = decode.error(reply)
    assert error.code.value == "PRECONDITION_FAILED"
    assert error.details == {"code": "payment.reference_reused", "paymentReference": REFERENCE}
    assert await state_of(db, other) == baseline, (
        "R48: a reused reference changed the other invoice"
    )
    assert (await db.invoice_row(other.invoice_id))["status"] == "issued"
    assert await state_of(db, world) == paid_baseline


async def test_r48_a_reference_reused_for_another_amount_is_refused_not_answered_duplicate(
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()
    await rpc("billing.payment.register", pay_body(world), headers=pay_headers(world))
    baseline = await state_of(db, world)

    reply = await rpc(
        "billing.payment.register",
        pay_body(world, amount=world.amount),
        headers=pay_headers(world),
    )

    error = decode.error(reply)
    assert error.code.value == "PRECONDITION_FAILED"
    assert error.details is not None
    assert error.details["code"] == "payment.reference_reused"
    assert await state_of(db, world) == baseline


# ------------------------------------------------------------------------------------ R49


async def test_r49_a_mismatched_amount_is_rejected_with_nothing_changed(
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()
    baseline = await state_of(db, world)
    assert baseline["credit_items"] == 3  # the control rows exist
    assert baseline["payments"] == 0

    # the GROSS, the net minus one and the net plus one: three amounts that are not the total
    for wrong in (world.amount, world.total - 1, world.total + 1):
        reply = await rpc(
            "billing.payment.register",
            pay_body(world, amount=wrong, reference=f"BANK-WRONG-{wrong}"),
            headers=pay_headers(world),
        )

        error = decode.error(reply)
        assert error.code.value == "PAYMENT_MISMATCH", f"R49: amount {wrong} answered {reply}"
        assert error.details == {"code": "invoice.payment_amount_mismatch"}
        assert await state_of(db, world) == baseline, f"R49: amount {wrong} changed the state"


async def test_r49_a_mismatched_currency_is_rejected_with_nothing_changed(
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()
    baseline = await state_of(db, world)

    reply = await rpc(
        "billing.payment.register",
        pay_body(world, currency="USD"),
        headers=pay_headers(world),
    )

    error = decode.error(reply)
    assert error.code.value == "PAYMENT_MISMATCH"
    assert error.details == {"code": "invoice.payment_currency_mismatch"}
    assert await state_of(db, world) == baseline


async def test_r49_a_second_reference_against_a_paid_invoice_is_rejected_with_nothing_changed(
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()
    first = decode.payment_register(
        await rpc("billing.payment.register", pay_body(world), headers=pay_headers(world))
    )
    assert first.outcome.value == "accepted"
    baseline = await state_of(db, world)
    assert baseline["payments"] == 1  # the control: the first payment is there

    reply = await rpc(
        "billing.payment.register",
        pay_body(world, reference="BANK-REF-SECOND"),
        headers=pay_headers(world),
    )

    error = decode.error(reply)
    assert error.code.value == "INVOICE_NOT_PAYABLE"
    assert error.details == {"code": "invoice.already_paid"}
    assert await state_of(db, world) == baseline
    assert [p["payment_reference"] for p in await db.payments_of(world.invoice_id)] == [REFERENCE]


# ------------------------------------------------------ identity, edge, and the inconsistent ledger


async def test_an_unknown_invoice_is_not_found_and_writes_nothing(
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()
    baseline = await state_of(db, world)
    unknown_id = str(uuid.uuid4())

    for body in (
        {**pay_body(world), "invoiceId": unknown_id},
        {**pay_body(world, by="reference"), "invoiceReference": "INV-999999"},
        {**pay_body(world), "invoiceReference": "INV-999999"},  # id and reference disagree
    ):
        error = decode.error(
            await rpc("billing.payment.register", body, headers=pay_headers(world))
        )
        assert error.code.value == "NOT_FOUND", f"{body}"
    assert await state_of(db, world) == baseline


async def test_an_invalid_request_or_missing_headers_are_validation_failed_and_write_nothing(
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()
    baseline = await state_of(db, world)
    no_identity = {k: v for k, v in pay_body(world).items() if k != "invoiceId"}

    assert (
        decode.error(
            await rpc("billing.payment.register", no_identity, headers=pay_headers(world))
        ).code.value
        == "VALIDATION_FAILED"
    )
    assert (
        decode.error(await rpc("billing.payment.register", pay_body(world), headers={})).code.value
        == "VALIDATION_FAILED"
    )
    assert (
        decode.error(
            await rpc(
                "billing.payment.register",
                json.dumps({**pay_body(world), "source": "bank"}).encode(),
                headers=pay_headers(world),
            )
        ).code.value
        == "VALIDATION_FAILED"
    )
    assert await state_of(db, world) == baseline


async def test_n3_a_payment_for_an_order_whose_exposure_is_not_outstanding_is_refused_and_writes_nothing(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    """The order's hold was released through `billing.credit.release` BEFORE the remittance: the
    release has nothing outstanding, so accepting the payment would emit payment.received.v1 alone
    and strand the order at `paid` (#8's N3, #7 the same). The remittance is refused and the
    transaction rolls back, including the invoice update."""
    world = await make_world()
    released = decode.release(
        await rpc(
            "billing.credit.release",
            {
                "orderReference": world.order_reference,
                "retailerCode": world.retailer_code,
                "companyCode": world.company_code,
            },
            headers={"x-correlation-id": world.correlation, "x-request-id": str(uuid.uuid4())},
        )
    )
    assert released.released is True  # the control: the exposure WAS outstanding until now
    baseline = await state_of(db, world)

    reply = await rpc("billing.payment.register", pay_body(world), headers=pay_headers(world))

    error = decode.error(reply)
    assert error.code.value == "PRECONDITION_FAILED"
    assert error.details == {"code": "credit.not_outstanding"}
    assert await state_of(db, world) == baseline, "N3: the payment was recorded without a release"
    assert (await db.invoice_row(world.invoice_id))["status"] == "issued"
