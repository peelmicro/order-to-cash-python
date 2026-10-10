"""The two `billing.invoice.*` requests and replies on the wire (`design.md` 8.2).

Requests are parsed by the generated models through `from_wire_json` (strict integers, patterns,
`minItems`, `units >= 1`, enums); a request that fails is `InvalidInvoiceRequestError` ->
`VALIDATION_FAILED`, with nothing dispatched. The checks the schema cannot express are made HERE,
at the edge, before `dispatcher.send` (BI2, BI33; #7's `N2`: a refusal inside the transaction, after
the counter lock, is the wrong place):

* `unitPrice >= 0` and `discount >= 0` (the generated `MinorUnits` admits a negative value);
* `discount <= sum(unitPrice x units)` (an invoice total is never negative, B6);
* `orderReference` at most 20 characters (the wire pattern has no maximum, the column is
  `varchar(20)`), every `units` at most `2**31 - 1` (the column is `integer`) and the sum at most
  `2**63 - 1` (the column is `bigint`): values Python's unbounded `int` would carry to the
  database inside the transaction.

Replies are application results mapped to the generated reply models and written by the one
serializer (`to_wire_json`): the issue reply carries `invoiceId` on EVERY outcome, `created` true or
false (BI9); an `issued` view writes `"paidAt":null` and a `paid` one the instant, because
`InvoiceView.paidAt` is declared nullable (BI32). No stdlib JSON dump and no ISO-format call here.
"""

from otc_billing.application.messages import (
    InvoiceIssueResult,
    InvoicePage,
    InvoiceViewData,
    IssueInvoiceCommand,
    IssueLine,
    ListInvoicesQuery,
)
from otc_billing.domain.invoice_state import InvoiceStatus
from otc_billing.presentation.credit_headers import RpcCorrelation
from otc_contracts import from_wire_json, to_wire_json
from otc_contracts.generated import asyncapi
from otc_contracts.wire import WireModel

ORDER_REFERENCE_MAX_LENGTH = 20  # invoices.order_reference is varchar(20)
MAX_UNITS = (1 << 31) - 1  # invoice_items.units is integer
MAX_MINOR_UNITS = (1 << 63) - 1  # invoices.amount is bigint


class InvalidInvoiceRequestError(Exception):
    """The request does not satisfy the wire schema (or a check the schema cannot express)."""


def _parse[M: WireModel](model: type[M], body: bytes, subject: str) -> M:
    try:
        return from_wire_json(model, body)
    except ValueError as error:  # pydantic's ValidationError and JSONDecodeError are ValueErrors
        raise InvalidInvoiceRequestError(f"{subject} request is invalid: {error}") from None


# ------------------------------------------------------------------------------------ requests


def decode_issue(body: bytes, correlation: RpcCorrelation) -> IssueInvoiceCommand:
    request = _parse(asyncapi.InvoiceIssueRequestPayload, body, "invoice.issue")
    if len(request.order_reference) > ORDER_REFERENCE_MAX_LENGTH:
        raise InvalidInvoiceRequestError(
            f"orderReference is longer than {ORDER_REFERENCE_MAX_LENGTH} characters"
        )
    for index, line in enumerate(request.lines):
        if line.units > MAX_UNITS:
            raise InvalidInvoiceRequestError(
                f"lines[{index}].units is above {MAX_UNITS} (the column is a 32-bit integer)"
            )
        if line.unit_price < 0:
            raise InvalidInvoiceRequestError(f"lines[{index}].unitPrice must not be negative")
    discount = 0 if request.discount is None else request.discount
    if discount < 0:
        raise InvalidInvoiceRequestError("discount must not be negative")
    gross = sum(line.unit_price * line.units for line in request.lines)
    if gross > MAX_MINOR_UNITS:
        raise InvalidInvoiceRequestError(
            f"the sum of unitPrice x units is above {MAX_MINOR_UNITS} (a 64-bit column)"
        )
    if discount > gross:
        raise InvalidInvoiceRequestError(
            "discount exceeds the sum of unitPrice x units: the total would be negative"
        )
    return IssueInvoiceCommand(
        order_reference=request.order_reference,
        retailer_code=request.retailer_code,
        company_code=request.company_code,
        currency=request.currency,
        lines=tuple(
            IssueLine(product_code=line.product_code, units=line.units, unit_price=line.unit_price)
            for line in request.lines
        ),
        discount=discount,
        correlation_id=correlation.correlation_id,
        request_id=correlation.request_id,
    )


def decode_list(body: bytes) -> ListInvoicesQuery:
    request = _parse(asyncapi.InvoiceListRequestPayload, body, "invoice.list")
    return ListInvoicesQuery(
        page=1 if request.page is None else request.page,
        page_size=25 if request.page_size is None else request.page_size,
        status=None if request.status is None else InvoiceStatus(request.status.value),
        retailer_code=request.retailer_code,
        company_code=request.company_code,
        order_reference=request.order_reference,
        issued_before_minutes=request.issued_before_minutes,
    )


# -------------------------------------------------------------------------------------- replies


def issue_reply(result: InvoiceIssueResult) -> asyncapi.InvoiceIssueReplyPayload:
    invoice = result.invoice
    return asyncapi.InvoiceIssueReplyPayload(
        order_reference=invoice.order_reference,
        invoice_id=invoice.invoice_id.value,
        invoice_reference=invoice.invoice_reference,
        invoice_date=invoice.invoice_date,
        currency=invoice.currency,
        total_amount=invoice.total_amount,
        status=asyncapi.InvoiceStatus(invoice.status.value),
        created=result.created,
    )


def _view(view: InvoiceViewData) -> asyncapi.InvoiceView:
    return asyncapi.InvoiceView(
        invoice_id=view.invoice_id.value,
        invoice_reference=view.invoice_reference,
        invoice_date=view.invoice_date,
        order_reference=view.order_reference,
        retailer_code=view.retailer_code,
        company_code=view.company_code,
        currency=view.currency,
        amount=view.amount,
        discount=view.discount,
        total_amount=view.total_amount,
        status=asyncapi.InvoiceStatus(view.status.value),
        paid_at=view.paid_at,
    )


def list_reply(result: InvoicePage) -> asyncapi.InvoiceListReplyPayload:
    return asyncapi.InvoiceListReplyPayload(
        items=[_view(v) for v in result.items],
        page=asyncapi.PageInfo(page=result.page, page_size=result.page_size, total=result.total),
    )


def encode(model: WireModel) -> bytes:
    return to_wire_json(model).encode("utf-8")
