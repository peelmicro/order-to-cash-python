"""`GET /invoices`, `POST /invoices/{id}/payments`, `GET /credits` (tag `billing`)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from otc_contracts.generated import openapi
from otc_gateway.application.messages import (
    ListCreditsQuery,
    ListInvoicesQuery,
    RegisterInvoicePaymentCommand,
)
from otc_gateway.presentation import contract
from otc_gateway.presentation.dependencies import Runtime
from otc_gateway.presentation.wire import RegisterPaymentBody, wire_response

router = APIRouter(tags=["billing"])

PartyCodeQuery = Annotated[str | None, Query(min_length=1, max_length=20)]


@router.get(
    "/invoices",
    operation_id="listInvoices",
    summary="List invoices.",
    response_model=openapi.InvoicePage,
    responses={**contract.UNAUTHORIZED, **contract.UPSTREAM_UNAVAILABLE},
)
async def list_invoices(
    runtime: Runtime,
    status: openapi.InvoiceStatus | None = None,
    retailer_code: Annotated[PartyCodeQuery, Query(alias="retailerCode")] = None,
    company_code: Annotated[PartyCodeQuery, Query(alias="companyCode")] = None,
    order_reference: Annotated[
        str | None, Query(alias="orderReference", pattern=r"^ORD-[0-9]{6,}$")
    ] = None,
    issued_before_minutes: Annotated[int | None, Query(alias="issuedBeforeMinutes", ge=0)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
) -> Response:
    invoices = await runtime.dispatcher.ask(
        ListInvoicesQuery(
            page=page,
            page_size=page_size,
            status=None if status is None else status.value,
            retailer_code=retailer_code,
            company_code=company_code,
            order_reference=order_reference,
            issued_before_minutes=issued_before_minutes,
        ),
        runtime.scope,
    )
    return wire_response(invoices)


@router.post(
    "/invoices/{id}/payments",
    operation_id="registerPayment",
    summary="Register a remittance against an invoice.",
    status_code=201,
    response_model=openapi.RegisterPaymentResponse,
    responses={
        **contract.declared(200, openapi.RegisterPaymentResponse, "Idempotent replay."),
        **contract.BAD_REQUEST,
        **contract.UNAUTHORIZED,
        **contract.NOT_FOUND,
        **contract.declared(
            409, openapi.Problem, "Already paid under another reference, or the reference reused."
        ),
        **contract.declared(
            422, openapi.Problem, "The amount or currency does not equal the invoice total."
        ),
        **contract.UPSTREAM_UNAVAILABLE,
    },
)
async def register_payment(id: UUID, body: RegisterPaymentBody, runtime: Runtime) -> Response:
    registered = await runtime.dispatcher.send(
        RegisterInvoicePaymentCommand(invoice_id=id, request=body), runtime.scope
    )
    # `openapi.yaml` registerPayment: 201 = this call changed the world, 200 = the original outcome
    # replayed (`Idempotent-Replay: true`); the correlation is the invoice's ORDER id.
    if registered.response.outcome is openapi.Outcome.duplicate:
        return wire_response(registered.response, 200, {"Idempotent-Replay": "true"})
    return wire_response(registered.response, 201, {"X-Correlation-Id": str(registered.order_id)})


@router.get(
    "/credits",
    operation_id="listCredits",
    summary="Credit limits and current exposure per retailer.",
    response_model=openapi.CreditPage,
    responses={**contract.UNAUTHORIZED, **contract.UPSTREAM_UNAVAILABLE},
)
async def list_credits(
    runtime: Runtime,
    retailer_code: Annotated[PartyCodeQuery, Query(alias="retailerCode")] = None,
    company_code: Annotated[PartyCodeQuery, Query(alias="companyCode")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
) -> Response:
    credits_page = await runtime.dispatcher.ask(
        ListCreditsQuery(
            page=page, page_size=page_size, retailer_code=retailer_code, company_code=company_code
        ),
        runtime.scope,
    )
    return wire_response(credits_page)
