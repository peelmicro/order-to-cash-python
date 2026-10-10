"""The six handlers, thin (`design.md` 7.1): each takes the scope and delegates to a read or to a
transactional unit. Registered one statement each in `composition.register_handlers`."""

from otc_billing.application import credit_hold, credit_release, invoice_issue, payment_register
from otc_billing.application.messages import (
    CreditPage,
    HoldCreditCommand,
    HoldResult,
    InvoiceIssueResult,
    InvoicePage,
    IssueInvoiceCommand,
    ListCreditQuery,
    ListInvoicesQuery,
    PaymentRegisterResult,
    RegisterPaymentCommand,
    ReleaseCreditCommand,
    ReleaseResult,
)
from otc_billing.application.scope import BillingScope


class HoldCreditHandler:
    def __init__(self, scope: BillingScope) -> None:
        self._scope = scope

    async def handle(self, command: HoldCreditCommand, /) -> HoldResult:
        return await credit_hold.hold(command, self._scope)


class ReleaseCreditHandler:
    def __init__(self, scope: BillingScope) -> None:
        self._scope = scope

    async def handle(self, command: ReleaseCreditCommand, /) -> ReleaseResult:
        return await credit_release.release(command, self._scope)


class ListCreditHandler:
    def __init__(self, scope: BillingScope) -> None:
        self._scope = scope

    async def handle(self, query: ListCreditQuery, /) -> CreditPage:
        return await self._scope.reads.list(
            page=query.page,
            page_size=query.page_size,
            retailer_code=query.retailer_code,
            company_code=query.company_code,
        )


class IssueInvoiceHandler:
    def __init__(self, scope: BillingScope) -> None:
        self._scope = scope

    async def handle(self, command: IssueInvoiceCommand, /) -> InvoiceIssueResult:
        return await invoice_issue.issue(command, self._scope)


class ListInvoicesHandler:
    def __init__(self, scope: BillingScope) -> None:
        self._scope = scope

    async def handle(self, query: ListInvoicesQuery, /) -> InvoicePage:
        # the clock is read ONCE here and handed to the adapter: the cutoff is the supplied `now`
        now = self._scope.clock.now()
        return await self._scope.invoice_reads.list(
            page=query.page,
            page_size=query.page_size,
            status=query.status,
            retailer_code=query.retailer_code,
            company_code=query.company_code,
            order_reference=query.order_reference,
            issued_before_minutes=query.issued_before_minutes,
            now=now,
        )


class RegisterPaymentHandler:
    def __init__(self, scope: BillingScope) -> None:
        self._scope = scope

    async def handle(self, command: RegisterPaymentCommand, /) -> PaymentRegisterResult:
        return await payment_register.register(command, self._scope)
