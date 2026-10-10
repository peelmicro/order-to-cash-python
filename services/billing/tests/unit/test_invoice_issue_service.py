"""The invoice-issue transactional unit, over fakes of the ports (tasks C2 - C5; BI5, BI8, BI9,
BI13, BI34).

One ordered call log is shared by every fake of the transaction (the credit repository, the invoice
repository, the allocator), so the lock order is asserted as ONE sequence of FIVE calls (#7's `N4`:
a two-element log cannot see the allocator move). The fast-path reads fake has its own log: the fast
path is outside the transaction.

The fixtures are chosen so no value satisfies an assertion by accident: the order id (`0xC0`), the
request id (`0xD0`), the credit line id, the invoice id and the entry ids are pairwise different;
`RETAIL-77` is neither `SUPPLY-CO` nor contained in it; the amounts are 8465 (gross), 350 (discount)
and 8115 (total, and the hold), none containing another; the lines are not in canonical order.

Loop scope: function (pytest-asyncio default); the only awaited things are in-memory fakes.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from otc_billing.application import invoice_issue
from otc_billing.application.errors import CreditLineNotFoundError, InvoiceCurrencyMismatchError
from otc_billing.application.messages import (
    CreditPage,
    InvoiceIssueResult,
    InvoicePage,
    IssueInvoiceCommand,
    IssueLine,
)
from otc_billing.application.ports.credit_store import CreditTransaction
from otc_billing.application.scope import BillingScope
from otc_billing.domain.buyer_credit import BuyerCredit
from otc_billing.domain.credit_entry_type import CreditEntryType as T
from otc_billing.domain.errors import NoActiveHoldError
from otc_billing.domain.invoice import Invoice
from otc_billing.domain.invoice_events import InvoiceIssued
from otc_billing.domain.invoice_snapshot import (
    InvoiceLineSnapshot,
    InvoiceSnapshot,
    PaymentSnapshot,
)
from otc_billing.domain.invoice_state import InvoiceStatus, Issued, Paid
from otc_billing.domain.snapshot import BuyerCreditSnapshot, CreditLedgerEntrySnapshot
from otc_shared_kernel import InvoiceReference, Money, Quantity, UniqueId

NOW = datetime(2026, 10, 9, 10, 15, 30, 123000, tzinfo=UTC)
ORDER = "ORD-000101"
RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
HOLD = 8115


def uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(int=n))


def line(*, with_hold: bool = True, currency: str = "EUR") -> BuyerCredit:
    entries = (
        (
            CreditLedgerEntrySnapshot(
                entry_id=uid(0x100),
                order_reference=ORDER,
                amount=Money(HOLD, currency),
                type=T.HOLD,
                entry_date=NOW,
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
            currency=currency,
            credit_limit=500_000,
            committed_exposure=HOLD if with_hold else 0,
            entries=entries,
        )
    )


def stored_invoice(*, paid: bool = False) -> InvoiceSnapshot:
    """An existing invoice with its own values, none equal to the command's or the fakes'."""
    return InvoiceSnapshot(
        id=uid(0x5001),
        invoice_reference=InvoiceReference.from_sequence(42),
        invoice_date=NOW - timedelta(days=2),
        order_reference=ORDER,
        retailer_code=RETAILER,
        company_code=COMPANY,
        currency="EUR",
        lines=(
            InvoiceLineSnapshot(
                id=uid(0x5002),
                product_code="PRD-AA",
                units=Quantity(1),
                unit_price=Money(900, "EUR"),
            ),
        ),
        amount=Money(900, "EUR"),
        discount=Money(70, "EUR"),
        total_amount=Money(830, "EUR"),
        state=Paid(NOW - timedelta(days=1)) if paid else Issued(),
    )


class Log:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def count(self, name: str) -> int:
        return self.calls.count(name)


class FakeCreditRepository:
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


class FakeInvoiceRepository:
    def __init__(self, log: Log, existing: InvoiceSnapshot | None) -> None:
        self._log = log
        self.existing = existing
        self.saved: list[tuple[Invoice, tuple[object, ...]]] = []
        self.find_args: list[str] = []

    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
        self._log.calls.append("invoices.find_by_order_reference")
        self.find_args.append(order_reference)
        return self.existing

    async def save(self, invoice: Invoice) -> None:
        self._log.calls.append("invoices.save")
        self.saved.append((invoice, invoice.domain_events))

    async def find_by_id(self, invoice_id: UniqueId) -> InvoiceSnapshot | None:
        raise AssertionError("the issue read an invoice by id")

    async def find_payment_by_reference(self, payment_reference: str) -> PaymentSnapshot | None:
        raise AssertionError("the issue read a payment")

    async def mark_paid(self, invoice: Invoice, payment: PaymentSnapshot) -> None:
        raise AssertionError("the issue marked an invoice paid")


class FakeAllocator:
    def __init__(self, log: Log) -> None:
        self._log = log

    async def next_reference(self) -> InvoiceReference:
        self._log.calls.append("next_reference")
        return InvoiceReference.from_sequence(777)


class FakeTransactions:
    def __init__(self, log: Log, credit: BuyerCredit | None, existing: InvoiceSnapshot | None):
        self.credits = FakeCreditRepository(log, credit)
        self.invoices = FakeInvoiceRepository(log, existing)
        self.invoice_numbers = FakeAllocator(log)
        self.runs = 0
        self.after_work: Callable[[], Awaitable[None]] | None = None

    async def run[T2](self, work: Callable[[CreditTransaction], Awaitable[T2]]) -> T2:
        self.runs += 1
        result = await work(self)
        if self.after_work is not None:
            await self.after_work()  # the commit: may block, or fail (a rollback)
        return result


class FakeInvoiceReads:
    def __init__(self, existing: InvoiceSnapshot | None) -> None:
        self.existing = existing
        self.finds: list[str] = []

    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
        self.finds.append(order_reference)
        return self.existing

    async def find_by_id(self, invoice_id: UniqueId) -> InvoiceSnapshot | None:
        raise AssertionError("the issue read an invoice by id")

    async def find_by_invoice_reference(self, invoice_reference: str) -> InvoiceSnapshot | None:
        raise AssertionError("the issue read an invoice by reference")

    async def find_payment_by_reference(self, payment_reference: str) -> PaymentSnapshot | None:
        raise AssertionError("the issue read a payment")

    async def list(self, **kwargs: object) -> InvoicePage:
        raise AssertionError("the issue read the invoice list")


class NoReads:
    async def list(
        self, *, page: int, page_size: int, retailer_code: str | None, company_code: str | None
    ) -> CreditPage:
        raise AssertionError("the issue read the credit list")


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
        raise AssertionError("the issue consulted the credit-decision port")


class Rig:
    def __init__(
        self,
        *,
        credit: BuyerCredit | None = None,
        reads_existing: InvoiceSnapshot | None = None,
        tx_existing: InvoiceSnapshot | None = None,
        ids: Sequence[UniqueId] | None = None,
    ) -> None:
        self.log = Log()
        self.transactions = FakeTransactions(self.log, credit, tx_existing)
        self.reads = FakeInvoiceReads(reads_existing)
        self.clock = DriftingClock()
        self.ids = FakeIds(ids if ids is not None else [uid(0xA0 + n) for n in range(1, 8)])
        self.scope = BillingScope(
            transactions=self.transactions,
            reads=NoReads(),
            invoice_reads=self.reads,
            clock=self.clock,
            ids=self.ids,
            credit_decision=NoDecision(),  # type: ignore[arg-type]
        )

    @property
    def allocator_calls(self) -> int:
        return self.log.count("next_reference")


def command(*, currency: str = "EUR", order: str = ORDER) -> IssueInvoiceCommand:
    return IssueInvoiceCommand(
        order_reference=order,
        retailer_code=RETAILER,
        company_code=COMPANY,
        currency=currency,
        lines=(  # not in canonical order: 3 x 1999 + 2 x 1234 = 8465
            IssueLine(product_code="PRD-ZZ", units=3, unit_price=1999),
            IssueLine(product_code="PRD-AA", units=2, unit_price=1234),
        ),
        discount=350,
        correlation_id=uid(0xC0),
        request_id=uid(0xD0),
    )


# ------------------------------------------------------------------------------------- C2


@pytest.mark.parametrize("paid", [False, True], ids=["issued", "paid"])
async def test_a_hit_on_the_fast_path_returns_created_false_and_opens_no_transaction(
    paid: bool,
) -> None:
    rig = Rig(credit=line(), reads_existing=stored_invoice(paid=paid))

    result = await invoice_issue.issue(command(), rig.scope)

    assert rig.transactions.runs == 0, "BI9: a fast-path hit opened a transaction"
    assert rig.log.calls == [], "BI9: a fast-path hit touched the transaction's repositories"
    assert result.created is False
    stored = stored_invoice(paid=paid)
    assert result.invoice.invoice_id == stored.id
    assert result.invoice.invoice_reference == "INV-000042"
    assert result.invoice.invoice_date == stored.invoice_date
    assert result.invoice.total_amount == 830, "the reply carries the STORED total"
    assert result.invoice.status is (InvoiceStatus.PAID if paid else InvoiceStatus.ISSUED)
    assert rig.ids.minted == 0


async def test_bi5_no_active_hold_raises_before_the_allocator_and_saves_nothing() -> None:
    rig = Rig(credit=line(with_hold=False))

    with pytest.raises(NoActiveHoldError):
        await invoice_issue.issue(command(), rig.scope)

    # the entry is observed, never the residue (#7's N3): neither the allocator nor either save
    assert rig.allocator_calls == 0, "BI5: the counter was touched for an order with no active hold"
    assert rig.log.count("invoices.save") == 0, "BI5: the invoice repository saved"
    assert rig.log.count("credits.save") == 0, "BI5: the credit repository saved"
    assert rig.log.calls == ["lock_for_order", "invoices.find_by_order_reference"]


async def test_an_in_transaction_hit_returns_created_false_and_saves_nothing() -> None:
    rig = Rig(credit=line(), tx_existing=stored_invoice())

    result = await invoice_issue.issue(command(), rig.scope)

    assert result.created is False
    assert result.invoice.invoice_reference == "INV-000042"
    assert rig.transactions.runs == 1
    assert rig.allocator_calls == 0, "BI9: a repeat allocated a number"
    assert rig.log.count("invoices.save") == 0
    assert rig.log.count("credits.save") == 0
    assert rig.log.calls == ["lock_for_order", "invoices.find_by_order_reference"]


async def test_no_credit_line_and_a_foreign_currency_write_nothing_and_skip_the_counter() -> None:
    absent = Rig(credit=None)
    with pytest.raises(CreditLineNotFoundError):
        await invoice_issue.issue(command(), absent.scope)
    assert absent.log.calls == ["lock_for_order"]

    foreign = Rig(credit=line())
    with pytest.raises(InvoiceCurrencyMismatchError) as caught:
        await invoice_issue.issue(command(currency="USD"), foreign.scope)
    assert (caught.value.expected, caught.value.received) == ("EUR", "USD")
    assert foreign.allocator_calls == 0
    assert foreign.log.count("invoices.save") + foreign.log.count("credits.save") == 0


# ------------------------------------------------------------------------------------- C3


async def test_the_clock_is_read_exactly_once_and_the_invoice_date_the_fact_and_the_entry_share_it() -> (  # noqa: E501
    None
):
    rig = Rig(credit=line())

    result = await invoice_issue.issue(command(), rig.scope)

    first = NOW + timedelta(seconds=1)
    assert rig.clock.calls == 1, f"BI13: the clock was read {rig.clock.calls} times"
    assert result.invoice.invoice_date == first
    [(invoice, events)] = rig.transactions.invoices.saved
    assert invoice.invoice_date == first
    assert len(events) == 1
    fact = events[0]
    assert isinstance(fact, InvoiceIssued)
    assert fact.occurred_at == first
    [credit] = rig.transactions.credits.saved
    [entry] = credit.appended_entries
    assert entry.entry_date == first, "the consume entry's date is not the one clock read"


# ------------------------------------------------------------------------------------- C4


async def test_bi8_locks_the_credit_line_then_re_reads_the_invoice_then_allocates_the_number() -> (
    None
):
    rig = Rig(credit=line())

    result = await invoice_issue.issue(command(), rig.scope)

    assert result.created is True
    assert rig.log.calls == [
        "lock_for_order",
        "invoices.find_by_order_reference",
        "next_reference",
        "invoices.save",
        "credits.save",
    ], "BI8: the issue path's calls are not lock, re-read, allocate, save, save"
    assert rig.reads.finds == [ORDER], "the fast path read happens once, outside the transaction"
    # J1: every call site is handed the ORDER named by the command (a fake that ignores its
    # arguments would let a substituted argument through)
    assert rig.transactions.credits.lock_args == [(RETAILER, COMPANY, ORDER)]
    assert rig.transactions.invoices.find_args == [ORDER]
    assert result.invoice.invoice_reference == "INV-000777"
    assert result.invoice.total_amount == 8115
    assert result.invoice.status is InvoiceStatus.ISSUED
    # J1: the aggregate was built from the RESOLVED line and the command, not mixed up
    [(invoice, _)] = rig.transactions.invoices.saved
    assert (invoice.retailer_code, invoice.company_code) == (RETAILER, COMPANY)
    assert (invoice.order_reference, invoice.currency) == (ORDER, "EUR")
    assert [(ln.product_code, ln.units.value, ln.unit_price.amount) for ln in invoice.lines] == [
        ("PRD-ZZ", 3, 1999),
        ("PRD-AA", 2, 1234),
    ]
    assert (invoice.amount.amount, invoice.discount.amount, invoice.total_amount.amount) == (
        8465,
        350,
        8115,
    )


# ------------------------------------------------------------------------------------- C5


async def test_bi34_the_issue_hands_the_scope_id_port_to_both_aggregates() -> None:
    supplied = [uid(0xB1), uid(0xB2), uid(0xB3), uid(0xB4), uid(0xB5)]
    rig = Rig(credit=line(), ids=supplied)

    result = await invoice_issue.issue(command(), rig.scope)

    # the consume entry mints first (step 4), then the invoice, its two lines and its fact
    [credit] = rig.transactions.credits.saved
    [entry] = credit.appended_entries
    assert entry.entry_id == uid(0xB1), "the consume entry's id is not from the scope's id port"
    assert entry.amount == Money(HOLD, "EUR")
    [(invoice, events)] = rig.transactions.invoices.saved
    assert invoice.id == uid(0xB2), "the invoice's id is not from the scope's id port"
    assert result.invoice.invoice_id == uid(0xB2)
    assert [ln.line_id for ln in invoice.lines] == [uid(0xB3), uid(0xB4)]
    assert events[0].event_id == uid(0xB5)  # type: ignore[attr-defined]
    assert rig.ids.minted == 5


async def test_the_result_is_returned_only_after_run_returns_with_both_saves_done() -> None:
    rig = Rig(credit=line())
    committing = asyncio.Event()
    release = asyncio.Event()
    seen_at_commit: list[str] = []

    async def commit() -> None:
        seen_at_commit.extend(rig.log.calls)
        committing.set()
        await release.wait()

    rig.transactions.after_work = commit
    task = asyncio.create_task(invoice_issue.issue(command(), rig.scope))
    await committing.wait()

    assert not task.done(), "the result was returned before the commit finished"
    assert seen_at_commit[-2:] == ["invoices.save", "credits.save"], (
        "both saves must have happened before the commit"
    )
    release.set()
    result = await task
    assert isinstance(result, InvoiceIssueResult)
    assert result.created is True


async def test_a_rollback_after_work_yields_no_result() -> None:
    rig = Rig(credit=line())

    class CommitFailed(Exception):
        pass

    async def fail() -> None:
        raise CommitFailed

    rig.transactions.after_work = fail

    with pytest.raises(CommitFailed):
        await invoice_issue.issue(command(), rig.scope)
