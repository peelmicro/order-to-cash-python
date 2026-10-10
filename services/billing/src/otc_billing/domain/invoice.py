"""The `Invoice` aggregate root: one invoice per order, mirroring the despatched lines
(`design.md` 5.1, 5.3 - 5.5; invariants B6 - B10; R45, R46).

Synchronous and pure: no I/O, no clock, no port, no minting. The invoice id, every line id and every
fact's `event_id` come from the `new_id` parameter at each site (`BI34`).

* B6: `amount = sum(unit_price x units)` and `total_amount = amount - discount` are DERIVED in
  `issue` and exposed only as read-only properties; no setter exists. `issue` refuses an empty line
  list, a foreign currency, an out-of-range total (`invoice.total_overflow`, `BI25`) and a negative
  total. A zero total is legal (`BI35`).
* B8: `mark_paid` is the only transition, `issued -> paid`; a paid invoice refuses it.
* B9: `status` and `paid_at` are ONE value, `_state` (`invoice_state.py`); `mark_paid` assigns it in
  one statement and nothing else assigns it after `issue` / `rehydrate`.
* B10 (amount half): `mark_paid` refuses a payment whose amount or currency is not the invoice's.
* Every mutation is all-or-nothing: compute and check, THEN assign. A raised error leaves
  `to_snapshot()` unchanged and no event raised.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Self, assert_never

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
from otc_billing.domain.invoice_events import (
    InvoiceFactLine,
    InvoiceIssued,
    PaymentReceived,
    PaymentSource,
)
from otc_billing.domain.invoice_snapshot import InvoiceLineSnapshot, InvoiceSnapshot
from otc_billing.domain.invoice_state import (
    InvoiceState,
    InvoiceStatus,
    Issued,
    Paid,
    paid_at_of,
    state_token,
)
from otc_shared_kernel import AggregateRoot, InvoiceReference, Money, Quantity, UniqueId

__all__ = [
    "Invoice",
    "InvoiceContext",
    "InvoiceLine",
    "IssueInvoiceInput",
    "IssueLineInput",
    "PaymentInput",
    "PaymentSource",
]

MIN_MINOR_UNITS = -(1 << 63)
MAX_MINOR_UNITS = (1 << 63) - 1  # the write model's bigint column


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceContext:
    """What the application supplies besides the ids: the instant (from the clock port, read once)
    and the `causationId` (the request's `x-request-id`)."""

    occurred_at: datetime
    causation_id: UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class IssueLineInput:
    product_code: str
    units: Quantity
    unit_price: Money


@dataclass(frozen=True, slots=True, kw_only=True)
class IssueInvoiceInput:
    invoice_reference: InvoiceReference
    order_reference: str
    retailer_code: str
    company_code: str
    currency: str
    lines: tuple[IssueLineInput, ...]
    discount: Money
    correlation_id: UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentInput:
    payment_reference: str
    amount: Money
    value_date: datetime
    source: PaymentSource
    correlation_id: UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceLine:
    line_id: UniqueId
    product_code: str
    units: Quantity
    unit_price: Money

    @property
    def line_total(self) -> Money:
        """The only arithmetic on a line."""
        return self.unit_price.multiply(self.units)


def _in_range(value: int) -> bool:
    return MIN_MINOR_UNITS <= value <= MAX_MINOR_UNITS


class Invoice(AggregateRoot):
    __slots__ = (
        "_amount",
        "_company_code",
        "_currency",
        "_discount",
        "_invoice_date",
        "_invoice_reference",
        "_lines",
        "_order_reference",
        "_retailer_code",
        "_state",
        "_total_amount",
    )

    def __init__(
        self,
        invoice_id: UniqueId,
        *,
        invoice_reference: InvoiceReference,
        invoice_date: datetime,
        order_reference: str,
        retailer_code: str,
        company_code: str,
        currency: str,
        lines: tuple[InvoiceLine, ...],
        amount: Money,
        discount: Money,
        total_amount: Money,
        state: InvoiceState,
    ) -> None:
        super().__init__(invoice_id)
        self._invoice_reference = invoice_reference
        self._invoice_date = invoice_date
        self._order_reference = order_reference
        self._retailer_code = retailer_code
        self._company_code = company_code
        self._currency = currency
        self._lines = lines
        self._amount = amount
        self._discount = discount
        self._total_amount = total_amount
        self._state = state

    # ------------------------------------------------------------------------------- creation

    @classmethod
    def issue(
        cls, data: IssueInvoiceInput, context: InvoiceContext, new_id: Callable[[], UniqueId]
    ) -> Self:
        """The ONLY way an invoice comes into being. Checks first, then mints the invoice id, one
        id per line (the request's order) and the fact's id, and raises exactly one `InvoiceIssued`
        before returning (a caller can never hold an invoice whose fact was not recorded)."""
        if not data.lines:
            raise EmptyInvoiceLinesError
        for line in data.lines:
            if line.unit_price.currency != data.currency:
                raise InvoiceLineCurrencyMismatchError(data.currency, line.unit_price.currency)
        if data.discount.currency != data.currency:
            raise InvoiceLineCurrencyMismatchError(data.currency, data.discount.currency)
        # plain ints first: `Money` would refuse an out-of-range value with `money.invalid_amount`
        amount = sum(line.unit_price.amount * line.units.value for line in data.lines)
        if not _in_range(amount):
            raise InvoiceTotalOverflowError("amount")
        total = amount - data.discount.amount
        if not _in_range(total):
            raise InvoiceTotalOverflowError("total amount")
        if total < 0:
            raise NegativeInvoiceTotalError(amount, data.discount.amount, data.currency)

        invoice_id = new_id()
        lines = tuple(
            InvoiceLine(
                line_id=new_id(),
                product_code=line.product_code,
                units=line.units,
                unit_price=line.unit_price,
            )
            for line in data.lines
        )
        invoice = cls(
            invoice_id,
            invoice_reference=data.invoice_reference,
            invoice_date=context.occurred_at,
            order_reference=data.order_reference,
            retailer_code=data.retailer_code,
            company_code=data.company_code,
            currency=data.currency,
            lines=lines,
            amount=Money(amount, data.currency),
            discount=data.discount,
            total_amount=Money(total, data.currency),
            state=Issued(),
        )
        invoice._raise_event(
            InvoiceIssued(
                event_id=new_id(),
                aggregate_id=invoice_id,
                correlation_id=data.correlation_id,
                causation_id=context.causation_id,
                occurred_at=context.occurred_at,
                order_reference=data.order_reference,
                invoice_reference=data.invoice_reference,
                invoice_date=context.occurred_at,
                retailer_code=data.retailer_code,
                company_code=data.company_code,
                currency=data.currency,
                lines=tuple(
                    InvoiceFactLine(
                        product_code=line.product_code,
                        units=line.units.value,
                        unit_price=line.unit_price.amount,
                    )
                    for line in data.lines
                ),
                amount=amount,
                discount=data.discount.amount,
                total_amount=total,
            )
        )
        return invoice

    @classmethod
    def rehydrate(cls, snapshot: InvoiceSnapshot) -> Self:
        """Restore a stored invoice. Bypasses `issue` and raises no event.

        Refuses (B6): no lines, a line or total in another currency than the invoice's, and stored
        `amount` / `total_amount` that disagree with the lines and the discount, or a negative
        total. The state is already ONE value (`parse_invoice_state` refused a disagreeing pair).
        """
        if not snapshot.lines:
            raise InvalidInvoiceSnapshotError("the invoice has no lines")
        for money in (
            snapshot.amount,
            snapshot.discount,
            snapshot.total_amount,
            *(line.unit_price for line in snapshot.lines),
        ):
            if money.currency != snapshot.currency:
                raise InvalidInvoiceSnapshotError(
                    f"{money.currency} amount in an invoice in {snapshot.currency}"
                )
        amount = sum(line.unit_price.amount * line.units.value for line in snapshot.lines)
        if snapshot.amount.amount != amount:
            raise InvalidInvoiceSnapshotError(
                f"stored amount {snapshot.amount.amount} is not the lines' sum {amount}"
            )
        total = amount - snapshot.discount.amount
        if snapshot.total_amount.amount != total or total < 0:
            raise InvalidInvoiceSnapshotError(
                f"stored total {snapshot.total_amount.amount} is not amount - discount "
                f"({total}) or is negative"
            )
        return cls(
            snapshot.id,
            invoice_reference=snapshot.invoice_reference,
            invoice_date=snapshot.invoice_date,
            order_reference=snapshot.order_reference,
            retailer_code=snapshot.retailer_code,
            company_code=snapshot.company_code,
            currency=snapshot.currency,
            lines=tuple(
                InvoiceLine(
                    line_id=line.id,
                    product_code=line.product_code,
                    units=line.units,
                    unit_price=line.unit_price,
                )
                for line in snapshot.lines
            ),
            amount=snapshot.amount,
            discount=snapshot.discount,
            total_amount=snapshot.total_amount,
            state=snapshot.state,
        )

    # ------------------------------------------------------------------------------------ reads

    @property
    def invoice_reference(self) -> InvoiceReference:
        return self._invoice_reference

    @property
    def invoice_date(self) -> datetime:
        return self._invoice_date

    @property
    def order_reference(self) -> str:
        return self._order_reference

    @property
    def retailer_code(self) -> str:
        return self._retailer_code

    @property
    def company_code(self) -> str:
        return self._company_code

    @property
    def currency(self) -> str:
        return self._currency

    @property
    def lines(self) -> tuple[InvoiceLine, ...]:
        return self._lines

    @property
    def amount(self) -> Money:
        return self._amount

    @property
    def discount(self) -> Money:
        return self._discount

    @property
    def total_amount(self) -> Money:
        return self._total_amount

    @property
    def state(self) -> InvoiceState:
        return self._state

    @property
    def status(self) -> InvoiceStatus:
        return state_token(self._state)

    @property
    def paid_at(self) -> datetime | None:
        return paid_at_of(self._state)

    # ---------------------------------------------------------------------------- mark_paid

    def mark_paid(
        self, payment: PaymentInput, context: InvoiceContext, new_id: Callable[[], UniqueId]
    ) -> PaymentReceived:
        """`issued -> paid` (R46), the only transition. Refuses a paid invoice, another currency
        and another amount than the invoice's total, changing and raising nothing. Otherwise ONE
        assignment of the state and exactly one `PaymentReceived`, raised AND returned (feature
        22 makes `credit.released.v1`'s `causationId` its `event_id`)."""
        match self._state:
            case Paid():
                raise InvoiceAlreadyPaidError(self._invoice_reference.value)
            case Issued():
                pass
            case _:
                assert_never(self._state)
        if payment.amount.currency != self._currency:
            raise InvoicePaymentCurrencyMismatchError(self._currency, payment.amount.currency)
        if payment.amount.amount != self._total_amount.amount:
            raise InvoicePaymentAmountMismatchError(
                self._total_amount.amount, payment.amount.amount, self._currency
            )
        paid = Paid(context.occurred_at)
        fact = PaymentReceived(
            event_id=new_id(),
            aggregate_id=self.id,
            correlation_id=payment.correlation_id,
            causation_id=context.causation_id,
            occurred_at=context.occurred_at,
            order_reference=self._order_reference,
            invoice_reference=self._invoice_reference,
            payment_reference=payment.payment_reference,
            amount=payment.amount.amount,
            currency=payment.amount.currency,
            value_date=payment.value_date,
            source=payment.source,
        )
        self._state = paid
        self._raise_event(fact)
        return fact

    def to_snapshot(self) -> InvoiceSnapshot:
        return InvoiceSnapshot(
            id=self.id,
            invoice_reference=self._invoice_reference,
            invoice_date=self._invoice_date,
            order_reference=self._order_reference,
            retailer_code=self._retailer_code,
            company_code=self._company_code,
            currency=self._currency,
            lines=tuple(
                InvoiceLineSnapshot(
                    id=line.line_id,
                    product_code=line.product_code,
                    units=line.units,
                    unit_price=line.unit_price,
                )
                for line in self._lines
            ),
            amount=self._amount,
            discount=self._discount,
            total_amount=self._total_amount,
            state=self._state,
        )
