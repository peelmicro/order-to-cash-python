"""`orders.cancel` on the wire: request validation, the command, the reply (feature 41).

Request validation is the wire contract's: `OrdersCancelRequestPayload` (generated from
`asyncapi.yaml`) requires `reason`, whose only value is `operator_cancelled` (`stock_rejected` and
`credit_rejected` are decided by the saga, never asked for), and may carry `orderId`,
`orderReference` and `note`. `orderId` is REQUIRED here although the schema lists only `reason`: the
Gateway, the only caller, always sends it, and this responder looks the order up by id (#7's
`orders-cancel.dto.ts` and #8's `OrdersCancelRequestValidator.cs` make the same choice). A request
that fails the schema, has no body, or names no (or the nil) `orderId` is
`InvalidOrdersCancelRequestError` -> `VALIDATION_FAILED`, never an `INTERNAL_ERROR`.

The reply is `OrdersCancelReplyPayload`: `cancellationReason` only when the order is already
cancelled (from `placed`), `compensationPlanned` always present, in release order (empty when the
cancellation was immediate). A note beginning with `$` is just text (`PR47`): nothing here
interpolates it.
"""

from pydantic import ValidationError

from otc_contracts import from_wire_json, to_wire_json
from otc_contracts.generated.asyncapi import (
    CancellationReason as WireCancellationReason,
)
from otc_contracts.generated.asyncapi import (
    CompensationPlannedEnum,
    OrdersCancelReplyPayload,
    OrdersCancelRequestPayload,
    RpcError,
)
from otc_contracts.generated.asyncapi import (
    OrderStatus as WireOrderStatus,
)
from otc_orders.application.commands.cancel_order import CancelOrderCommand, CancelOrderResult
from otc_shared_kernel import UniqueId


class InvalidOrdersCancelRequestError(Exception):
    """The request does not satisfy the wire schema."""


def decode_request(body: bytes) -> OrdersCancelRequestPayload:
    """Parse and validate; raises `InvalidOrdersCancelRequestError` naming the offending fields."""
    if not body:
        raise InvalidOrdersCancelRequestError("orders.cancel request carried no payload.")
    try:
        request = from_wire_json(OrdersCancelRequestPayload, body)
    except ValidationError as error:
        fields = ", ".join(
            dict.fromkeys(
                ".".join(str(part) for part in e["loc"]) or "(body)" for e in error.errors()
            )
        )
        raise InvalidOrdersCancelRequestError(
            f"orders.cancel request is invalid: {fields}."
        ) from None
    if request.order_id is None or request.order_id.int == 0:
        raise InvalidOrdersCancelRequestError(
            "orders.cancel request is invalid: orderId is missing or empty."
        )
    return request


def to_command(request: OrdersCancelRequestPayload) -> CancelOrderCommand:
    if request.order_id is None:  # decode_request refused it; the type checker is told so
        raise InvalidOrdersCancelRequestError("orders.cancel request has no orderId.")
    return CancelOrderCommand(order_id=UniqueId(request.order_id), note=request.note)


def to_reply(result: CancelOrderResult) -> OrdersCancelReplyPayload:
    return OrdersCancelReplyPayload(
        order_id=result.order_id.value,
        order_reference=result.order_reference.value,
        status=WireOrderStatus(result.status.value),
        cancellation_reason=(
            None
            if result.cancellation_reason is None
            else WireCancellationReason(result.cancellation_reason.value)
        ),
        compensation_planned=[
            CompensationPlannedEnum(p.value) for p in result.compensation_planned
        ],
    )


def encode(model: RpcError | OrdersCancelReplyPayload) -> bytes:
    return to_wire_json(model).encode("utf-8")
