"""`POST /orders` -> `orders.create`, `POST /orders/{id}/cancel` -> `orders.cancel`."""

from otc_contracts.generated import asyncapi, openapi
from otc_gateway.application.errors import RpcProtocolError
from otc_gateway.application.messages import CancelOrderCommand, PlaceOrderCommand
from otc_gateway.application.rpc_subjects import ORDERS_CANCEL, ORDERS_CREATE
from otc_gateway.application.scope import GatewayScope
from otc_shared_kernel import UniqueId


class PlaceOrderHandler:
    def __init__(self, scope: GatewayScope) -> None:
        self._scope = scope

    async def handle(self, command: PlaceOrderCommand, /) -> openapi.PlaceOrderResponse:
        request = command.request
        payload = asyncapi.OrdersCreateRequestPayload(
            # `Idempotency-Key` travels as the PAYLOAD's `requestId` (R62), never as the
            # transport's `x-request-id`, which names this attempt and is fresh on every call
            request_id=command.idempotency_key,
            retailer_code=request.retailer_code,
            company_code=request.company_code,
            currency=request.currency,
            lines=[
                asyncapi.Line(
                    product_code=line.product_code,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    line_discount=line.line_discount,
                )
                for line in request.lines
            ],
            order_discount=request.order_discount,
            notes=request.notes,
        )
        # Neither the order nor its id exists yet: a fresh gateway request id is the correlation
        # (`asyncapi.yaml` `RpcHeaders.x-correlation-id`).
        request_id = UniqueId.new().value
        reply = await self._scope.rpc.call(
            ORDERS_CREATE,
            payload,
            asyncapi.OrdersCreateReplyPayload,
            correlation_id=request_id,
            request_id=request_id,
        )
        # R55: an id the caller has just been given is an id this process just handed out
        self._scope.issued_orders.record(reply.order_id)
        return openapi.PlaceOrderResponse(
            order_id=reply.order_id,
            order_reference=reply.order_reference,
            status="placed",
            currency=reply.currency,
            initial_amount=reply.initial_amount,
            initial_discount=reply.initial_discount,
            total_amount=reply.total_amount,
            order_date=reply.order_date,
            projection_pending=True,  # always true at creation: the read model has not seen it
        )


class CancelOrderHandler:
    def __init__(self, scope: GatewayScope) -> None:
        self._scope = scope

    async def handle(self, command: CancelOrderCommand, /) -> openapi.CancelOrderResponse:
        payload = asyncapi.OrdersCancelRequestPayload(
            order_id=command.order_id, reason="operator_cancelled", note=command.note
        )
        reply = await self._scope.rpc.call(
            ORDERS_CANCEL,
            payload,
            asyncapi.OrdersCancelReplyPayload,
            # the order id IS known here: it is the correlationId of every fact of its saga
            correlation_id=command.order_id,
            request_id=UniqueId.new().value,
        )
        reason = reply.cancellation_reason
        if reason is not None and reason.value != "operator_cancelled":
            raise RpcProtocolError(
                ORDERS_CANCEL, f"{ORDERS_CANCEL} answered the cancellation reason {reason.value!r}"
            )
        return openapi.CancelOrderResponse(
            order_id=reply.order_id,
            order_reference=reply.order_reference,
            status=openapi.OrderStatus(reply.status.value),
            cancellation_reason=None if reason is None else "operator_cancelled",
            compensation_planned=[
                openapi.CompensationPlannedEnum(step.value) for step in reply.compensation_planned
            ],
        )
