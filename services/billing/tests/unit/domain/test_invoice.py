"""The `Invoice` aggregate (tasks B5, B7, B9, B10; R45, R46, BI10, BI11, BI14, BI25, BI35, BI38).

Pure; nothing async. Fixtures are chosen so no value satisfies an assertion by accident: the order
id (`0xC0`), the request id (`0xD0`), the invoice id and the line ids are pairwise different;
retailer `RETAIL-77` is neither the company `SUPPLY-CO` nor contained in it; the lines are sent
in an order that is NOT the canonical `(product_code, id)` order; and the three totals are
pairwise-distinct, non-zero numbers none of which contains another: amount 8465, discount 350,
total 8115 (the plausible wrong values -- total = amount, total = discount, amount = total -- are
each a different number). Builders live in this module: the repository runs
`--import-mode=importlib`, so a test module cannot import a sibling.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial

import pytest

from otc_billing.domain.invoice import (
    Invoice,
    InvoiceContext,
    IssueInvoiceInput,
    IssueLineInput,
    PaymentInput,
    PaymentSource,
)
from otc_billing.domain.invoice_errors import (
    EmptyInvoiceLinesError,
    InvalidInvoiceSnapshotError,
    InvoiceAlreadyPaidError,
    InvoiceLineCurrencyMismatchError,
    InvoicePaymentAmountMismatchError,
    InvoicePaymentCurrencyMismatchError,
    InvoiceTotalOverflowError,
    NegativeInvoiceTotalError,
)
from otc_billing.domain.invoice_events import InvoiceIssued, PaymentReceived
from otc_billing.domain.invoice_snapshot import InvoiceLineSnapshot, InvoiceSnapshot
from otc_billing.domain.invoice_state import InvoiceStatus, Issued, Paid
from otc_shared_kernel import InvoiceReference, Money, Quantity, UniqueId

ORDER = "ORD-000101"
RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CURRENCY = "EUR"
WHEN = datetime(2026, 10, 9, 10, 15, 30, 123000, tzinfo=UTC)
LATER = WHEN + timedelta(days=3, hours=1)
VALUE_DATE = WHEN + timedelta(days=1, minutes=7)  # distinct from the context's instant


def uid(number: int) -> UniqueId:
    return UniqueId(uuid.UUID(f"00000000-0000-4000-8000-{number:012x}"))


def id_source(supplied: Sequence[UniqueId]) -> Callable[[], UniqueId]:
    queue = list(supplied)

    def new_id() -> UniqueId:
        assert queue, "the aggregate asked for more identifiers than the test supplied"
        return queue.pop(0)

    return new_id


def refuse_minting() -> UniqueId:
    raise AssertionError(
        "the aggregate began constructing an invoice that should have been refused (id minted)"
    )


def outcome(call: Callable[[], object]) -> Exception | None:
    """The exception a call raised, or None: lets a test say which claim failed."""
    try:
        call()
    except Exception as error:
        return error
    return None


def only_event(invoice: Invoice, claim: str) -> object:
    """The one raised event; the count is asserted BEFORE any unpacking."""
    events = invoice.domain_events
    assert len(events) == 1, f"{claim}: expected exactly one event, got {len(events)}"
    return events[0]


def context(at: datetime = WHEN) -> InvoiceContext:
    return InvoiceContext(occurred_at=at, causation_id=uid(0xD0))


def two_lines() -> tuple[IssueLineInput, ...]:
    """NOT in canonical `(product_code, id)` order: `PRD-ZZ` is sent before `PRD-AA`.
    3 x 1999 + 2 x 1234 = 8465."""
    return (
        IssueLineInput(product_code="PRD-ZZ", units=Quantity(3), unit_price=Money(1999, CURRENCY)),
        IssueLineInput(product_code="PRD-AA", units=Quantity(2), unit_price=Money(1234, CURRENCY)),
    )


def issue_input(
    *,
    lines: tuple[IssueLineInput, ...] | None = None,
    discount: int = 350,
    currency: str = CURRENCY,
) -> IssueInvoiceInput:
    return IssueInvoiceInput(
        invoice_reference=InvoiceReference.from_sequence(321),
        order_reference=ORDER,
        retailer_code=RETAILER,
        company_code=COMPANY,
        currency=currency,
        lines=two_lines() if lines is None else lines,
        discount=Money(discount, currency),
        correlation_id=uid(0xC0),
    )


def issued(*, discount: int = 350) -> Invoice:
    return Invoice.issue(
        issue_input(discount=discount),
        context(),
        id_source([uid(0xA0), uid(0xA1), uid(0xA2), uid(0xA3)]),
    )


def payment(
    *,
    amount: int = 8115,
    currency: str = CURRENCY,
    source: PaymentSource = PaymentSource.ROBOT,
    reference: str = "PAY-77-ABC",
) -> PaymentInput:
    return PaymentInput(
        payment_reference=reference,
        amount=Money(amount, currency),
        value_date=VALUE_DATE,
        source=source,
        correlation_id=uid(0xC0),
    )


# ------------------------------------------------------------------------------------ R45


def test_r45_creates_exactly_one_issued_invoice_mirroring_the_despatched_lines_with_a_non_negative_total_and_returns_the_existing_reference_emitting_no_second_fact_on_a_repeat() -> (  # noqa: E501
    None
):
    """The aggregate half of `R45`: the REPEAT half ("returns the existing reference, emits no
    second fact") is the application's and the store's -- C2 (fast path, in-transaction re-read)
    and F6 (through the real host) -- because an aggregate cannot know another exists."""
    invoice = issued()

    assert invoice.status is InvoiceStatus.ISSUED
    assert invoice.paid_at is None
    assert invoice.state == Issued()
    # the lines mirror the request, in the REQUEST's order (PRD-ZZ before PRD-AA)
    assert [(ln.product_code, ln.units.value, ln.unit_price.amount) for ln in invoice.lines] == [
        ("PRD-ZZ", 3, 1999),
        ("PRD-AA", 2, 1234),
    ]
    assert invoice.invoice_date == WHEN
    assert invoice.invoice_reference.value == "INV-000321"
    # the totals are DERIVED: a non-zero discount reaches the total (BI38's domain half)
    assert invoice.amount == Money(8465, CURRENCY)
    assert invoice.discount == Money(350, CURRENCY)
    assert invoice.total_amount == Money(8115, CURRENCY)
    assert invoice.total_amount.amount >= 0
    fact = only_event(invoice, "R45")  # exactly one event
    assert isinstance(fact, InvoiceIssued)
    assert fact.total_amount == 8115
    assert fact.discount == 350
    assert fact.amount == 8465


def test_bi11_derives_amount_and_total_from_the_lines_and_refuses_empty_lines_a_foreign_currency_and_a_negative_total() -> (  # noqa: E501
    None
):
    # derivation: a different discount moves only the total
    other = issued(discount=1)
    assert (other.amount.amount, other.discount.amount, other.total_amount.amount) == (
        8465,
        1,
        8464,
    )
    # the boundary: discount == amount is a zero total, legal; one more is negative, refused
    assert issued(discount=8465).total_amount.amount == 0

    refusals: list[tuple[IssueInvoiceInput, type[Exception], str]] = [
        (issue_input(lines=()), EmptyInvoiceLinesError, "invoice.empty_lines"),
        (
            issue_input(
                lines=(
                    IssueLineInput(
                        product_code="PRD-AA", units=Quantity(1), unit_price=Money(5, "USD")
                    ),
                )
            ),
            InvoiceLineCurrencyMismatchError,
            "invoice.line_currency_mismatch",
        ),
        (
            replace(issue_input(), discount=Money(350, "USD")),
            InvoiceLineCurrencyMismatchError,
            "invoice.line_currency_mismatch",
        ),
        (issue_input(discount=8466), NegativeInvoiceTotalError, "invoice.negative_total"),
    ]
    for data, error_type, code in refusals:
        error = outcome(partial(Invoice.issue, data, context(), refuse_minting))
        assert isinstance(error, error_type), (
            f"BI11: expected {code} ({error_type.__name__}), got {error!r}"
        )
        assert getattr(error, "code", None) == code


def test_bi25_an_out_of_range_line_total_raises_invoice_total_overflow_with_its_code() -> None:
    lines = (
        IssueLineInput(
            product_code="PRD-AA", units=Quantity(2), unit_price=Money(1 << 62, CURRENCY)
        ),
        IssueLineInput(
            product_code="PRD-BB", units=Quantity(2), unit_price=Money(1 << 62, CURRENCY)
        ),
    )
    ids = [uid(n) for n in range(1, 9)]  # enough that a missing check is not an id-queue error
    error = outcome(
        partial(Invoice.issue, issue_input(lines=lines, discount=0), context(), id_source(ids))
    )
    assert isinstance(error, InvoiceTotalOverflowError), (
        f"BI25: expected invoice.total_overflow, got {error!r}"
    )
    assert error.code == "invoice.total_overflow"
    # the other path: the amount is in range, the total is beyond int64's maximum (a negative
    # discount, which the edge refuses and the domain must still not wrap or truncate)
    one = (IssueLineInput(product_code="PRD-AA", units=Quantity(1), unit_price=Money(1, CURRENCY)),)
    beyond = replace(issue_input(lines=one), discount=Money(-((1 << 63) - 1), CURRENCY))
    error = outcome(partial(Invoice.issue, beyond, context(), id_source(ids)))
    assert isinstance(error, InvoiceTotalOverflowError), (
        f"BI25: expected invoice.total_overflow for an out-of-range total, got {error!r}"
    )
    assert error.code == "invoice.total_overflow"
    # control: the largest representable total is accepted
    top = (
        IssueLineInput(
            product_code="PRD-AA", units=Quantity(1), unit_price=Money((1 << 63) - 1, CURRENCY)
        ),
    )
    assert (
        Invoice.issue(
            issue_input(lines=top, discount=0),
            context(),
            id_source([uid(1), uid(2), uid(3)]),
        ).total_amount.amount
        == (1 << 63) - 1
    )


def test_the_totals_state_and_lines_of_an_issued_invoice_have_no_setter() -> None:
    """Assigning any of them raises `AttributeError` and changes nothing (B6, B9)."""
    invoice = issued()
    before = invoice.to_snapshot()
    for name, value in (
        ("amount", Money(1, CURRENCY)),
        ("discount", Money(1, CURRENCY)),
        ("total_amount", Money(1, CURRENCY)),
        ("status", InvoiceStatus.PAID),
        ("paid_at", WHEN),
        ("lines", ()),
        ("state", Paid(WHEN)),
    ):
        with pytest.raises(AttributeError):
            setattr(invoice, name, value)
    assert invoice.to_snapshot() == before


# ------------------------------------------------------------------------------------ R46


def test_r46_allows_only_the_transition_from_issued_to_paid_sets_paid_at_exactly_then_and_raises_on_every_other_transition_changing_and_emitting_nothing() -> (  # noqa: E501
    None
):
    invoice = issued()
    invoice.pull_domain_events()  # the issue fact is not under test here
    assert invoice.paid_at is None

    fact = invoice.mark_paid(payment(), context(LATER), id_source([uid(0xB0)]))

    assert invoice.status is InvoiceStatus.PAID
    assert invoice.paid_at == LATER, "paid_at must be the context's instant"
    assert invoice.paid_at != invoice.invoice_date
    assert invoice.paid_at != VALUE_DATE
    assert invoice.domain_events == (fact,), "exactly one event, the one returned"

    # every other transition: paid -> paid raises, changes nothing, emits nothing
    before = invoice.to_snapshot()
    events_before = invoice.domain_events
    with pytest.raises(InvoiceAlreadyPaidError) as caught:
        invoice.mark_paid(payment(), context(LATER + timedelta(hours=5)), id_source([uid(0xB1)]))
    assert caught.value.code == "invoice.already_paid"
    assert invoice.to_snapshot() == before, "a refused transition changed the invoice"
    assert invoice.paid_at == LATER, "a second mark_paid overwrote paid_at"
    assert invoice.domain_events == events_before, "a refused transition emitted a fact"
    assert len(invoice.domain_events) == 1


def test_bi10_status_and_paid_at_are_one_value_and_a_disagreeing_snapshot_is_refused() -> None:
    invoice = issued()
    # the instance holds ONE state attribute and no separate status / paid_at
    slots = {name for klass in type(invoice).__mro__ for name in getattr(klass, "__slots__", ())}
    assert "_state" in slots
    assert "_status" not in slots, "BI10: a separate _status attribute exists"
    assert "_paid_at" not in slots, "BI10: a separate _paid_at attribute exists"

    snapshot = invoice.to_snapshot()
    assert Invoice.rehydrate(snapshot).to_snapshot() == snapshot  # the control loads
    paid_snapshot = replace(snapshot, state=Paid(LATER))
    assert Invoice.rehydrate(paid_snapshot).paid_at == LATER

    # a stored amount or total that disagrees with the lines and the discount is refused
    wrong = {
        "amount": replace(snapshot, amount=Money(8466, CURRENCY)),
        "total_amount": replace(snapshot, total_amount=Money(8116, CURRENCY)),
        "total_equals_amount": replace(snapshot, total_amount=Money(8465, CURRENCY)),
        "no lines": replace(snapshot, lines=()),
        "currency": replace(snapshot, amount=Money(8465, "USD")),
    }
    for label, bad in wrong.items():
        with pytest.raises(InvalidInvoiceSnapshotError) as caught:
            Invoice.rehydrate(bad)
        assert caught.value.code == "invoice.invalid_snapshot", label
    # a negative stored total is refused even when it agrees with amount - discount
    negative = replace(snapshot, discount=Money(9000, CURRENCY), total_amount=Money(-535, CURRENCY))
    with pytest.raises(InvalidInvoiceSnapshotError):
        Invoice.rehydrate(negative)
    assert isinstance(snapshot.lines[0], InvoiceLineSnapshot)
    assert isinstance(snapshot, InvoiceSnapshot)


# ------------------------------------------------------------------------------------ BI14


def test_bi14_mark_paid_moves_issued_to_paid_with_paid_at_in_one_step_and_one_fact_carrying_every_payment_field() -> (  # noqa: E501
    None
):
    invoice = issued()
    invoice.pull_domain_events()
    pay = PaymentInput(
        payment_reference="PAY-77-ABC",
        amount=Money(8115, CURRENCY),
        value_date=VALUE_DATE,
        source=PaymentSource.ROBOT,  # not the first member of the enum
        correlation_id=uid(0xC0),
    )

    returned = invoice.mark_paid(pay, context(LATER), id_source([uid(0xB0)]))

    raised = only_event(invoice, "BI14")
    assert returned is raised, "mark_paid must RETURN the object it raised (#8 id 57)"
    assert isinstance(returned, PaymentReceived)
    assert invoice.state == Paid(LATER)
    # every field against a test-supplied, pairwise-distinct value (#8's D1: two of these
    # survived corruption there)
    assert returned.event_id == uid(0xB0)
    assert returned.aggregate_id == uid(0xA0), "aggregate_id is the INVOICE's id"
    assert returned.correlation_id == uid(0xC0)
    assert returned.causation_id == uid(0xD0)
    assert returned.occurred_at == LATER
    assert returned.order_reference == ORDER
    assert returned.invoice_reference.value == "INV-000321"
    assert returned.payment_reference == "PAY-77-ABC"
    assert returned.amount == 8115
    assert returned.currency == CURRENCY
    assert returned.value_date == VALUE_DATE
    assert returned.value_date != LATER, "value_date must not equal the context's instant"
    assert returned.source is PaymentSource.ROBOT
    assert returned.source is not next(iter(PaymentSource))
    assert returned.amount != invoice.amount.amount, "the fixture's payment equals the gross"


def test_bi14_mark_paid_refuses_a_paid_invoice_a_wrong_amount_and_a_wrong_currency_changing_and_emitting_nothing() -> (  # noqa: E501
    None
):
    for bad, error_type, code in (
        (
            payment(amount=8116),
            InvoicePaymentAmountMismatchError,
            "invoice.payment_amount_mismatch",
        ),
        (
            payment(amount=8465),
            InvoicePaymentAmountMismatchError,
            "invoice.payment_amount_mismatch",
        ),
        (
            payment(currency="USD"),
            InvoicePaymentCurrencyMismatchError,
            "invoice.payment_currency_mismatch",
        ),
    ):
        invoice = issued()
        invoice.pull_domain_events()
        before = invoice.to_snapshot()
        with pytest.raises(error_type) as caught:
            invoice.mark_paid(bad, context(LATER), id_source([uid(0xB0)]))
        assert getattr(caught.value, "code", None) == code
        assert invoice.to_snapshot() == before, f"{code}: the invoice changed"
        assert invoice.domain_events == (), f"{code}: a fact was raised"
        assert invoice.state == Issued()
    # a paid invoice refuses, whatever the payment
    paid = issued()
    paid.mark_paid(payment(), context(LATER), id_source([uid(0xB0)]))
    paid.pull_domain_events()
    before = paid.to_snapshot()
    with pytest.raises(InvoiceAlreadyPaidError):
        paid.mark_paid(payment(), context(LATER), id_source([uid(0xB1)]))
    assert paid.to_snapshot() == before
    assert paid.domain_events == ()


# ------------------------------------------------------------------------------------ BI35


def test_bi35_a_zero_total_invoice_is_issued() -> None:
    one = (
        IssueLineInput(product_code="PRD-AA", units=Quantity(3), unit_price=Money(1999, CURRENCY)),
    )
    try:
        invoice = Invoice.issue(
            issue_input(lines=one, discount=5997),  # zero_total_on_purpose: discount == the gross
            context(),
            id_source([uid(1), uid(2), uid(3)]),
        )
    except NegativeInvoiceTotalError as refused:
        pytest.fail(f"BI35: a zero-total invoice was refused: {refused}")
    assert invoice.amount.amount == 5997
    assert invoice.total_amount.amount == 0, "zero_total_on_purpose"
    fact = only_event(invoice, "BI35")
    assert isinstance(fact, InvoiceIssued)
    assert fact.total_amount == 0
