"""The remittance-intake transactional unit (`billing.payment.register`; R47 - R49, BI8, #8 id 57).

```text
fast path, no transaction: the paymentReference is stored -> duplicate (or, for another invoice or
                           another amount, PaymentReferenceReusedError)                     (R48)
resolve the invoice, UNLOCKED, to learn its credit line's party pair                        (BI8)
run(work):
  1. lock_for_order         -- THE FIRST LOCK (BI8): the credits row FOR UPDATE
  2. invoices.find_by_id    -- the re-read AFTER the lock, plain: sees what a competitor committed
  3. invoices.find_payment_by_reference -- the R48 authority read, under the lock
  4. Invoice.mark_paid      -- R49's three refusals; raises payment.received.v1, returns it
  5. credit.release         -- INVOICE_PAID; its causationId is the payment fact's eventId (id 57);
                               None (nothing outstanding) is REFUSED, never discarded (#8's N3)
  6. invoices.mark_paid     -- UPDATE the invoice, INSERT the payment, outbox row 1
  7. credits.save           -- the release entry, outbox row 2
```

**R47's ordering is structural**: step 6 happens before step 7 (call order), and the outbox `seq`
is an `Identity` column, so `payment.received.v1` gets the lower `seq`. (The writer's per-row flush
matters only when one `write()` carries several events, which no Billing transaction does yet.)
The clock is read ONCE, after the fast path and
the resolution: the paid instant, both facts' `occurredAt` and the release entry's date are that one
instant. `work` touches only its `CreditTransaction` and its own arguments; the reply is built from
the result only after `run()` returns, i.e. after the commit.

**What a reused reference answers.** The same `paymentReference` stored against another invoice,
or against this one with another amount or currency, is `PaymentReferenceReusedError`
(`openapi.yaml` 673: "the key is being used to mean two different things"), on the fast path, under
the lock and, for a competitor on another credit line, through the `payments` UNIQUE constraint. #7
and #8 compared the invoice identity only; the amount and currency comparison is the shared
contract's text.
"""

from collections.abc import Callable
from functools import partial

from otc_billing.application.errors import (
    CreditLineNotFoundError,
    CreditNotOutstandingError,
    InvoiceNotFoundError,
    PaymentReferenceReusedError,
)
from otc_billing.application.messages import (
    PaymentOutcome,
    PaymentRegisterResult,
    RegisterPaymentCommand,
)
from otc_billing.application.ports.credit_store import CreditTransaction
from otc_billing.application.ports.invoice_store import InvoiceReads
from otc_billing.application.scope import BillingScope
from otc_billing.domain.buyer_credit import CreditContext
from otc_billing.domain.invoice import Invoice, InvoiceContext, PaymentInput
from otc_billing.domain.invoice_snapshot import InvoiceSnapshot, PaymentSnapshot
from otc_billing.domain.invoice_state import paid_at_of, state_token
from otc_billing.domain.reasons import CreditReleaseReason
from otc_shared_kernel import UniqueId


def _identity_matches(command: RegisterPaymentCommand, invoice: InvoiceSnapshot) -> bool:
    """Whichever identifiers the caller supplied name THIS invoice (an absent one is not a
    mismatch: the edge guarantees at least one)."""
    if command.invoice_id is not None and command.invoice_id != invoice.id:
        return False
    return (
        command.invoice_reference is None
        or command.invoice_reference == invoice.invoice_reference.value
    )


def _duplicate(
    command: RegisterPaymentCommand, invoice: InvoiceSnapshot, payment: PaymentSnapshot
) -> PaymentRegisterResult:
    """R48: the stored payment answers a repeat with the original outcome, or, when the reference
    means something else in this request, refuses it."""
    if (
        payment.invoice_id != invoice.id
        or not _identity_matches(command, invoice)
        or payment.amount != command.amount
    ):
        raise PaymentReferenceReusedError(command.payment_reference)
    return PaymentRegisterResult(
        outcome=PaymentOutcome.DUPLICATE,
        payment_reference=payment.payment_reference,
        invoice_reference=invoice.invoice_reference.value,
        order_reference=invoice.order_reference,
        invoice_status=state_token(invoice.state),
        paid_at=paid_at_of(invoice.state),
    )


async def _resolve(command: RegisterPaymentCommand, reads: InvoiceReads) -> InvoiceSnapshot:
    """The invoice the request names, unlocked. Both identifiers, when both are given, must name the
    same invoice."""
    found: InvoiceSnapshot | None = None
    if command.invoice_id is not None:
        found = await reads.find_by_id(command.invoice_id)
    elif command.invoice_reference is not None:
        found = await reads.find_by_invoice_reference(command.invoice_reference)
    if found is None or not _identity_matches(command, found):
        raise InvoiceNotFoundError(
            None if command.invoice_id is None else str(command.invoice_id.value),
            command.invoice_reference,
        )
    return found


async def _register_work(
    tx: CreditTransaction,
    *,
    command: RegisterPaymentCommand,
    target: InvoiceSnapshot,
    invoice_context: InvoiceContext,
    new_id: Callable[[], UniqueId],
) -> PaymentRegisterResult:
    credit = await tx.credits.lock_for_order(  # 1. THE FIRST LOCK
        target.retailer_code, target.company_code, target.order_reference
    )
    if credit is None:
        raise CreditLineNotFoundError(target.retailer_code, target.company_code)
    snapshot = await tx.invoices.find_by_id(target.id)  # 2. the re-read, after the lock, plain
    if snapshot is None:
        raise InvoiceNotFoundError(str(target.id.value), target.invoice_reference.value)
    stored = await tx.invoices.find_payment_by_reference(command.payment_reference)  # 3.
    if stored is not None:
        return _duplicate(command, snapshot, stored)
    invoice = Invoice.rehydrate(snapshot)
    fact = invoice.mark_paid(  # 4.
        PaymentInput(
            payment_reference=command.payment_reference,
            amount=command.amount,
            value_date=command.value_date,
            source=command.source,
            correlation_id=command.correlation_id,
        ),
        invoice_context,
        new_id,
    )
    released = credit.release(  # 5. caused by the payment fact, not by the request (id 57)
        invoice.order_reference,
        CreditReleaseReason.INVOICE_PAID,
        command.correlation_id,
        CreditContext(occurred_at=invoice_context.occurred_at, causation_id=fact.event_id),
        new_id,
    )
    if released is None:
        raise CreditNotOutstandingError(invoice.order_reference)
    await tx.invoices.mark_paid(  # 6. outbox row 1: payment.received.v1
        invoice,
        PaymentSnapshot(
            id=new_id(),
            payment_reference=command.payment_reference,
            invoice_id=invoice.id,
            amount=command.amount,
            value_date=command.value_date,
            source=command.source,
        ),
    )
    await tx.credits.save(credit)  # 7. outbox row 2: credit.released.v1
    return PaymentRegisterResult(
        outcome=PaymentOutcome.ACCEPTED,
        payment_reference=command.payment_reference,
        invoice_reference=invoice.invoice_reference.value,
        order_reference=invoice.order_reference,
        invoice_status=invoice.status,
        paid_at=invoice.paid_at,
    )


async def register(command: RegisterPaymentCommand, scope: BillingScope) -> PaymentRegisterResult:
    stored = await scope.invoice_reads.find_payment_by_reference(command.payment_reference)
    if stored is not None:  # R48: a repeat is routine; no transaction opens
        owner = await scope.invoice_reads.find_by_id(stored.invoice_id)
        if owner is None:
            raise RuntimeError(f"payment {stored.payment_reference!r} names a missing invoice")
        return _duplicate(command, owner, stored)
    target = await _resolve(command, scope.invoice_reads)
    now = scope.clock.now()  # the ONE clock read
    work = partial(
        _register_work,
        command=command,
        target=target,
        invoice_context=InvoiceContext(occurred_at=now, causation_id=command.request_id),
        new_id=scope.ids.new,
    )
    return await scope.transactions.run(work)
