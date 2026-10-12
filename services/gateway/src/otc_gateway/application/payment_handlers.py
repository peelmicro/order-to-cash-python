"""`POST /invoices/{id}/payments` -> `billing.payment.register` (R47 - R49).

The path carries the INVOICE id, but Billing keys `payment.received.v1`, `credit.released.v1` and
the timeline by `correlationId = order id` and refuses a request with no `x-correlation-id`
(`BC1`). So the order id is resolved BEFORE the call:

1. `billing.invoice.list` is scanned for the invoice id (the contract has no get-by-id query and the
   list cannot be filtered by it), a bounded number of pages: found -> its `orderReference`; the end
   of the list -> `InvoiceNotFoundError` (404); the budget used with the last page still full ->
   `InvoiceScanBudgetExceededError` (503, never a false 404);
2. the read model maps that `orderReference` to the order id (R54: the Gateway's read of it);
   an order the projector has not written yet -> `OrderNotYetProjectedError` (503 + Retry-After),
   never a request under the invoice id or a fresh id.

Ported from #7 (`apps/gateway/src/application/commands/register-payment.command.ts:36-37`, the
scan bounds) and #8 (`src/Gateway/Application/Commands/RegisterInvoicePaymentCommand.cs:70-95`, the
handler; `:97-125`, the scan).
"""

from uuid import UUID

from otc_contracts.generated import asyncapi, openapi
from otc_gateway.application.errors import (
    InvoiceNotFoundError,
    InvoiceScanBudgetExceededError,
    OrderNotYetProjectedError,
)
from otc_gateway.application.messages import PaymentRegistered, RegisterInvoicePaymentCommand
from otc_gateway.application.rpc_subjects import INVOICE_LIST, PAYMENT_REGISTER
from otc_gateway.application.scope import GatewayScope
from otc_shared_kernel import UniqueId

SCAN_PAGE_SIZE = 200  # the contract's maximum `pageSize`
SCAN_MAX_PAGES = 5


class RegisterPaymentHandler:
    def __init__(self, scope: GatewayScope) -> None:
        self._scope = scope

    async def handle(self, command: RegisterInvoicePaymentCommand, /) -> PaymentRegistered:
        order_reference = await self._order_reference_of(command.invoice_id)
        order_id = await self._scope.read_model.find_order_id_by_reference(order_reference)
        if order_id is None:
            raise OrderNotYetProjectedError(order_reference)
        request = command.request
        payload = asyncapi.PaymentRegisterRequestPayload(
            invoice_id=command.invoice_id,
            payment_reference=request.payment_reference,
            amount=asyncapi.Money(amount=request.amount.amount, currency=request.amount.currency),
            value_date=request.value_date,
            source=asyncapi.PaymentSource(request.source.value),
        )
        reply = await self._scope.rpc.call(
            PAYMENT_REGISTER,
            payload,
            asyncapi.PaymentRegisterReplyPayload,
            correlation_id=order_id,
            request_id=UniqueId.new().value,
        )
        return PaymentRegistered(
            response=openapi.RegisterPaymentResponse(
                outcome=openapi.Outcome(reply.outcome.value),
                payment_reference=reply.payment_reference,
                invoice_reference=reply.invoice_reference,
                order_reference=reply.order_reference,
                invoice_status=openapi.InvoiceStatus(reply.invoice_status.value),
                paid_at=reply.paid_at,
            ),
            order_id=order_id,
        )

    async def _order_reference_of(self, invoice_id: UUID) -> str:
        scanned = 0
        for page in range(1, SCAN_MAX_PAGES + 1):
            request_id = UniqueId.new().value
            reply = await self._scope.rpc.call(
                INVOICE_LIST,
                asyncapi.InvoiceListRequestPayload(page=page, page_size=SCAN_PAGE_SIZE),
                asyncapi.InvoiceListReplyPayload,
                correlation_id=request_id,
                request_id=request_id,
            )
            scanned += len(reply.items)
            for invoice in reply.items:
                if invoice.invoice_id == invoice_id:
                    return invoice.order_reference
            if len(reply.items) < SCAN_PAGE_SIZE:
                raise InvoiceNotFoundError(str(invoice_id))
        raise InvoiceScanBudgetExceededError(str(invoice_id), scanned)
