"""The constructed races of `billing.payment.register` (feature 22; R48, BI8).

A change of KIND, not of probability: every race here is built from a lock the TEST holds and a
wait on `pg_stat_activity` (`Db.wait_for_lock_waiters`), never from repetition or a sleep.

* **R48 concurrent.** The test's own connection holds the credit line `FOR UPDATE`; two
  registrations of ONE `paymentReference` for ONE invoice are sent; the test waits until TWO lock
  requests are seen ungranted, and only then commits. Correct code serialises the two on the line
  row: the winner pays, and the loser's re-reads (new statements at the pinned `READ COMMITTED`,
  after the line lock was granted) see the winner's payment, so it answers `duplicate`.
* **BI8 lock order.** While one registration waits for the credits row, the test (a) takes the
  INVOICE row with `FOR UPDATE NOWAIT` (it succeeds only if the request does NOT hold the invoice
  row while waiting for the credits row: the line is the first lock), then (b) pays the invoice
  itself and commits, and only then releases the credits row. The request resolved the invoice
  UNLOCKED (`issued`), so only a re-read AFTER the lock sees `paid`: it answers
  `INVOICE_NOT_PAYABLE` (a request that skipped the re-read would try to pay a paid invoice and
  fail the guarded UPDATE as `UNAVAILABLE`).
* **R48 across credit lines.** The line lock does not serialise two invoices of DIFFERENT lines,
  so the `payments.payment_reference` UNIQUE constraint is the arbiter: the test holds an
  uncommitted `payments` row with the reference, the request waits on the unique index, the test
  commits, and the request answers the reused-reference refusal instead of `INTERNAL_ERROR`.

Loop scope: function. The host, the caller and the lock-holding connections are created and closed
in the test's loop.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg

REFERENCE = "BANK-REF-7731"
VALUE_DATE = "2026-10-09T13:45:10.123Z"


def headers(world: Any) -> dict[str, str]:
    return {"x-correlation-id": world.correlation, "x-request-id": str(uuid.uuid4())}


def body(world: Any, reference: str = REFERENCE) -> dict[str, Any]:
    return {
        "invoiceId": str(world.invoice_id),
        "paymentReference": reference,
        "amount": {"amount": world.total, "currency": "EUR"},
        "valueDate": VALUE_DATE,
        "source": "robot",
    }


async def test_r48_two_concurrent_registrations_of_one_reference_yield_one_payment_and_one_fact_pair(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()
    payments_before = await db.count("payments")
    outbox_before = await db.count("outbox")
    items_before = await db.count("credit_items")

    line_lock = await db.hold(world.retailer_code, world.company_code)
    try:
        first = asyncio.create_task(
            rpc("billing.payment.register", body(world), headers=headers(world))
        )
        second = asyncio.create_task(
            rpc("billing.payment.register", body(world), headers=headers(world))
        )
        await db.wait_for_lock_waiters("%", 2)
    finally:
        await line_lock.commit()
    replies = await asyncio.gather(first, second)

    # each reply's own discriminating field first (`outcome`), so a loser answered with an
    # RpcError fails HERE, naming the reply
    decoded = [decode.payment_register(reply) for reply in replies]
    assert sorted(d.outcome.value for d in decoded) == ["accepted", "duplicate"], (
        f"R48: two registrations of one reference answered {[d.outcome.value for d in decoded]}"
    )
    winner = next(d for d in decoded if d.outcome.value == "accepted")
    loser = next(d for d in decoded if d.outcome.value == "duplicate")
    assert loser.paid_at == winner.paid_at
    assert loser.invoice_reference == winner.invoice_reference == world.invoice_reference
    assert await db.count("payments") == payments_before + 1, "R48: more than one payment row"
    facts = (await db.outbox())[outbox_before:]
    assert [f["event_type"] for f in facts] == ["payment.received.v1", "credit.released.v1"], (
        f"R48: expected exactly one fact pair, got {[f['event_type'] for f in facts]}"
    )
    assert await db.count("credit_items") == items_before + 1, "R48: more than one release entry"


async def test_bi8_the_request_waits_for_the_credits_row_without_the_invoice_row_and_re_reads_after_it(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()
    competitor_reference = "BANK-REF-COMPETITOR"
    outbox_before = await db.count("outbox")
    items_before = await db.count("credit_items")

    line_lock = await db.hold(world.retailer_code, world.company_code)
    request = asyncio.create_task(
        rpc("billing.payment.register", body(world), headers=headers(world))
    )
    try:
        await db.wait_for_lock_waiters("%", 1)
        # (a) the request is parked on the credits row. It must NOT hold the invoice row: the
        # credits row is the first lock (BI8). NOWAIT turns "held by the request" into an error.
        probe = await db.connect()
        transaction = probe.transaction()
        await transaction.start()
        try:
            await probe.fetch(
                "SELECT id FROM invoices WHERE id = $1 FOR UPDATE NOWAIT", world.invoice_id
            )
        except asyncpg.exceptions.LockNotAvailableError:
            await transaction.rollback()
            await probe.close()
            raise AssertionError(
                "BI8: the request holds the invoice row while it waits for the credits row "
                "(the lock order is inverted)"
            ) from None
        # (b) a competitor pays the invoice meanwhile, with ANOTHER reference, and commits
        await probe.execute(
            "UPDATE invoices SET status = 'paid', paid_at = now(), updated_at = now()"
            " WHERE id = $1",
            world.invoice_id,
        )
        await probe.execute(
            "INSERT INTO payments (id, payment_reference, invoice_id, amount, currency_code,"
            " value_date, source, created_at) VALUES ($1, $2, $3, $4, 'EUR', $5, 'test', now())",
            uuid.uuid4(),
            competitor_reference,
            world.invoice_id,
            world.total,
            datetime(2026, 10, 9, tzinfo=UTC),
        )
        await transaction.commit()
        await probe.close()
    finally:
        await line_lock.commit()
    reply = await request

    error = decode.error(reply)
    assert error.code.value == "INVOICE_NOT_PAYABLE", (
        f"BI8: the request acted on the invoice it read BEFORE the credits lock; got {reply}"
    )
    assert error.details == {"code": "invoice.already_paid"}
    assert [p["payment_reference"] for p in await db.payments_of(world.invoice_id)] == [
        competitor_reference
    ]
    assert await db.count("outbox") == outbox_before, "BI8: the refused request emitted a fact"
    assert await db.count("credit_items") == items_before, "BI8: the refused request released"


async def test_r48_a_reference_stored_by_a_competitor_on_another_credit_line_is_reused_not_internal_error(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any, make_world: Any
) -> None:
    world = await make_world()
    other = await make_world(second=True)
    outbox_before = await db.count("outbox")
    items_before = await db.count("credit_items")

    competitor = await db.connect()
    transaction = competitor.transaction()
    await transaction.start()
    try:
        await competitor.execute(
            "INSERT INTO payments (id, payment_reference, invoice_id, amount, currency_code,"
            " value_date, source, created_at) VALUES ($1, $2, $3, $4, 'EUR', $5, 'test', now())",
            uuid.uuid4(),
            REFERENCE,
            other.invoice_id,
            other.total,
            datetime(2026, 10, 9, tzinfo=UTC),
        )
        request = asyncio.create_task(
            rpc("billing.payment.register", body(world), headers=headers(world))
        )
        await db.wait_for_lock_waiters("%", 1)
    finally:
        await transaction.commit()
        await competitor.close()
    reply = await request

    error = decode.error(reply)
    assert error.code.value == "PRECONDITION_FAILED", (
        f"R48: the UNIQUE backstop surfaced as {reply}, not the reused-reference refusal"
    )
    assert error.details == {"code": "payment.reference_reused", "paymentReference": REFERENCE}
    assert (await db.invoice_row(world.invoice_id))["status"] == "issued"
    assert await db.payments_of(world.invoice_id) == []
    assert await db.count("outbox") == outbox_before
    assert await db.count("credit_items") == items_before
