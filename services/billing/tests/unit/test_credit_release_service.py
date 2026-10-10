"""The release transactional unit, over fakes of the ports (task C4; BC11, BC25, BC36).

Loop scope: function (pytest-asyncio default); the only awaited things are in-memory fakes.
"""

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

import pytest

from otc_billing.application import credit_release
from otc_billing.application.errors import CreditLineNotFoundError
from otc_billing.application.messages import CreditPage, InvoicePage, ReleaseCreditCommand
from otc_billing.application.ports.credit_decision import CreditDecision
from otc_billing.application.ports.credit_store import CreditTransaction
from otc_billing.application.ports.invoice_store import InvoiceNumberAllocator, InvoiceRepository
from otc_billing.application.scope import BillingScope
from otc_billing.domain.buyer_credit import BuyerCredit
from otc_billing.domain.credit_entry_type import CreditEntryType as T
from otc_billing.domain.events import CreditReleased
from otc_billing.domain.invoice_snapshot import InvoiceSnapshot, PaymentSnapshot
from otc_billing.domain.reasons import CreditReleaseReason
from otc_billing.domain.snapshot import BuyerCreditSnapshot, CreditLedgerEntrySnapshot
from otc_shared_kernel import Money, UniqueId

NOW = datetime(2026, 10, 8, 9, 0, 0, 123000, tzinfo=UTC)
ORDER = "ORD-000101"
RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
# Another order holds 400 on the same line (D1); it is inside `committed`, because the aggregate
# loads only its own order's entries. Available-after is therefore never the limit.


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

    async def lock_for_order(
        self, retailer_code: str, company_code: str, order_reference: str
    ) -> BuyerCredit | None:
        return self.credit

    async def save(self, credit: BuyerCredit) -> None:
        self.saved.append((credit, credit.domain_events))


class FakeTransactions:
    def __init__(self, repository: FakeRepository) -> None:
        self.credits = repository

    @property
    def invoices(self) -> InvoiceRepository:
        raise AssertionError("the release touched the invoice repository")

    @property
    def invoice_numbers(self) -> InvoiceNumberAllocator:
        raise AssertionError("the release touched the invoice number allocator")

    async def run[T2](self, work: Callable[[CreditTransaction], Awaitable[T2]]) -> T2:
        return await work(self)


class NoReads:
    async def list(
        self, *, page: int, page_size: int, retailer_code: str | None, company_code: str | None
    ) -> CreditPage:
        raise AssertionError("the release read the list view")


class NoInvoiceReads:
    """The invoice reads: the release must never touch them."""

    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
        raise AssertionError("the release read an invoice")

    async def find_by_id(self, invoice_id: object) -> InvoiceSnapshot | None:
        raise AssertionError("the release read an invoice by id")

    async def find_by_invoice_reference(self, invoice_reference: str) -> InvoiceSnapshot | None:
        raise AssertionError("the release read an invoice by reference")

    async def find_payment_by_reference(self, payment_reference: str) -> PaymentSnapshot | None:
        raise AssertionError("the release read a payment")

    async def list(self, **kwargs: object) -> InvoicePage:
        raise AssertionError("the release read the invoice list")


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeIds:
    def __init__(self, supplied: Sequence[UniqueId]) -> None:
        self._queue = list(supplied)
        self.minted = 0

    def new(self) -> UniqueId:
        self.minted += 1
        assert self._queue, "the unit asked for more identifiers than the test supplied"
        return self._queue.pop(0)


class Port:
    def decide(self, request: object) -> CreditDecision:
        raise AssertionError("the release consulted the credit-decision port")


def rig(
    credit: BuyerCredit | None, ids: Sequence[UniqueId]
) -> tuple[FakeRepository, FakeIds, BillingScope]:
    repository = FakeRepository(credit)
    fake_ids = FakeIds(ids)
    scope = BillingScope(
        transactions=FakeTransactions(repository),
        reads=NoReads(),
        invoice_reads=NoInvoiceReads(),
        clock=FakeClock(),
        ids=fake_ids,
        credit_decision=Port(),
    )
    return repository, fake_ids, scope


def command() -> ReleaseCreditCommand:
    return ReleaseCreditCommand(
        order_reference=ORDER,
        retailer_code=RETAILER,
        company_code=COMPANY,
        correlation_id=uid(0xC0),
        request_id=uid(0xCA0),
    )


async def test_a_release_with_outstanding_exposure_records_exactly_one_release_entry_and_one_released_fact() -> (  # noqa: E501
    None
):
    repository, _, scope = rig(
        line(limit=1000, committed=650, entries=[(ORDER, 250, T.HOLD)]),
        [uid(0xA1), uid(0xA2)],
    )
    result = await credit_release.release(command(), scope)

    assert result.released is True
    assert (result.released_amount, result.available_credit_after) == (250, 600)
    assert (result.order_reference, result.credit_code, result.currency) == (ORDER, CODE, "EUR")
    assert len(repository.saved) == 1, "the release must save the aggregate exactly once"
    [(saved, events)] = repository.saved
    assert [(e.type, e.amount, e.entry_id) for e in saved.appended_entries] == [
        (T.RELEASE, Money(250, "EUR"), uid(0xA1))
    ], "exactly one release entry"
    assert len(events) == 1, f"expected exactly one credit.released.v1, got {len(events)}"
    assert events == (
        CreditReleased(
            event_id=uid(0xA2),
            aggregate_id=uid(0x1D),
            correlation_id=uid(0xC0),
            causation_id=uid(0xCA0),
            occurred_at=NOW,
            order_reference=ORDER,
            retailer_code=RETAILER,
            company_code=COMPANY,
            credit_code=CODE,
            currency="EUR",
            released_amount=250,
            available_credit_after=600,
            reason=CreditReleaseReason.ORDER_CANCELLED,
        ),
    ), "a field of the credit.released.v1 fact is wrong"


async def test_a_release_with_nothing_outstanding_writes_nothing_and_reports_released_false() -> (
    None
):
    never_held = rig(line(limit=1000, committed=400), [])
    already = rig(
        line(
            limit=1000,
            committed=400,
            entries=[(ORDER, 250, T.HOLD), (ORDER, 250, T.RELEASE)],
        ),
        [],
    )
    for case, (repository, fake_ids, scope) in {
        "never held": never_held,
        "released": already,
    }.items():
        result = await credit_release.release(command(), scope)
        assert result.released is False, case
        assert result.released_amount is None, case
        assert result.available_credit_after == 600, case
        assert (result.order_reference, result.credit_code, result.currency) == (ORDER, CODE, "EUR")
        assert repository.saved == [], f"{case}: save was called on a no-op release"
        assert repository.credit is not None
        assert repository.credit.domain_events == (), f"{case}: the no-op release recorded a fact"
        assert fake_ids.minted == 0, case


async def test_a_release_for_a_missing_line_raises_and_saves_nothing() -> None:
    repository, _, scope = rig(None, [])
    with pytest.raises(CreditLineNotFoundError):
        await credit_release.release(command(), scope)
    assert repository.saved == []


async def test_bc36_the_release_hands_the_scope_id_port_to_the_domain() -> None:
    repository, _, scope = rig(
        line(limit=1000, committed=250, entries=[(ORDER, 250, T.HOLD)]), [uid(0xB1), uid(0xB2)]
    )
    await credit_release.release(command(), scope)
    [(saved, events)] = repository.saved
    assert saved.appended_entries[0].entry_id == uid(0xB1), "BC36: the release entry id"
    assert isinstance(events[0], CreditReleased)
    assert events[0].event_id == uid(0xB2), "BC36: the released fact's event id"
