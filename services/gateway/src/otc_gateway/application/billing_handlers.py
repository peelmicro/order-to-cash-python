"""`GET /invoices` -> `billing.invoice.list`, `GET /credits` -> `billing.credit.list`."""

from otc_contracts.generated import asyncapi, openapi
from otc_gateway.application.messages import ListCreditsQuery, ListInvoicesQuery
from otc_gateway.application.rpc_subjects import CREDIT_LIST, INVOICE_LIST
from otc_gateway.application.scope import GatewayScope
from otc_gateway.application.stock_handlers import page_info
from otc_shared_kernel import UniqueId


class ListInvoicesHandler:
    def __init__(self, scope: GatewayScope) -> None:
        self._scope = scope

    async def handle(self, query: ListInvoicesQuery, /) -> openapi.InvoicePage:
        request_id = UniqueId.new().value
        reply = await self._scope.rpc.call(
            INVOICE_LIST,
            asyncapi.InvoiceListRequestPayload(
                page=query.page,
                page_size=query.page_size,
                status=None if query.status is None else asyncapi.InvoiceStatus(query.status),
                retailer_code=query.retailer_code,
                company_code=query.company_code,
                order_reference=query.order_reference,
                issued_before_minutes=query.issued_before_minutes,
            ),
            asyncapi.InvoiceListReplyPayload,
            correlation_id=request_id,
            request_id=request_id,
        )
        return openapi.InvoicePage(
            items=[
                openapi.Invoice(
                    invoice_id=view.invoice_id,
                    invoice_reference=view.invoice_reference,
                    invoice_date=view.invoice_date,
                    order_reference=view.order_reference,
                    retailer_code=view.retailer_code,
                    company_code=view.company_code,
                    currency=view.currency,
                    amount=view.amount,
                    discount=view.discount,
                    total_amount=view.total_amount,
                    status=openapi.InvoiceStatus(view.status.value),
                    paid_at=view.paid_at,
                )
                for view in reply.items
            ],
            page=page_info(reply.page),
        )


class ListCreditsHandler:
    def __init__(self, scope: GatewayScope) -> None:
        self._scope = scope

    async def handle(self, query: ListCreditsQuery, /) -> openapi.CreditPage:
        request_id = UniqueId.new().value
        reply = await self._scope.rpc.call(
            CREDIT_LIST,
            asyncapi.CreditListRequestPayload(
                page=query.page,
                page_size=query.page_size,
                retailer_code=query.retailer_code,
                company_code=query.company_code,
            ),
            asyncapi.CreditListReplyPayload,
            correlation_id=request_id,
            request_id=request_id,
        )
        return openapi.CreditPage(
            items=[
                openapi.Credit(
                    credit_code=view.credit_code,
                    retailer_code=view.retailer_code,
                    company_code=view.company_code,
                    currency=view.currency,
                    credit_limit=view.credit_limit,
                    active_holds=view.active_holds,
                    open_exposure=view.open_exposure,
                    available_credit=view.available_credit,
                )
                for view in reply.items
            ],
            page=page_info(reply.page),
        )
