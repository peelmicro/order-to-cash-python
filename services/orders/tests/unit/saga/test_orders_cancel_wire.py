# ruff: noqa: E501 - test names are sentences naming the case
"""`orders.cancel` on the wire, with no broker and no database (feature 41).

The request is the wire contract's `OrdersCancelRequestPayload`; the reply is
`OrdersCancelReplyPayload`; both key sets are compared with `asyncapi.yaml`'s own schema, never with
a list typed here (#8 D2). The route is driven through the BUILT dispatcher and the responder's task,
so a missing registration, route or error mapping fails here, not on the first real message.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from otc_contracts import from_wire_json
from otc_contracts.generated.asyncapi import (
    Code,
    CreditReleaseReplyPayload,
    CreditReleaseRequestPayload,
    OrdersCancelReplyPayload,
    OrdersCancelRequestPayload,
    RpcError,
    StockReleaseRequestPayload,
)
from otc_orders.application.commands.cancel_order import (
    CancelOrderCommand,
    CancelOrderResult,
    CompensationPlanned,
    OrderNotFoundError,
)
from otc_orders.application.scope import OrdersScope
from otc_orders.composition import build_dispatcher
from otc_orders.domain.errors import OrderNotCancellableError
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.presentation import orders_cancel as wire
from otc_orders.presentation.orders_create import map_error
from otc_orders.presentation.orders_create_responder import ROUTES, OrdersCreateResponder
from otc_shared_kernel import OrderNumber, UniqueId

NOW = datetime(2026, 10, 12, 9, 0, 0, 123000, tzinfo=UTC)
ORDER_ID = uuid.UUID("00000000-0000-4000-8000-0000000000d1")
ASYNCAPI = Path(__file__).resolve().parents[5] / "specs" / "shared" / "asyncapi.yaml"


def schema(name: str) -> tuple[set[str], set[str]]:
    document: dict[str, Any] = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    component = document["components"]["schemas"][name]
    return set(component["properties"]), set(component.get("required", []))


def body(**fields: Any) -> bytes:
    return json.dumps({"orderId": str(ORDER_ID), "reason": "operator_cancelled"} | fields).encode()


# ------------------------------------------------------------------------- the request, decoded


def test_a_request_with_a_note_becomes_the_command_carrying_that_note_verbatim() -> None:
    command = wire.to_command(wire.decode_request(body(note="$set — café")))

    assert command == CancelOrderCommand(order_id=UniqueId(ORDER_ID), note="$set — café")


def test_a_request_without_a_note_becomes_the_command_with_none() -> None:
    assert wire.to_command(wire.decode_request(body())).note is None


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"[]",
        b"{}",
        b'{"reason":"operator_cancelled"}',
        b'{"orderId":"00000000-0000-0000-0000-000000000000","reason":"operator_cancelled"}',
        b'{"orderId":"nope","reason":"operator_cancelled"}',
        b'{"orderId":"00000000-0000-4000-8000-0000000000d1","reason":"credit_rejected"}',
        b'{"orderId":"00000000-0000-4000-8000-0000000000d1","reason":"stock_rejected"}',
        b'{"orderId":"00000000-0000-4000-8000-0000000000d1"}',
        b'{"orderId":"00000000-0000-4000-8000-0000000000d1","reason":"operator_cancelled","note":1}',
        b'{"orderReference":"ORD-000101","reason":"operator_cancelled"}',
        b'{"orderReference":"101","orderId":"00000000-0000-4000-8000-0000000000d1","reason":"operator_cancelled"}',
    ],
)
def test_a_request_the_schema_or_the_responder_refuses_is_invalid(raw: bytes) -> None:
    with pytest.raises(wire.InvalidOrdersCancelRequestError):
        wire.decode_request(raw)


# --------------------------------------------------------------------------- the reply, encoded

RESULT = CancelOrderResult(
    order_id=UniqueId(ORDER_ID),
    order_reference=OrderNumber("ORD-000007"),
    status=OrderStatus.CONFIRMED,
    cancellation_reason=None,
    compensation_planned=(CompensationPlanned.STOCK_RELEASE, CompensationPlanned.CREDIT_RELEASE),
)


def test_a_compensating_reply_names_the_plan_in_release_order_and_omits_the_reason() -> None:
    document = json.loads(wire.encode(wire.to_reply(RESULT)))

    assert document == {
        "orderId": str(ORDER_ID),
        "orderReference": "ORD-000007",
        "status": "confirmed",
        "compensationPlanned": ["stock_release", "credit_release"],
    }


def test_an_immediate_reply_carries_the_reason_and_an_empty_plan_not_an_absent_one() -> None:
    result = CancelOrderResult(
        order_id=UniqueId(ORDER_ID),
        order_reference=OrderNumber("ORD-000007"),
        status=OrderStatus.CANCELLED,
        cancellation_reason=CancellationReason.OPERATOR_CANCELLED,
        compensation_planned=(),
    )

    document = json.loads(wire.encode(wire.to_reply(result)))

    assert document["cancellationReason"] == "operator_cancelled"
    assert document["compensationPlanned"] == []


def test_the_reply_is_compact_json() -> None:
    assert wire.encode(wire.to_reply(RESULT)) == (
        b'{"orderId":"00000000-0000-4000-8000-0000000000d1","orderReference":"ORD-000007",'
        b'"status":"confirmed","compensationPlanned":["stock_release","credit_release"]}'
    )


def test_the_reply_models_fields_are_exactly_the_schemas_properties_and_the_requireds_are_required() -> (
    None
):
    """Both ways, from the spec: no declared property is missing from the model and the model has no
    property the spec does not declare (a retyped list would drift with the code, not the spec)."""
    for model, name in (
        (OrdersCancelReplyPayload, "OrdersCancelReplyPayload"),
        (OrdersCancelRequestPayload, "OrdersCancelRequestPayload"),
        (StockReleaseRequestPayload, "StockReleaseRequestPayload"),
        (CreditReleaseRequestPayload, "CreditReleaseRequestPayload"),
        (CreditReleaseReplyPayload, "CreditReleaseReplyPayload"),
    ):
        properties, required = schema(name)
        aliases = {field.alias or key for key, field in model.model_fields.items()}
        assert aliases == properties, f"{name}: model and spec disagree on the properties"
        assert {
            field.alias or key for key, field in model.model_fields.items() if field.is_required()
        } == required, f"{name}: model and spec disagree on the required properties"


# ------------------------------------------------------------------------ the error mapping

OCCURRED = NOW


def test_an_order_that_cannot_be_cancelled_maps_to_order_not_cancellable_with_its_status() -> None:
    error = map_error(OrderNotCancellableError("despatched"), OCCURRED)

    assert error.code is Code.order_not_cancellable
    assert error.details == {"code": "order.not_cancellable", "status": "despatched"}
    assert "despatched" in error.message


def test_an_unknown_order_maps_to_not_found_naming_field_and_value() -> None:
    error = map_error(OrderNotFoundError(UniqueId(ORDER_ID)), OCCURRED)

    assert error.code is Code.not_found
    assert error.details == {"field": "orderId", "value": str(ORDER_ID)}


def test_a_malformed_request_maps_to_validation_failed() -> None:
    error = map_error(
        wire.InvalidOrdersCancelRequestError("orders.cancel request is invalid"), OCCURRED
    )

    assert error.code is Code.validation_failed


def test_an_unclassified_failure_is_an_internal_error_that_carries_no_internal_text() -> None:
    error = map_error(RuntimeError("password=hunter2 at /etc/secret"), OCCURRED)

    assert error.code is Code.internal_error
    assert "hunter2" not in error.message


# ----------------------------------------------------------------------------- the route


class FakeMessage:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.reply = "_INBOX.x"
        self.headers: dict[str, str] | None = None  # nats-py's `Msg.headers` is always an attribute
        self.replies: list[bytes] = []
        self.answered = asyncio.Event()

    async def respond(self, data: bytes) -> None:
        self.replies.append(data)
        self.answered.set()


class FakeSubscription:
    async def unsubscribe(self) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.callbacks: dict[str, Any] = {}

    async def subscribe(self, subject: str, queue: str, cb: Any) -> FakeSubscription:
        self.callbacks[subject] = cb
        return FakeSubscription()

    async def flush(self) -> None:
        return None


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeOrders:
    def __init__(self, order: Order | None) -> None:
        self._order = order

    async def get_by_id_for_update(self, order_id: UniqueId) -> Order | None:
        return self._order

    async def save(self, order: Order) -> None:
        return None


class FakeUnitOfWork:
    def __init__(self, order: Order | None) -> None:
        self._order = order

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[Any]:
        class Transaction:
            orders = FakeOrders(self._order)

        yield Transaction()


class NoSignal:
    def signal(self, ref: Any) -> None:
        return None


async def serve(raw: bytes, order: Order | None) -> dict[str, Any]:
    connection = FakeConnection()
    dispatcher = build_dispatcher()

    def scope() -> OrdersScope:
        return OrdersScope(
            unit_of_work=cast("Any", FakeUnitOfWork(order)),
            catalog=cast("Any", object()),
            stock=cast("Any", object()),
            clock=FakeClock(),
            dispatcher=dispatcher,
            saga_signal=NoSignal(),
        )

    responder = OrdersCreateResponder(
        connection=cast("Any", connection),
        dispatcher=dispatcher,
        scope_factory=scope,
        clock=FakeClock(),
    )
    await responder.start()
    stop = asyncio.Event()
    task = asyncio.create_task(responder.run(stop))
    message = FakeMessage(raw)
    await connection.callbacks["orders.cancel"](message)
    async with asyncio.timeout(5):
        await message.answered.wait()
    stop.set()
    await task
    [reply] = message.replies
    document: dict[str, Any] = json.loads(reply)
    return document


def test_orders_cancel_is_a_route_of_the_one_responder() -> None:
    assert "orders.cancel" in ROUTES


async def test_the_responder_answers_a_placed_order_cancelled_through_the_built_dispatcher(
    order_in: Callable[..., Order],
) -> None:
    order = order_in(OrderStatus.PLACED, order_id=UniqueId(ORDER_ID))

    document = await serve(body(note="n"), order)

    reply = from_wire_json(OrdersCancelReplyPayload, json.dumps(document))
    assert reply.status.value == "cancelled"
    assert reply.compensation_planned == []


async def test_the_responder_answers_a_terminal_order_with_an_rpc_error_not_a_reply(
    order_in: Callable[..., Order],
) -> None:
    order = order_in(OrderStatus.DESPATCHED, order_id=UniqueId(ORDER_ID))

    document = await serve(body(), order)

    error = from_wire_json(RpcError, json.dumps(document))
    assert error.code is Code.order_not_cancellable


async def test_the_responder_answers_an_unknown_order_not_found() -> None:
    document = await serve(body(), None)

    assert document["code"] == "NOT_FOUND"


async def test_the_responder_answers_a_malformed_request_validation_failed() -> None:
    document = await serve(b'{"orderId":"nope"}', None)

    assert document["code"] == "VALIDATION_FAILED"
