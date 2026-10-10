"""The remittance-intake transactional unit over fakes of the ports (feature 22; R47 - R49, BI8,
#8 id 57, #8's N3).

One ordered call log is shared by every fake of the transaction, so the lock order is asserted as
ONE sequence (the credits row, the invoice re-read, the payment re-read, the update, the credit
save). The fast-path reads fake has its own log: the fast path is outside the transaction.

The fixtures are chosen so no value satisfies an assertion by accident (the plausible wrong values
and what separates them):

* the invoice carries a NON-ZERO discount: gross 8465 (3 x 1999 + 2 x 1234), discount 350, net 8115.
  A payment of the gross (8465) is a mismatch; the payment equals the NET.
* the credit line's limit is 250 000 and ANOTHER order holds 20 021, so the committed exposure
  before is 28 136, the available credit before is 221 864, and after the release 229 979: not the
  limit, not the pre-payment value, not the gross, not the net.
* the request id (`0xD0`), the correlation id (`0xC0`), the invoice id (`0x5001`) and the ids the
  port supplies (`0xB1` ...) are pairwise different, so a fact caused by the wrong one is seen.

Loop scope: function (pytest-asyncio default); the only awaited things are in-memory fakes.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from otc_billing.application import payment_register
from otc_billing.application.errors import (
    CreditLineNotFoundError,
    CreditNotOutstandingError,
    InvoiceNotFoundError,
    PaymentReferenceReusedError,
)
from otc_billing.application.messages import (
    CreditPage,
    InvoicePage,
    PaymentOutcome,
    RegisterPaymentCommand,
)
from otc_billing.application.ports.credit_store import CreditTransaction
from otc_billing.application.scope import BillingScope
from otc_billing.domain.buyer_credit import BuyerCredit
from otc_billing.domain.credit_entry_type import CreditEntryType as T
from otc_billing.domain.events import CreditReleased
from otc_billing.domain.invoice import Invoice
from otc_billing.domain.invoice_errors import (
    InvoiceAlreadyPaidError,
    InvoicePaymentAmountMismatchError,
    InvoicePaymentCurrencyMismatchError,
)
from otc_billing.domain.invoice_events import PaymentReceived, PaymentSource
from otc_billing.domain.invoice_snapshot import (
    InvoiceLineSnapshot,
    InvoiceSnapshot,
    PaymentSnapshot,
)
from otc_billing.domain.invoice_state import InvoiceStatus, Issued, Paid
from otc_billing.domain.reasons import CreditReleaseReason
from otc_billing.domain.snapshot import BuyerCreditSnapshot, CreditLedgerEntrySnapshot
from otc_shared_kernel import InvoiceReference, Money, Quantity, UniqueId

NOW = datetime(2026, 10, 10, 10, 15, 30, 123000, tzinfo=UTC)
VALUE_DATE = datetime(2026, 10, 9, 0, 0, 0, tzinfo=UTC)
ORDER = "ORD-000101"
RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
GROSS, DISCOUNT, NET = 8465, 350, 8115
LIMIT, OTHER_HOLD = 250_000, 20_021
REFERENCE = "BANK-REF-7731"


def uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(int=n))


INVOICE_ID = uid(0x5001)
CORRELATION = uid(0xC0)
REQUEST = uid(0xD0)


def credit_line(*, with_hold: bool = True) -> BuyerCredit:
    entries = (
        (
            CreditLedgerEntrySnapshot(
                entry_id=uid(0x100),
                order_reference=ORDER,
                amount=Money(NET, "EUR"),
                type=T.HOLD,
                entry_date=NOW - timedelta(days=3),
            ),
        )
        if with_hold
        else ()
    )
    return BuyerCredit.rehydrate(
        BuyerCreditSnapshot(
            id=uid(0x1D),
            code=CODE,
            retailer_code=RETAILER,
            company_code=COMPANY,
            currency="EUR",
            credit_limit=LIMIT,
            committed_exposure=OTHER_HOLD + (NET if with_hold else 0),
            entries=entries,
        )
    )


def stored_invoice(*, paid: bool = False, currency: str = "EUR") -> InvoiceSnapshot:
    return InvoiceSnapshot(
        id=INVOICE_ID,
        invoice_reference=InvoiceReference.from_sequence(42),
        invoice_date=NOW - timedelta(days=2),
        order_reference=ORDER,
        retailer_code=RETAILER,
        company_code=COMPANY,
        currency=currency,
        lines=(
            InvoiceLineSnapshot(
                id=uid(0x5002),
                product_code="PRD-AA",
                units=Quantity(2),
                unit_price=Money(1234, currency),
            ),
            InvoiceLineSnapshot(
                id=uid(0x5003),
                product_code="PRD-ZZ",
                units=Quantity(3),
                unit_price=Money(1999, currency),
            ),
        ),
        amount=Money(GROSS, currency),
        discount=Money(DISCOUNT, currency),
        total_amount=Money(NET, currency),
        state=Paid(NOW - timedelta(days=1)) if paid else Issued(),
    )


def stored_payment(
    *, invoice_id: UniqueId = INVOICE_ID, amount: int = NET, currency: str = "EUR"
) -> PaymentSnapshot:
    return PaymentSnapshot(
        id=uid(0x7001),
        payment_reference=REFERENCE,
        invoice_id=invoice_id,
        amount=Money(amount, currency),
        value_date=VALUE_DATE,
        source=PaymentSource.ROBOT,
    )


class Log:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def count(self, name: str) -> int:
        return self.calls.count(name)


class FakeCredits:
    def __init__(self, log: Log, credit: BuyerCredit | None) -> None:
        self._log = log
        self.credit = credit
        self.saved: list[BuyerCredit] = []
        self.lock_args: list[tuple[str, str, str]] = []

    async def lock_for_order(
        self, retailer_code: str, company_code: str, order_reference: str
    ) -> BuyerCredit | None:
        self._log.calls.append("lock_for_order")
        self.lock_args.append((retailer_code, company_code, order_reference))
        return self.credit

    async def save(self, credit: BuyerCredit) -> None:
        self._log.calls.append("credits.save")
        self.saved.append(credit)


class FakeInvoices:
    def __init__(
        self,
        log: Log,
        *,
        by_id: InvoiceSnapshot | None,
        payment: PaymentSnapshot | None,
    ) -> None:
        self._log = log
        self.by_id = by_id
        self.payment = payment
        self.find_args: list[UniqueId] = []
        self.reference_args: list[str] = []
        self.marked: list[tuple[Invoice, PaymentSnapshot, tuple[object, ...]]] = []

    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
        raise AssertionError("the payment path read an invoice by order reference")

    async def save(self, invoice: Invoice) -> None:
        raise AssertionError("the payment path inserted an invoice")

    async def find_by_id(self, invoice_id: UniqueId) -> InvoiceSnapshot | None:
        self._log.calls.append("invoices.find_by_id")
        self.find_args.append(invoice_id)
        return self.by_id

    async def find_payment_by_reference(self, payment_reference: str) -> PaymentSnapshot | None:
        self._log.calls.append("invoices.find_payment_by_reference")
        self.reference_args.append(payment_reference)
        return self.payment

    async def mark_paid(self, invoice: Invoice, payment: PaymentSnapshot) -> None:
        self._log.calls.append("invoices.mark_paid")
        self.marked.append((invoice, payment, invoice.domain_events))


class Unused:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"the payment path touched {name}")


class FakeTransactions:
    def __init__(
        self,
        log: Log,
        credit: BuyerCredit | None,
        *,
        tx_invoice: InvoiceSnapshot | None,
        tx_payment: PaymentSnapshot | None,
    ) -> None:
        self.credits = FakeCredits(log, credit)
        self.invoices = FakeInvoices(log, by_id=tx_invoice, payment=tx_payment)
        self.invoice_numbers = Unused()
        self.runs = 0
        self.after_work: Callable[[], Awaitable[None]] | None = None

    async def run[R](self, work: Callable[[CreditTransaction], Awaitable[R]]) -> R:
        self.runs += 1
        result = await work(self)  # type: ignore[arg-type]
        if self.after_work is not None:
            await self.after_work()  # the commit: may block, or fail (a rollback)
        return result


class FakeInvoiceReads:
    def __init__(
        self,
        *,
        by_id: dict[UniqueId, InvoiceSnapshot],
        by_reference: dict[str, InvoiceSnapshot],
        payment: PaymentSnapshot | None,
    ) -> None:
        self.by_id = by_id
        self.by_reference = by_reference
        self.payment = payment
        self.calls: list[str] = []

    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
        raise AssertionError("the payment path read an invoice by order reference")

    async def find_by_id(self, invoice_id: UniqueId) -> InvoiceSnapshot | None:
        self.calls.append(f"find_by_id:{invoice_id.value.int:#x}")
        return self.by_id.get(invoice_id)

    async def find_by_invoice_reference(self, invoice_reference: str) -> InvoiceSnapshot | None:
        self.calls.append(f"find_by_invoice_reference:{invoice_reference}")
        return self.by_reference.get(invoice_reference)

    async def find_payment_by_reference(self, payment_reference: str) -> PaymentSnapshot | None:
        self.calls.append(f"find_payment_by_reference:{payment_reference}")
        return self.payment

    async def list(self, **kwargs: object) -> InvoicePage:
        raise AssertionError("the payment path read the invoice list")


class NoReads:
    async def list(
        self, *, page: int, page_size: int, retailer_code: str | None, company_code: str | None
    ) -> CreditPage:
        raise AssertionError("the payment path read the credit list")


class DriftingClock:
    """A different instant on EVERY call: a unit that reads the clock twice cannot pass."""

    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return NOW + timedelta(seconds=self.calls)


class FakeIds:
    def __init__(self, supplied: Sequence[UniqueId]) -> None:
        self._queue = list(supplied)
        self.minted = 0

    def new(self) -> UniqueId:
        self.minted += 1
        assert self._queue, "the unit asked for more identifiers than the test supplied"
        return self._queue.pop(0)


class NoDecision:
    def decide(self, request: object) -> object:
        raise AssertionError("the payment path consulted the credit-decision port")


class Rig:
    def __init__(
        self,
        *,
        credit: BuyerCredit | str | None = "default",
        reads_payment: PaymentSnapshot | None = None,
        reads_invoices: Sequence[InvoiceSnapshot] | None = None,
        tx_invoice: InvoiceSnapshot | str | None = "default",
        tx_payment: PaymentSnapshot | None = None,
        ids: Sequence[UniqueId] | None = None,
    ) -> None:
        self.log = Log()
        invoices = [stored_invoice()] if reads_invoices is None else list(reads_invoices)
        self.transactions = FakeTransactions(
            self.log,
            credit_line() if credit == "default" else credit,  # type: ignore[arg-type]
            tx_invoice=stored_invoice() if tx_invoice == "default" else tx_invoice,  # type: ignore[arg-type]
            tx_payment=tx_payment,
        )
        self.reads = FakeInvoiceReads(
            by_id={i.id: i for i in invoices},
            by_reference={i.invoice_reference.value: i for i in invoices},
            payment=reads_payment,
        )
        self.clock = DriftingClock()
        self.ids = FakeIds(ids if ids is not None else [uid(0xB0 + n) for n in range(1, 9)])
        self.scope = BillingScope(
            transactions=self.transactions,
            reads=NoReads(),
            invoice_reads=self.reads,
            clock=self.clock,
            ids=self.ids,
            credit_decision=NoDecision(),  # type: ignore[arg-type]
        )


def command(
    *,
    amount: int = NET,
    currency: str = "EUR",
    invoice_id: UniqueId | None = INVOICE_ID,
    invoice_reference: str | None = None,
    reference: str = REFERENCE,
) -> RegisterPaymentCommand:
    return RegisterPaymentCommand(
        invoice_id=invoice_id,
        invoice_reference=invoice_reference,
        payment_reference=reference,
        amount=Money(amount, currency),
        value_date=VALUE_DATE,
        source=PaymentSource.ROBOT,
        correlation_id=CORRELATION,
        request_id=REQUEST,
    )


# ------------------------------------------------------------------------------------- R47


async def test_r47_bi8_resolves_unlocked_then_locks_credits_then_re_reads_then_updates() -> None:
    rig = Rig()

    result = await payment_register.register(command(), rig.scope)

    assert result.outcome is PaymentOutcome.ACCEPTED
    assert rig.reads.calls == [
        f"find_payment_by_reference:{REFERENCE}",
        f"find_by_id:{INVOICE_ID.value.int:#x}",
    ], "the fast path then the identity resolution, both outside the transaction"
    assert rig.log.calls == [
        "lock_for_order",
        "invoices.find_by_id",
        "invoices.find_payment_by_reference",
        "invoices.mark_paid",
        "credits.save",
    ], "BI8 / R47: the calls are not lock the credits row, re-read, dedup, update, save credit"
    # every call site is handed the values the RESOLVED invoice and the command carry
    assert rig.transactions.credits.lock_args == [(RETAILER, COMPANY, ORDER)]
    assert rig.transactions.invoices.find_args == [INVOICE_ID]
    assert rig.transactions.invoices.reference_args == [REFERENCE]


async def test_r47_the_reply_is_accepted_with_the_paid_invoice_and_the_one_clock_read() -> None:
    rig = Rig()

    result = await payment_register.register(command(), rig.scope)

    first = NOW + timedelta(seconds=1)
    assert rig.clock.calls == 1, f"R47: the clock was read {rig.clock.calls} times"
    assert (result.payment_reference, result.invoice_reference) == (REFERENCE, "INV-000042")
    assert (result.order_reference, result.invoice_status) == (ORDER, InvoiceStatus.PAID)
    assert result.paid_at == first
    [(invoice, payment, events)] = rig.transactions.invoices.marked
    assert invoice.status is InvoiceStatus.PAID
    assert invoice.paid_at == first
    [fact] = events
    assert isinstance(fact, PaymentReceived)
    assert fact.occurred_at == first
    [credit] = rig.transactions.credits.saved
    [entry] = credit.appended_entries
    assert entry.entry_date == first, "the release entry's date is not the one clock read"
    [released] = credit.domain_events
    assert isinstance(released, CreditReleased)
    assert released.occurred_at == first
    # the payment row carries the command's own values, field by field (#8's N2: valueDate)
    assert payment.payment_reference == REFERENCE
    assert payment.invoice_id == INVOICE_ID
    assert payment.amount == Money(NET, "EUR")
    assert payment.value_date == VALUE_DATE
    assert payment.source is PaymentSource.ROBOT


async def test_r47_payment_received_then_credit_released_with_the_net_amounts() -> None:
    rig = Rig()

    await payment_register.register(command(), rig.scope)

    [(_, _, events)] = rig.transactions.invoices.marked
    [fact] = events
    assert isinstance(fact, PaymentReceived)
    assert (fact.amount, fact.currency) == (NET, "EUR")
    assert fact.amount not in (GROSS, LIMIT), "the payment is the NET, not the gross"
    assert (fact.payment_reference, fact.value_date, fact.source) == (
        REFERENCE,
        VALUE_DATE,
        PaymentSource.ROBOT,
    )
    assert (fact.order_reference, fact.invoice_reference.value) == (ORDER, "INV-000042")
    assert fact.correlation_id == CORRELATION
    assert fact.causation_id == REQUEST
    assert fact.aggregate_id == INVOICE_ID
    [credit] = rig.transactions.credits.saved
    [released] = credit.domain_events
    assert isinstance(released, CreditReleased)
    assert released.reason is CreditReleaseReason.INVOICE_PAID
    assert released.released_amount == NET
    assert released.available_credit_after == LIMIT - OTHER_HOLD == 229_979
    assert released.available_credit_after not in (LIMIT, 221_864, GROSS, NET)
    assert released.correlation_id == CORRELATION
    assert released.aggregate_id == uid(0x1D)


async def test_id57_the_release_is_caused_by_the_payment_fact_not_by_the_request() -> None:
    rig = Rig()

    await payment_register.register(command(), rig.scope)

    [(_, _, events)] = rig.transactions.invoices.marked
    [fact] = events
    [credit] = rig.transactions.credits.saved
    [released] = credit.domain_events
    assert isinstance(fact, PaymentReceived)
    assert isinstance(released, CreditReleased)
    assert released.causation_id == fact.event_id, (
        "#8 id 57: credit.released.v1's causationId is not payment.received.v1's eventId"
    )
    assert released.causation_id != REQUEST
    assert fact.causation_id == REQUEST
    assert fact.event_id != released.event_id


async def test_bi34_the_ids_come_from_the_scope_port_in_the_order_the_units_mint_them() -> None:
    rig = Rig(ids=[uid(0xB1), uid(0xB2), uid(0xB3), uid(0xB4)])

    await payment_register.register(command(), rig.scope)

    [(_, payment, events)] = rig.transactions.invoices.marked
    assert events[0].event_id == uid(0xB1)  # type: ignore[attr-defined]  # mark_paid mints first
    [credit] = rig.transactions.credits.saved
    [entry] = credit.appended_entries
    assert entry.entry_id == uid(0xB2)
    assert credit.domain_events[0].event_id == uid(0xB3)  # type: ignore[attr-defined]
    assert payment.id == uid(0xB4), "the payment row's id is not from the scope's id port"
    assert rig.ids.minted == 4


async def test_n3_a_release_with_nothing_outstanding_refuses_the_payment_and_saves_nothing() -> (
    None
):
    rig = Rig(credit=credit_line(with_hold=False))

    with pytest.raises(CreditNotOutstandingError) as caught:
        await payment_register.register(command(), rig.scope)

    assert caught.value.order_reference == ORDER
    assert rig.log.count("invoices.mark_paid") == 0, (
        "N3: the payment was recorded without a release"
    )
    assert rig.log.count("credits.save") == 0
    assert rig.transactions.invoices.marked == []


async def test_the_result_is_returned_only_after_run_returns_with_both_writes_done() -> None:
    rig = Rig()
    committing = asyncio.Event()
    release = asyncio.Event()
    seen_at_commit: list[str] = []

    async def commit() -> None:
        seen_at_commit.extend(rig.log.calls)
        committing.set()
        await release.wait()

    rig.transactions.after_work = commit
    task = asyncio.create_task(payment_register.register(command(), rig.scope))
    await committing.wait()

    assert not task.done(), "the result was returned before the commit finished"
    assert seen_at_commit[-2:] == ["invoices.mark_paid", "credits.save"]
    release.set()
    assert (await task).outcome is PaymentOutcome.ACCEPTED


async def test_a_rollback_after_work_yields_no_result() -> None:
    rig = Rig()

    class CommitFailed(Exception):
        pass

    async def fail() -> None:
        raise CommitFailed

    rig.transactions.after_work = fail

    with pytest.raises(CommitFailed):
        await payment_register.register(command(), rig.scope)


# --------------------------------------------------------------------------- identity


async def test_r47_the_invoice_is_resolved_by_reference_when_no_id_is_given() -> None:
    rig = Rig()

    result = await payment_register.register(
        command(invoice_id=None, invoice_reference="INV-000042"), rig.scope
    )

    assert result.outcome is PaymentOutcome.ACCEPTED
    assert rig.reads.calls[1] == "find_by_invoice_reference:INV-000042"


@pytest.mark.parametrize(
    ("kwargs", "label"),
    [
        ({"invoice_id": uid(0x9999)}, "an unknown id"),
        ({"invoice_id": None, "invoice_reference": "INV-000999"}, "an unknown reference"),
        ({"invoice_reference": "INV-000999"}, "an id and a reference naming different invoices"),
    ],
)
async def test_an_unknown_invoice_is_not_found_and_opens_no_transaction(
    kwargs: dict[str, object], label: str
) -> None:
    rig = Rig()

    with pytest.raises(InvoiceNotFoundError):
        await payment_register.register(command(**kwargs), rig.scope)  # type: ignore[arg-type]

    assert rig.transactions.runs == 0, f"{label}: a transaction was opened"
    assert rig.clock.calls == 0


async def test_a_missing_credit_line_writes_nothing() -> None:
    rig = Rig(credit=None)

    try:
        await payment_register.register(command(), rig.scope)
    except CreditLineNotFoundError:
        pass
    except Exception as error:
        pytest.fail(f"a missing credit line was answered {type(error).__name__}: {error}")
    else:
        pytest.fail("a missing credit line was not refused")

    assert rig.log.calls == ["lock_for_order"]


async def test_bi8_the_decision_uses_the_re_read_after_the_lock_not_the_pre_lock_snapshot() -> None:
    """The unlocked read said `issued`; by the time the credits row was granted a competitor had
    paid the invoice. The unit must act on the re-read."""
    rig = Rig(tx_invoice=stored_invoice(paid=True))

    with pytest.raises(InvoiceAlreadyPaidError):
        await payment_register.register(command(), rig.scope)

    assert rig.log.calls == [
        "lock_for_order",
        "invoices.find_by_id",
        "invoices.find_payment_by_reference",
    ]
    assert rig.transactions.invoices.marked == []


async def test_a_vanished_invoice_after_the_lock_is_not_found() -> None:
    rig = Rig(tx_invoice=None)

    with pytest.raises(InvoiceNotFoundError):
        await payment_register.register(command(), rig.scope)

    assert rig.log.count("invoices.mark_paid") == 0


# ------------------------------------------------------------------------------------- R48


async def test_r48_a_stored_reference_answers_duplicate_on_the_fast_path_with_no_transaction() -> (
    None
):
    paid = stored_invoice(paid=True)
    rig = Rig(reads_payment=stored_payment(), reads_invoices=[paid])

    result = await payment_register.register(command(), rig.scope)

    assert rig.transactions.runs == 0, "R48: a fast-path hit opened a transaction"
    assert rig.log.calls == [], "R48: a fast-path hit touched the transaction's repositories"
    assert rig.clock.calls == 0
    assert rig.ids.minted == 0
    assert result.outcome is PaymentOutcome.DUPLICATE
    assert (result.payment_reference, result.invoice_reference) == (REFERENCE, "INV-000042")
    assert (result.order_reference, result.invoice_status) == (ORDER, InvoiceStatus.PAID)
    assert result.paid_at == NOW - timedelta(days=1), "the reply carries the STORED paidAt"


@pytest.mark.parametrize(
    ("changes", "label"),
    [
        ({"invoice_id": uid(0x8888)}, "another invoice id"),
        ({"invoice_id": None, "invoice_reference": "INV-000777"}, "another invoice reference"),
        ({"amount": NET + 1}, "another amount"),
        ({"currency": "USD"}, "another currency"),
    ],
)
async def test_r48_a_stored_reference_used_to_mean_something_else_is_reused_not_a_duplicate(
    changes: dict[str, object], label: str
) -> None:
    rig = Rig(reads_payment=stored_payment(), reads_invoices=[stored_invoice(paid=True)])

    with pytest.raises(PaymentReferenceReusedError) as caught:
        await payment_register.register(command(**changes), rig.scope)  # type: ignore[arg-type]

    assert caught.value.payment_reference == REFERENCE, label
    assert rig.transactions.runs == 0


async def test_r48_the_stored_payment_of_another_invoice_is_reused() -> None:
    """The reference is recorded against ANOTHER invoice (`0x5555`); the request names `0x5001`."""
    other_id = uid(0x5555)
    other = replace(stored_invoice(paid=True), id=other_id)
    rig = Rig(reads_payment=stored_payment(invoice_id=other_id), reads_invoices=[other])

    with pytest.raises(PaymentReferenceReusedError):
        await payment_register.register(command(), rig.scope)


async def test_r48_a_reference_stored_by_a_competitor_under_the_lock_answers_duplicate() -> None:
    """Not on the fast path (the competitor had not committed), but visible to the re-read after
    the credits lock was granted."""
    rig = Rig(tx_invoice=stored_invoice(paid=True), tx_payment=stored_payment())

    result = await payment_register.register(command(), rig.scope)

    assert result.outcome is PaymentOutcome.DUPLICATE
    assert result.invoice_status is InvoiceStatus.PAID
    assert rig.log.calls == [
        "lock_for_order",
        "invoices.find_by_id",
        "invoices.find_payment_by_reference",
    ]
    assert rig.ids.minted == 0, "R48: a duplicate minted an identifier"


async def test_r48_a_reference_stored_for_another_invoice_under_the_lock_is_reused() -> None:
    """A competitor on the SAME credit line stored the reference against ANOTHER invoice (`0x5555`)
    between the fast path and the lock; this request names `0x5001`."""
    rig = Rig(tx_payment=stored_payment(invoice_id=uid(0x5555)))

    with pytest.raises(PaymentReferenceReusedError):
        await payment_register.register(command(), rig.scope)

    assert rig.transactions.invoices.marked == []
    assert rig.transactions.credits.saved == []


async def test_r48_a_competitors_payment_under_the_lock_for_another_amount_is_reused() -> None:
    rig = Rig(tx_invoice=stored_invoice(paid=True), tx_payment=stored_payment(amount=NET + 5))

    with pytest.raises(PaymentReferenceReusedError):
        await payment_register.register(command(), rig.scope)


# ------------------------------------------------------------------------------------- R49


async def test_r49_a_mismatched_amount_changes_nothing() -> None:
    rig = Rig()

    with pytest.raises(InvoicePaymentAmountMismatchError) as caught:
        await payment_register.register(command(amount=GROSS), rig.scope)

    assert (caught.value.expected, caught.value.received) == (NET, GROSS)
    assert rig.transactions.invoices.marked == []
    assert rig.transactions.credits.saved == []
    assert rig.log.count("invoices.mark_paid") + rig.log.count("credits.save") == 0


async def test_r49_a_mismatched_currency_changes_nothing() -> None:
    rig = Rig()

    with pytest.raises(InvoicePaymentCurrencyMismatchError) as caught:
        await payment_register.register(command(currency="USD"), rig.scope)

    assert (caught.value.expected, caught.value.received) == ("EUR", "USD")
    assert rig.transactions.invoices.marked == []
    assert rig.transactions.credits.saved == []


async def test_r49_a_second_reference_against_a_paid_invoice_changes_nothing() -> None:
    rig = Rig(reads_invoices=[stored_invoice()], tx_invoice=stored_invoice(paid=True))

    with pytest.raises(InvoiceAlreadyPaidError) as caught:
        await payment_register.register(command(reference="BANK-REF-OTHER"), rig.scope)

    assert caught.value.invoice_reference == "INV-000042"
    assert rig.transactions.invoices.marked == []
    assert rig.transactions.credits.saved == []
    assert rig.transactions.invoices.reference_args == ["BANK-REF-OTHER"]
