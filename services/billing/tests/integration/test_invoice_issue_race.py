"""The constructed race of `billing.invoice.issue` (task I1; BI8, B7).

A change of KIND, not of probability: the test's own connection holds `FOR UPDATE` on the order's
`credits` row AND on the invoice counter row; two issue requests for the SAME order are sent
(distinct `x-request-id`s, one `x-correlation-id`); the test waits until TWO lock requests are seen
ungranted (`pg_stat_activity`), and only then commits. Correct code serialises the two on the line
row: the winner issues, and the loser's `invoices` re-read, a NEW statement at the pinned
`READ COMMITTED` after the line lock was granted, sees the winner's committed invoice, so it answers
`created: false` with the same reference (L10).

**What this race CANNOT see (#7's review `N5`).** Two instances of one transaction taking their
locks in a consistently INVERTED order can never form a cycle with each other, so this race cannot
see an inversion in general (with the counter held it does fail a counter-first inversion, on `the
counter advanced exactly once`, but that is incidental; review N4b, Q3a-race).
The ordering clause of BI8 (the `credits` row, then any `invoices` row,
then the counter row) is guarded ONLY by the ordered call log of
`unit/test_invoice_issue_service.py::
test_bi8_locks_the_credit_line_then_re_reads_the_invoice_then_allocates_the_number` (task C4).

The counter row is held by the test as well so that, when a mutation lets a request skip the line
lock, the request still BLOCKS somewhere (on the counter) and the test reaches its assertion on the
loser's reply instead of dying in the wait.

Loop scope: function. The host, the caller and the lock-holding connection are created and closed
in the test's loop.
"""

import asyncio
import uuid
from typing import Any

RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
ORDER = "ORD-000101"
LINES = [("PRD-ZZ", 3, 1999), ("PRD-AA", 2, 1234)]  # 8465; discount 350; net 8115


def headers(correlation: str) -> dict[str, str]:
    return {"x-correlation-id": correlation, "x-request-id": str(uuid.uuid4())}


async def test_bi8_two_concurrent_issues_for_one_order_yield_one_invoice_one_consume_and_one_fact(
    billing_host: Any, db: Any, rpc: Any, decode: Any, issue_body: Any
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=250_000, code=CODE)
    built = issue_body(
        LINES, 350, order_reference=ORDER, retailer_code=RETAILER, company_code=COMPANY
    )
    held = await rpc(
        "billing.credit.hold",
        {
            "orderReference": ORDER,
            "retailerCode": RETAILER,
            "companyCode": COMPANY,
            "amount": {"amount": built.total, "currency": "EUR"},
        },
        headers=headers(str(uuid.uuid4())),
    )
    assert decode.hold(held).outcome.value == "approved"
    # the counter row exists (so the test can hold it) and nothing has been allocated yet
    await db.execute("INSERT INTO invoice_number_sequences (id, next_value) VALUES (1, 1)")
    outbox_before = await db.count("outbox")
    correlation = str(uuid.uuid4())  # the order id: one for both requests

    line_lock = await db.hold(RETAILER, COMPANY)
    counter_lock = await db.hold_counter()
    try:
        first = asyncio.create_task(
            rpc("billing.invoice.issue", built.body, headers=headers(correlation))
        )
        second = asyncio.create_task(
            rpc("billing.invoice.issue", built.body, headers=headers(correlation))
        )
        await db.wait_for_lock_waiters("%", 2)
    finally:
        await line_lock.commit()
        await counter_lock.commit()
    replies = await asyncio.gather(first, second)

    # each reply's own discriminating field first (`created`), so a loser answered with an
    # RpcError fails HERE, naming the reply (the mutation arms record it)
    decoded = [decode.invoice_issue(reply) for reply in replies]
    assert sorted(d.created for d in decoded) == [False, True], (
        f"BI8: two issues for one order answered created={[d.created for d in decoded]}"
    )
    winner = next(d for d in decoded if d.created)
    loser = next(d for d in decoded if not d.created)
    assert loser.invoice_reference == winner.invoice_reference == "INV-000001"
    assert loser.invoice_id == winner.invoice_id
    assert loser.total_amount == winner.total_amount == 8115
    # exactly one invoice, one consume entry and one fact for the order
    invoices = await db.invoices_of(ORDER)
    assert len(invoices) == 1, f"BI8: {len(invoices)} invoices for one order"
    consumes = [r for r in await db.ledger_of(ORDER) if r["type"] == "consume"]
    assert len(consumes) == 1, f"BI8: {len(consumes)} consume entries for one order"
    facts = (await db.outbox())[outbox_before:]
    assert [f["event_type"] for f in facts] == ["invoice.issued.v1"], (
        f"BI8: expected exactly one invoice.issued.v1, got {[f['event_type'] for f in facts]}"
    )
    assert str(facts[0]["correlation_id"]) == correlation
    assert await db.invoice_counter() == 2, "the counter advanced exactly once"
