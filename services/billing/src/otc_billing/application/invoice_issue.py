"""The invoice-issue transactional unit (`design.md` 6, 7.3; R45, BI3 - BI9, BI13, BI34, BI35).

```text
fast path, no transaction: the order already has an invoice -> reply it, created=False   (BI9)
run(work):
  1. lock_for_order            -- THE FIRST LOCK (BI8): the credits row FOR UPDATE
  2. invoices.find_by_order_reference   -- the B7 authority read, NO lock, a new statement
  3. currency differs from the line's -> InvoiceCurrencyMismatchError
  4. credit.consume            -- in memory; no active hold -> NoActiveHoldError, BEFORE the counter
  5. invoice_numbers.next_reference     -- THE LAST LOCK (BI8): the counter row FOR UPDATE
  6. Invoice.issue             -- raises exactly one InvoiceIssued
  7. invoices.save, credits.save
```

**The deviation from `domain-model.md` section 8 rule 6** ("one transaction mutates exactly one
aggregate instance plus its outbox records"): this transaction mutates an `Invoice` AND a
`BuyerCredit`. The invariant that no single aggregate owns is *an issued invoice's hold is
consumed*: neither order of two transactions can hold it (invoice first leaves an invoice over an
active hold that nothing can detect, because `consume` raises no event; `consume` first converts a
hold for an invoice that may never exist, and every retry then meets `NoActiveHoldError`, terminal
in Orders).
The argument is re-derived against this repository in `specs/billing_invoicing/design.md` 6.5.

The clock is read ONCE, after the fast path: the invoice date, the fact's `occurredAt` and the
`consume` entry's date are that one instant (BI13). `work` touches only its `CreditTransaction` and
its own arguments (bound with `functools.partial`). The reply is built from the result only after
`run()` returns, i.e. after the commit.
"""

from collections.abc import Callable
from functools import partial

from otc_billing.application.errors import CreditLineNotFoundError, InvoiceCurrencyMismatchError
from otc_billing.application.messages import (
    InvoiceIssueResult,
    InvoiceSummary,
    IssueInvoiceCommand,
)
from otc_billing.application.ports.credit_store import CreditTransaction
from otc_billing.application.scope import BillingScope
from otc_billing.domain.buyer_credit import CreditContext
from otc_billing.domain.invoice import (
    Invoice,
    InvoiceContext,
    IssueInvoiceInput,
    IssueLineInput,
)
from otc_billing.domain.invoice_snapshot import InvoiceSnapshot
from otc_billing.domain.invoice_state import state_token
from otc_shared_kernel import Money, Quantity, UniqueId


def _summary_of_snapshot(snapshot: InvoiceSnapshot) -> InvoiceSummary:
    return InvoiceSummary(
        invoice_id=snapshot.id,
        invoice_reference=snapshot.invoice_reference.value,
        invoice_date=snapshot.invoice_date,
        order_reference=snapshot.order_reference,
        currency=snapshot.currency,
        total_amount=snapshot.total_amount.amount,
        status=state_token(snapshot.state),
    )


def _summary_of_invoice(invoice: Invoice) -> InvoiceSummary:
    return InvoiceSummary(
        invoice_id=invoice.id,
        invoice_reference=invoice.invoice_reference.value,
        invoice_date=invoice.invoice_date,
        order_reference=invoice.order_reference,
        currency=invoice.currency,
        total_amount=invoice.total_amount.amount,
        status=invoice.status,
    )


async def _issue_work(
    tx: CreditTransaction,
    *,
    command: IssueInvoiceCommand,
    invoice_context: InvoiceContext,
    credit_context: CreditContext,
    new_id: Callable[[], UniqueId],
) -> InvoiceIssueResult:
    credit = await tx.credits.lock_for_order(  # 1. THE FIRST LOCK
        command.retailer_code, command.company_code, command.order_reference
    )
    if credit is None:
        raise CreditLineNotFoundError(command.retailer_code, command.company_code)
    existing = await tx.invoices.find_by_order_reference(command.order_reference)  # 2. no lock
    if existing is not None:
        return InvoiceIssueResult(created=False, invoice=_summary_of_snapshot(existing))
    if command.currency != credit.currency:  # 3.
        raise InvoiceCurrencyMismatchError(credit.currency, command.currency)
    credit.consume(command.order_reference, credit_context, new_id)  # 4. before the counter
    reference = await tx.invoice_numbers.next_reference()  # 5. THE LAST LOCK
    invoice = Invoice.issue(  # 6.
        IssueInvoiceInput(
            invoice_reference=reference,
            order_reference=command.order_reference,
            retailer_code=credit.retailer_code,
            company_code=credit.company_code,
            currency=credit.currency,
            lines=tuple(
                IssueLineInput(
                    product_code=line.product_code,
                    units=Quantity(line.units),
                    unit_price=Money(line.unit_price, credit.currency),
                )
                for line in command.lines
            ),
            discount=Money(command.discount, credit.currency),
            correlation_id=command.correlation_id,
        ),
        invoice_context,
        new_id,
    )
    await tx.invoices.save(invoice)  # 7.
    await tx.credits.save(credit)
    return InvoiceIssueResult(created=True, invoice=_summary_of_invoice(invoice))


async def issue(command: IssueInvoiceCommand, scope: BillingScope) -> InvoiceIssueResult:
    existing = await scope.invoice_reads.find_by_order_reference(command.order_reference)
    if existing is not None:  # BI9: a repeat is routine (saga.md 6 layer 3); no transaction opens
        return InvoiceIssueResult(created=False, invoice=_summary_of_snapshot(existing))
    now = scope.clock.now()  # the ONE clock read
    work = partial(
        _issue_work,
        command=command,
        invoice_context=InvoiceContext(occurred_at=now, causation_id=command.request_id),
        credit_context=CreditContext(occurred_at=now, causation_id=command.request_id),
        new_id=scope.ids.new,
    )
    return await scope.transactions.run(work)
