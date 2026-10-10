"""Builders for the buyer-credit aggregate's pure unit tests (`billing_credit/design.md` 13.1).

Pytest fixtures, not helper modules: the repository runs `--import-mode=importlib`, so a test module
cannot import a sibling module. Builders, not mocks. Every id is built from a distinct number, so
the credit line id, the entry ids, the correlation id and the causation id are pairwise different;
the order references, the retailer and the company code are chosen so that none contains another.

Loop scope: nothing here is async.
"""

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import pytest

from otc_billing.domain.buyer_credit import BuyerCredit, CreditContext, HoldRequest
from otc_billing.domain.credit_entry_type import CreditEntryType
from otc_billing.domain.snapshot import BuyerCreditSnapshot, CreditLedgerEntrySnapshot
from otc_shared_kernel import Money, UniqueId

CURRENCY = "EUR"
RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
WHEN = datetime(2026, 10, 8, 9, 30, 15, 123000, tzinfo=UTC)

# `(entry number, order reference, amount, type)`
EntryRow = tuple[int, str, int, CreditEntryType]


def _uid(number: int) -> UniqueId:
    return UniqueId(uuid.UUID(f"00000000-0000-4000-8000-{number:012x}"))


@pytest.fixture
def uid() -> Callable[[int], UniqueId]:
    """`uid(0xa1)`: a distinct, valid identifier per number."""
    return _uid


@pytest.fixture
def context() -> CreditContext:
    return CreditContext(occurred_at=WHEN, causation_id=_uid(0xCA0))


@pytest.fixture
def hold_request() -> Callable[..., HoldRequest]:
    def build(order_reference: str, amount: int, *, currency: str = CURRENCY) -> HoldRequest:
        return HoldRequest(
            order_reference=order_reference,
            amount=Money(amount, currency),
            correlation_id=_uid(0xC0),
        )

    return build


@pytest.fixture
def build_credit() -> Callable[..., BuyerCredit]:
    """`build_credit(limit=1000, committed=0, entries=[(1, "ORD-000101", 100, HOLD)])`."""

    def build(
        *,
        limit: int = 1000,
        committed: int = 0,
        entries: Sequence[EntryRow] = (),
        currency: str = CURRENCY,
        entry_currency: str | None = None,
    ) -> BuyerCredit:
        return BuyerCredit.rehydrate(
            BuyerCreditSnapshot(
                id=_uid(0x1D),
                code=CODE,
                retailer_code=RETAILER,
                company_code=COMPANY,
                currency=currency,
                credit_limit=limit,
                committed_exposure=committed,
                entries=tuple(
                    CreditLedgerEntrySnapshot(
                        entry_id=_uid(number),
                        order_reference=order_reference,
                        amount=Money(amount, entry_currency or currency),
                        type=entry_type,
                        entry_date=WHEN,
                    )
                    for number, order_reference, amount, entry_type in entries
                ),
            )
        )

    return build


@pytest.fixture
def id_source() -> Callable[[Sequence[UniqueId]], Callable[[], UniqueId]]:
    """`id_source([a, b, c])` -> a `new_id` that returns a, b, c in order and then fails loudly."""

    def make(supplied: Sequence[UniqueId]) -> Callable[[], UniqueId]:
        queue = list(supplied)

        def new_id() -> UniqueId:
            assert queue, "the domain asked for more identifiers than the test supplied"
            return queue.pop(0)

        return new_id

    return make
