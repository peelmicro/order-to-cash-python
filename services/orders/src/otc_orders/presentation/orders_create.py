"""`orders.create` on the wire: request validation, the command, the reply, the RPC error mapping.

Request validation is the wire contract's: `OrdersCreateRequestPayload` (generated from
`asyncapi.yaml`) requires `retailerCode`, `companyCode` (1..20 chars), `currency` (`^[A-Z]{3}$`) and
a non-empty `lines`, each line a `productCode` (1..30) and an integer `quantity >= 1`, all parsed
strictly (a `2.0` or `"2"` quantity is refused). On top of the model, a whitespace-only code is
refused too (a blank is not a code). A request that fails either is
`InvalidOrdersCreateRequestError` -> `VALIDATION_FAILED`, never a reference-data `NOT_FOUND` and
never an `INTERNAL_ERROR`.

The error mapping is `orders_aggregate/design.md` 9.2 (#8) and #7's: `VALIDATION_FAILED` with the
domain `code` under `details.code` (the key is `code`), `NOT_FOUND` with
`details: {field, value}`, `UNAVAILABLE` / `TIMEOUT` with the subject in `details`, the responder's
own code passed through when it is one of the wire enum's twelve (else `UNAVAILABLE` carrying it as
`details.responderCode`).
`INTERNAL_ERROR` never carries the exception's text (it can hold SQL or a path); it is logged.

`map_error` is the mapping of the service's ONE responder, so it also maps the refusal of a
`catalog.reference.list` request (`InvalidCatalogReferenceListRequestError` -> `VALIDATION_FAILED`,
feature 40) and the refusals of `orders.cancel` (feature 41): a malformed request ->
`VALIDATION_FAILED`, an unknown order -> `NOT_FOUND`, an order that cannot be cancelled
(`despatched` onwards, or already `cancelled`) -> `ORDER_NOT_CANCELLABLE` with the order's status, a
domain refusal and not a transport failure.
"""

from datetime import datetime

from pydantic import ValidationError

from otc_contracts import from_wire_json, to_wire_json
from otc_contracts.generated.asyncapi import (
    Code,
    OrdersCreateReplyPayload,
    OrdersCreateRequestPayload,
    RpcError,
    Shortage,
)
from otc_orders.application.commands.cancel_order import OrderNotFoundError
from otc_orders.application.commands.place_order import (
    PlaceOrderCommand,
    PlaceOrderError,
    PlaceOrderLine,
    PlaceOrderResult,
    ReferenceDataNotFoundError,
    StockUnavailableError,
)
from otc_orders.application.ports.stock_availability import (
    StockCheckBusinessError,
    StockCheckError,
    StockCheckTimeoutError,
    StockCheckTransportError,
)
from otc_orders.domain.errors import OrderNotCancellableError
from otc_orders.presentation.catalog_reference_list import InvalidCatalogReferenceListRequestError
from otc_orders.presentation.orders_cancel import InvalidOrdersCancelRequestError
from otc_shared_kernel import DomainError, Quantity


class InvalidOrdersCreateRequestError(Exception):
    """The request does not satisfy the wire schema."""


def decode_request(body: bytes) -> OrdersCreateRequestPayload:
    """Parse and validate; raises `InvalidOrdersCreateRequestError` naming the offending fields."""
    try:
        request = from_wire_json(OrdersCreateRequestPayload, body)
    except ValidationError as error:
        fields = ", ".join(
            dict.fromkeys(
                ".".join(str(part) for part in e["loc"]) or "(body)" for e in error.errors()
            )
        )
        raise InvalidOrdersCreateRequestError(
            f"orders.create request is invalid: {fields}."
        ) from None
    blank = [
        name
        for name, value in (
            ("retailerCode", request.retailer_code),
            ("companyCode", request.company_code),
            *(
                (f"lines.{i}.productCode", line.product_code)
                for i, line in enumerate(request.lines)
            ),
        )
        if not value.strip()
    ]
    if blank:
        raise InvalidOrdersCreateRequestError(
            f"orders.create request is invalid: blank {', '.join(blank)}."
        )
    return request


def to_command(request: OrdersCreateRequestPayload) -> PlaceOrderCommand:
    return PlaceOrderCommand(
        request_id=request.request_id,
        retailer_code=request.retailer_code,
        company_code=request.company_code,
        currency=request.currency,
        lines=tuple(
            PlaceOrderLine(
                product_code=line.product_code,
                quantity=Quantity(line.quantity),
                unit_price=line.unit_price,
                line_discount=line.line_discount,
            )
            for line in request.lines
        ),
        order_discount=request.order_discount,
        notes=request.notes,
    )


def to_reply(result: PlaceOrderResult) -> OrdersCreateReplyPayload:
    """Each money field from its own source: the three amounts are different values."""
    return OrdersCreateReplyPayload(
        order_id=result.order_id.value,
        order_reference=result.order_reference.value,
        status="placed",
        currency=result.currency,
        initial_amount=result.initial_amount.amount,
        initial_discount=result.initial_discount.amount,
        total_amount=result.total_amount.amount,
        order_date=result.order_date,
    )


_WIRE_CODES = frozenset(code.value for code in Code)


def map_error(error: Exception, occurred_at: datetime) -> RpcError:
    """The `RpcError` for a failure of the `orders.create` path. Order matters: the specific
    refusals come before the general ones they are subclasses of."""
    match error:
        case (
            InvalidOrdersCreateRequestError()
            | InvalidCatalogReferenceListRequestError()
            | InvalidOrdersCancelRequestError()
        ):
            return RpcError(
                code=Code.validation_failed, message=str(error), occurred_at=occurred_at
            )
        case OrderNotFoundError():
            return RpcError(
                code=Code.not_found,
                message=str(error),
                details={"field": "orderId", "value": str(error.order_id.value)},
                occurred_at=occurred_at,
            )
        case OrderNotCancellableError():  # before DomainError, which it is a subclass of
            return RpcError(
                code=Code.order_not_cancellable,
                message=error.message,
                details={"code": error.code, "status": error.source},
                occurred_at=occurred_at,
            )
        case StockUnavailableError():
            return RpcError(
                code=Code.stock_unavailable,
                message=str(error),
                details={
                    "shortages": [
                        Shortage(
                            product_code=s.product_code,
                            requested=s.requested,
                            available=s.available,
                        ).model_dump(mode="json")
                        for s in error.shortages
                    ]
                },
                occurred_at=occurred_at,
            )
        case StockCheckTimeoutError():
            return RpcError(
                code=Code.timeout,
                message=str(error),
                details={"subject": error.subject, "timeoutMs": error.timeout_ms},
                occurred_at=occurred_at,
            )
        case StockCheckTransportError():
            return RpcError(
                code=Code.unavailable,
                message=str(error),
                details={"subject": error.subject},
                occurred_at=occurred_at,
            )
        case StockCheckBusinessError():
            details: dict[str, object] = {"subject": error.subject}
            code = error.rpc_error_code
            if code not in _WIRE_CODES:
                details["responderCode"] = code
                code = Code.unavailable
            return RpcError(
                code=Code(code),
                message=error.responder_message,
                details=details,
                occurred_at=occurred_at,
            )
        case StockCheckError():  # an unclassified failure of the stock check is still the transport
            return RpcError(
                code=Code.unavailable,
                message=str(error),
                details={"subject": error.subject},
                occurred_at=occurred_at,
            )
        case ReferenceDataNotFoundError():
            return RpcError(
                code=Code.not_found,
                message=str(error),
                details={"field": error.field, "value": error.value},
                occurred_at=occurred_at,
            )
        case PlaceOrderError():  # an order discount, the only other one today
            return RpcError(
                code=Code.validation_failed, message=str(error), occurred_at=occurred_at
            )
        case DomainError():
            return RpcError(
                code=Code.validation_failed,
                message=error.message,
                details={"code": error.code},
                occurred_at=occurred_at,
            )
        case _:
            return RpcError(
                code=Code.internal_error,
                message="The request could not be processed.",
                occurred_at=occurred_at,
            )


def encode(model: RpcError | OrdersCreateReplyPayload) -> bytes:
    return to_wire_json(model).encode("utf-8")
