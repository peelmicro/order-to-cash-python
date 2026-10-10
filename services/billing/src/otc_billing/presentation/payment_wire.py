"""`billing.payment.register` on the wire (`asyncapi.yaml` `PaymentRegisterRequest` / `Reply`).

The request is parsed by the generated model through `from_wire_json` (strict integers, patterns,
`maxLength`, enums); a request that fails is `InvalidPaymentRequestError` -> `VALIDATION_FAILED`,
with nothing dispatched. The checks the schema cannot express are made here: at least one of
`invoiceId` / `invoiceReference` (both are optional in the schema), and `valueDate` cut to the
millisecond with the one `wire_instant` truncation, so the stored `payments.value_date` (a
`timestamptz(3)`, which ROUNDS), the fact's `valueDate` and the request's are the same instant
(OI19).

The reply is an application result mapped to the generated reply model and written by the one
serializer (`to_wire_json`): `outcome` is `accepted` or `duplicate`; a refusal is an `RpcError`
(`credit_rpc_errors.map_error`), never a reply.
"""

from otc_billing.application.messages import PaymentRegisterResult, RegisterPaymentCommand
from otc_billing.domain.invoice_events import PaymentSource
from otc_billing.presentation.credit_headers import RpcCorrelation
from otc_contracts import from_wire_json, to_wire_json, wire_instant
from otc_contracts.generated import asyncapi
from otc_contracts.wire import WireModel
from otc_shared_kernel import Money, UniqueId


class InvalidPaymentRequestError(Exception):
    """The request does not satisfy the wire schema (or a check the schema cannot express)."""


def decode_register(body: bytes, correlation: RpcCorrelation) -> RegisterPaymentCommand:
    try:
        request = from_wire_json(asyncapi.PaymentRegisterRequestPayload, body)
    except ValueError as error:  # pydantic's ValidationError and JSONDecodeError are ValueErrors
        raise InvalidPaymentRequestError(f"payment.register request is invalid: {error}") from None
    if request.invoice_id is None and request.invoice_reference is None:
        raise InvalidPaymentRequestError("one of invoiceId and invoiceReference is required")
    return RegisterPaymentCommand(
        invoice_id=None if request.invoice_id is None else UniqueId(request.invoice_id),
        invoice_reference=request.invoice_reference,
        payment_reference=request.payment_reference,
        amount=Money(request.amount.amount, request.amount.currency),
        value_date=wire_instant(request.value_date),
        source=PaymentSource(request.source.value),
        correlation_id=correlation.correlation_id,
        request_id=correlation.request_id,
    )


def register_reply(result: PaymentRegisterResult) -> asyncapi.PaymentRegisterReplyPayload:
    return asyncapi.PaymentRegisterReplyPayload(
        outcome=asyncapi.Outcome3(result.outcome.value),
        payment_reference=result.payment_reference,
        invoice_reference=result.invoice_reference,
        order_reference=result.order_reference,
        invoice_status=asyncapi.InvoiceStatus(result.invoice_status.value),
        paid_at=result.paid_at,
    )


def encode(model: WireModel) -> bytes:
    return to_wire_json(model).encode("utf-8")
