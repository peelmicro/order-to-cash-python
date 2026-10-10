"""The hold transactional unit, over fakes of the ports (task C3; BC7, BC13, BC14, BC36).

The fixtures are chosen so no value satisfies an assertion by accident: the order id is not the
request id is not the line id; retailer `RETAIL-77` is neither the company `SUPPLY-CO` nor contained
in it; every amount is distinct.

Loop scope: function (pytest-asyncio default); the only awaited things are in-memory fakes.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

import pytest

from otc_billing.application import credit_hold
from otc_billing.application.errors import CreditCurrencyMismatchError, CreditLineNotFoundError
from otc_billing.application.messages import (
    CreditPage,
    HoldCreditCommand,
    HoldOutcomeKind,
    InvoicePage,
)
from otc_billing.application.ports.credit_decision import (
    Approve,
    CreditDecision,
    CreditDecisionRequest,
    Refuse,
)
from otc_billing.application.ports.credit_store import CreditTransaction
from otc_billing.application.ports.invoice_store import InvoiceNumberAllocator, InvoiceRepository
from otc_billing.application.scope import BillingScope
from otc_billing.domain.buyer_credit import BuyerCredit
from otc_billing.domain.credit_entry_type import CreditEntryType as T
from otc_billing.domain.events import CreditApproved, CreditRejected
from otc_billing.domain.invoice_snapshot import InvoiceSnapshot, PaymentSnapshot
from otc_billing.domain.reasons import AdapterRejectionReason, CreditRejectionReason
from otc_billing.domain.snapshot import BuyerCreditSnapshot, CreditLedgerEntrySnapshot
from otc_shared_kernel import Money, UniqueId

NOW = datetime(2026, 10, 8, 9, 0, 0, 123000, tzinfo=UTC)
ORDER = "ORD-000101"
RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"


def uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(int=n))


def line(
    *, limit: int = 1000, committed: int = 0, entries: Sequence[tuple[str, int, T]] = ()
) -> BuyerCredit:
    return BuyerCredit.rehydrate(
        BuyerCreditSnapshot(
            id=uid(0x1D),
            code=CODE,
            retailer_code=RETAILER,
            company_code=COMPANY,
            currency="EUR",
            credit_limit=limit,
            committed_exposure=committed,
            entries=tuple(
                CreditLedgerEntrySnapshot(
                    entry_id=uid(0x100 + i),
                    order_reference=order,
                    amount=Money(amount, "EUR"),
                    type=kind,
                    entry_date=NOW,
                )
                for i, (order, amount, kind) in enumerate(entries)
            ),
        )
    )


class FakeRepository:
    def __init__(self, credit: BuyerCredit | None) -> None:
        self.credit = credit
        self.saved: list[tuple[BuyerCredit, tuple[object, ...]]] = []
        self.lock_calls: list[tuple[str, str, str]] = []

    async def lock_for_order(
        self, retailer_code: str, company_code: str, order_reference: str
    ) -> BuyerCredit | None:
        self.lock_calls.append((retailer_code, company_code, order_reference))
        return self.credit

    async def save(self, credit: BuyerCredit) -> None:
        # what the repository would drain, captured at the moment of the call
        self.saved.append((credit, credit.domain_events))


class FakeTransactions:
    def __init__(self, repository: FakeRepository) -> None:
        self.credits = repository
        self.runs = 0
        self.after_work: Callable[[], Awaitable[None]] | None = None

    @property
    def invoices(self) -> InvoiceRepository:
        raise AssertionError("the hold touched the invoice repository")

    @property
    def invoice_numbers(self) -> InvoiceNumberAllocator:
        raise AssertionError("the hold touched the invoice number allocator")

    async def run[T2](self, work: Callable[[CreditTransaction], Awaitable[T2]]) -> T2:
        self.runs += 1
        result = await work(self)
        if self.after_work is not None:
            await self.after_work()  # the commit: may block, or fail (a rollback)
        return result


class NoReads:
    """The list view: the hold must never touch it."""

    async def list(
        self, *, page: int, page_size: int, retailer_code: str | None, company_code: str | None
    ) -> CreditPage:
        raise AssertionError("the hold read the list view")


class NoInvoiceReads:
    """The invoice reads: the hold must never touch them."""

    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
        raise AssertionError("the hold read an invoice")

    async def find_by_id(self, invoice_id: object) -> InvoiceSnapshot | None:
        raise AssertionError("the hold read an invoice by id")

    async def find_by_invoice_reference(self, invoice_reference: str) -> InvoiceSnapshot | None:
        raise AssertionError("the hold read an invoice by reference")

    async def find_payment_by_reference(self, payment_reference: str) -> PaymentSnapshot | None:
        raise AssertionError("the hold read a payment")

    async def list(self, **kwargs: object) -> InvoicePage:
        raise AssertionError("the hold read the invoice list")


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeIds:
    def __init__(self, supplied: Sequence[UniqueId] = ()) -> None:
        self._queue = list(supplied)
        self.minted = 0

    def new(self) -> UniqueId:
        self.minted += 1
        assert self._queue, "the unit asked for more identifiers than the test supplied"
        return self._queue.pop(0)


class RecordingPort:
    def __init__(self, decision: CreditDecision) -> None:
        self.decision = decision
        self.requests: list[CreditDecisionRequest] = []

    def decide(self, request: CreditDecisionRequest) -> CreditDecision:
        self.requests.append(request)
        return self.decision


class Rig:
    def __init__(
        self,
        credit: BuyerCredit | None,
        *,
        decision: CreditDecision | None = None,
        ids: Sequence[UniqueId] = (uid(0xA1), uid(0xA2)),
    ) -> None:
        self.repository = FakeRepository(credit)
        self.transactions = FakeTransactions(self.repository)
        self.port = RecordingPort(decision or Approve())
        self.ids = FakeIds(ids)
        self.scope = BillingScope(
            transactions=self.transactions,
            reads=NoReads(),
            invoice_reads=NoInvoiceReads(),
            clock=FakeClock(),
            ids=self.ids,
            credit_decision=self.port,
        )


def command(amount: int = 250, *, currency: str = "EUR", order: str = ORDER) -> HoldCreditCommand:
    return HoldCreditCommand(
        order_reference=order,
        retailer_code=RETAILER,
        company_code=COMPANY,
        amount=Money(amount, currency),
        correlation_id=uid(0xC0),
        request_id=uid(0xCA0),
    )


async def test_bc7_already_held_on_a_released_hold_calls_no_port_and_writes_nothing() -> None:
    # the hold was released, so the order's net exposure is zero and the amount IS affordable
    rig = Rig(
        line(
            limit=1000,
            committed=0,
            entries=[(ORDER, 300, T.HOLD), (ORDER, 300, T.RELEASE)],
        )
    )
    result = await credit_hold.hold(command(250), rig.scope)
    assert result.outcome is HoldOutcomeKind.ALREADY_HELD
    assert result.held_amount == 300, "the reply must carry the RECORDED hold amount"
    assert result.available_credit == 1000, "the reply must carry the CURRENT available credit"
    assert (result.credit_code, result.currency, result.reason) == (CODE, "EUR", None)
    assert rig.port.requests == [], "BC7: the credit-decision port was consulted"
    assert rig.repository.saved == [], "BC7: something was saved"
    assert rig.ids.minted == 0
    assert rig.transactions.runs == 1


async def test_bc13_the_port_is_consulted_only_for_a_fitting_hold_and_never_for_an_over_limit_one() -> (  # noqa: E501
    None
):
    over = Rig(line(limit=1000, committed=400), ids=[uid(0xA3)])
    result = await credit_hold.hold(command(601), over.scope)
    assert result.outcome is HoldOutcomeKind.REJECTED
    assert result.reason is CreditRejectionReason.OVER_LIMIT
    assert len(over.port.requests) == 0, (
        f"BC13: the port was consulted {len(over.port.requests)} time(s) for an over-limit hold"
    )

    fits = Rig(line(limit=1000, committed=400))
    result = await credit_hold.hold(command(600), fits.scope)
    assert result.outcome is HoldOutcomeKind.APPROVED
    assert len(fits.port.requests) == 1, "BC13: the port must be consulted once for a fitting hold"
    [request] = fits.port.requests
    assert request == CreditDecisionRequest(
        order_reference=ORDER,
        retailer_code=RETAILER,
        company_code=COMPANY,
        credit_code=CODE,
        amount=Money(600, "EUR"),
        available_credit=Money(600, "EUR"),  # BEFORE the hold
    )


async def test_bc14_a_port_refusal_records_exactly_one_credit_rejected_fact_on_the_saved_aggregate() -> (  # noqa: E501
    None
):
    rig = Rig(
        line(limit=1000, committed=300),
        decision=Refuse(AdapterRejectionReason.SIMULATED_FAILURE_RATE),
        ids=[uid(0xA3)],
    )
    result = await credit_hold.hold(command(250), rig.scope)

    assert result.outcome is HoldOutcomeKind.REJECTED
    assert result.reason is CreditRejectionReason.SIMULATED_FAILURE_RATE, (
        "BC14: the reply carries a reason other than the port's"
    )
    assert result.held_amount is None
    assert result.available_credit == 700
    assert len(rig.repository.saved) == 1, "BC14: the refusal branch did not save the aggregate"
    saved, events = rig.repository.saved[0]
    assert saved.appended_entries == (), "BC14: a refusal appended a ledger entry"
    assert len(events) == 1, f"BC14: expected exactly one fact on the saved aggregate, got {events}"
    assert events == (
        CreditRejected(
            event_id=uid(0xA3),
            aggregate_id=uid(0x1D),
            correlation_id=uid(0xC0),
            causation_id=uid(0xCA0),
            occurred_at=NOW,
            order_reference=ORDER,
            retailer_code=RETAILER,
            company_code=COMPANY,
            credit_code=CODE,
            currency="EUR",
            requested_amount=250,
            available_credit=700,
            reason=CreditRejectionReason.SIMULATED_FAILURE_RATE,
        ),
    ), "BC14: a field of the port-refusal fact is wrong"


async def test_bc14_the_port_refusal_reason_is_the_ports_not_a_sibling() -> None:
    for adapter, expected in (
        (AdapterRejectionReason.SIMULATED_CENTS_RULE, CreditRejectionReason.SIMULATED_CENTS_RULE),
        (
            AdapterRejectionReason.SIMULATED_FAILURE_RATE,
            CreditRejectionReason.SIMULATED_FAILURE_RATE,
        ),
    ):
        rig = Rig(line(), decision=Refuse(adapter), ids=[uid(0xA3)])
        result = await credit_hold.hold(command(250), rig.scope)
        [(_, [fact])] = ((s, e) for s, e in rig.repository.saved)
        assert isinstance(fact, CreditRejected)
        assert fact.reason is expected, f"the fact carries {fact.reason}, the port said {adapter}"
        assert result.reason is expected


async def test_an_approved_hold_saves_once_and_replies_with_the_amounts() -> None:
    rig = Rig(line(limit=1000, committed=300))
    result = await credit_hold.hold(command(250), rig.scope)
    assert result.outcome is HoldOutcomeKind.APPROVED
    assert (result.held_amount, result.available_credit, result.reason) == (250, 450, None)
    assert (result.order_reference, result.credit_code, result.currency) == (ORDER, CODE, "EUR")
    assert len(rig.repository.saved) == 1
    [(saved, events)] = rig.repository.saved
    assert len(saved.appended_entries) == 1
    assert len(events) == 1
    assert isinstance(events[0], CreditApproved)
    assert rig.repository.lock_calls == [(RETAILER, COMPANY, ORDER)]


async def test_bc36_the_hold_hands_the_scope_id_port_to_the_domain() -> None:
    approved = Rig(line(), ids=[uid(0xB1), uid(0xB2)])
    await credit_hold.hold(command(250), approved.scope)
    [(saved, events)] = approved.repository.saved
    assert saved.appended_entries[0].entry_id == uid(0xB1), "BC36: the hold entry id"
    assert isinstance(events[0], CreditApproved)
    assert events[0].event_id == uid(0xB2), "BC36: the approved fact's event id"

    over = Rig(line(limit=100), ids=[uid(0xB3)])
    await credit_hold.hold(command(250), over.scope)
    [(_, over_events)] = over.repository.saved
    assert isinstance(over_events[0], CreditRejected)
    assert over_events[0].event_id == uid(0xB3), "BC36: the rejected fact's event id"

    refused = Rig(
        line(), decision=Refuse(AdapterRejectionReason.SIMULATED_CENTS_RULE), ids=[uid(0xB4)]
    )
    await credit_hold.hold(command(250), refused.scope)
    [(_, refused_events)] = refused.repository.saved
    assert isinstance(refused_events[0], CreditRejected)
    assert refused_events[0].event_id == uid(0xB4), "BC36: the port-refusal fact's event id"


async def test_a_missing_line_and_a_currency_mismatch_are_contract_violations_that_save_nothing() -> (  # noqa: E501
    None
):
    missing = Rig(None)
    with pytest.raises(CreditLineNotFoundError) as not_found:
        await credit_hold.hold(command(250), missing.scope)
    assert (not_found.value.retailer_code, not_found.value.company_code) == (RETAILER, COMPANY)
    assert missing.repository.saved == []
    assert missing.port.requests == []

    wrong = Rig(line())
    with pytest.raises(CreditCurrencyMismatchError) as mismatch:
        await credit_hold.hold(command(250, currency="USD"), wrong.scope)
    assert (mismatch.value.expected, mismatch.value.received) == ("EUR", "USD")
    assert wrong.repository.saved == []
    assert wrong.port.requests == []


async def test_the_reply_comes_only_after_run_returns_and_a_rollback_yields_no_reply() -> None:
    release_commit = asyncio.Event()
    committing = asyncio.Event()

    rig = Rig(line())

    async def slow_commit() -> None:
        committing.set()
        await release_commit.wait()

    rig.transactions.after_work = slow_commit
    task = asyncio.create_task(credit_hold.hold(command(250), rig.scope))
    async with asyncio.timeout(5):
        await committing.wait()
    assert not task.done(), "the unit returned before the transaction committed"
    assert len(rig.repository.saved) == 1  # the work is done, the commit is not
    release_commit.set()
    assert (await task).outcome is HoldOutcomeKind.APPROVED

    failing = Rig(line())

    async def failing_commit() -> None:
        raise ConnectionError("the commit failed")

    failing.transactions.after_work = failing_commit
    with pytest.raises(ConnectionError):
        await credit_hold.hold(command(250), failing.scope)
