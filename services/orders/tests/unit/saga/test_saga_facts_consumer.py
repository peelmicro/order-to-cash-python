# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""`SagaFactsConsumerTask.handle`: the routing of `design.md` 5.5 (SO2, L23), against a recorder.

The dispatcher is a recorder and the scope factory is a spy: a fact that must cause no transaction
and no store access is proven by the scope factory never being called (the scope is what carries the
unit of work).
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any, cast

import pytest

from otc_cqrs import Dispatcher
from otc_orders.application.ports.fact_stream import FactMessage
from otc_orders.application.saga.fact_commands import (
    FACT_COMMANDS,
    HandleCreditApprovedFactCommand,
    HandleCreditRejectedFactCommand,
    HandleCreditReleasedFactCommand,
    HandleInvoiceIssuedFactCommand,
    HandleOrderDespatchedFactCommand,
    HandleOrderPlacedFactCommand,
    HandlePaymentReceivedFactCommand,
    HandleStockRejectedFactCommand,
    HandleStockReleasedFactCommand,
    HandleStockReservedFactCommand,
)
from otc_orders.application.scope import OrdersScope
from otc_orders.presentation.saga_facts_consumer import SagaFactsConsumerTask

TOPIC = "otc.fulfillment.facts.v1"

EXPECTED_COMMANDS = {
    "order.placed.v1": HandleOrderPlacedFactCommand,
    "stock.reserved.v1": HandleStockReservedFactCommand,
    "stock.rejected.v1": HandleStockRejectedFactCommand,
    "stock.released.v1": HandleStockReleasedFactCommand,
    "credit.approved.v1": HandleCreditApprovedFactCommand,
    "credit.rejected.v1": HandleCreditRejectedFactCommand,
    "order.despatched.v1": HandleOrderDespatchedFactCommand,
    "invoice.issued.v1": HandleInvoiceIssuedFactCommand,
    "payment.received.v1": HandlePaymentReceivedFactCommand,
    "credit.released.v1": HandleCreditReleasedFactCommand,
}
SELF_PRODUCED = (
    "order.confirmed.v1",
    "order.completed.v1",
    "order.cancelled.v1",
    "order.saga_failed.v1",
)


class RecordingDispatcher:
    def __init__(self, failure: Exception | None = None) -> None:
        self.sent: list[tuple[object, object]] = []
        self._failure = failure

    async def send(self, command: object, scope: object) -> None:
        self.sent.append((command, scope))
        if self._failure is not None:
            raise self._failure


class ScopeSpy:
    def __init__(self) -> None:
        self.built = 0
        self.scope = cast("OrdersScope", object())

    def __call__(self) -> OrdersScope:
        self.built += 1
        return self.scope


def task_over(dispatcher: RecordingDispatcher, scope: ScopeSpy) -> SagaFactsConsumerTask:
    return SagaFactsConsumerTask(
        subscriber=cast("Any", None),
        dispatcher=cast("Dispatcher[OrdersScope]", dispatcher),
        scope_factory=scope,
    )


def message(value: bytes) -> FactMessage:
    return FactMessage(topic=TOPIC, partition=2, offset=41, key=b"k", value=value, headers=())


def test_the_fact_command_map_is_the_literal_ten() -> None:
    assert dict(FACT_COMMANDS) == EXPECTED_COMMANDS


@pytest.mark.parametrize(("event_type", "command_type"), sorted(EXPECTED_COMMANDS.items()))
async def test_each_consumed_fact_reaches_its_own_handle_fact_command(
    event_type: str, command_type: type, envelope_bytes: Callable[..., bytes]
) -> None:
    dispatcher, scope = RecordingDispatcher(), ScopeSpy()

    await task_over(dispatcher, scope).handle(message(envelope_bytes(event_type)))

    [(command, used_scope)] = dispatcher.sent
    assert type(command) is command_type, f"{event_type} was routed to {type(command).__name__}"
    assert used_scope is scope.scope
    assert command.envelope.event_type == event_type  # type: ignore[attr-defined]
    assert command.topic == TOPIC  # type: ignore[attr-defined]


@pytest.mark.parametrize("event_type", SELF_PRODUCED)
async def test_so2_a_self_produced_fact_is_acknowledged_with_no_dispatch_no_transaction_and_no_store_access(
    event_type: str, envelope_bytes: Callable[..., bytes], caplog: pytest.LogCaptureFixture
) -> None:
    dispatcher, scope = RecordingDispatcher(), ScopeSpy()

    with caplog.at_level(logging.DEBUG):
        await task_over(dispatcher, scope).handle(message(envelope_bytes(event_type)))

    assert dispatcher.sent == []
    assert scope.built == 0, "no scope was built, so no unit of work, no repository, no dedup row"
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def without(raw: bytes, key: str) -> bytes:
    document = json.loads(raw)
    del document[key]
    return json.dumps(document).encode()


@pytest.mark.parametrize(
    "shape",
    ["not json", "a json array", "a missing correlationId", "a non-uuid eventId", "an empty value"],
)
async def test_a_malformed_envelope_is_logged_and_acknowledged_and_an_unknown_event_type_is_warned_and_acknowledged(
    shape: str, envelope_bytes: Callable[..., bytes], caplog: pytest.LogCaptureFixture
) -> None:
    good = envelope_bytes("stock.reserved.v1")
    value = {
        "not json": b"{ this is not json",
        "a json array": b'[{"eventId":"x"}]',
        "a missing correlationId": without(good, "correlationId"),
        "a non-uuid eventId": envelope_bytes("stock.reserved.v1", eventId="not-a-uuid"),
        "an empty value": b"",
    }[shape]
    dispatcher, scope = RecordingDispatcher(), ScopeSpy()

    with caplog.at_level(logging.DEBUG):
        await task_over(dispatcher, scope).handle(message(value))  # returns normally

    assert dispatcher.sent == []
    assert scope.built == 0
    [record] = [r for r in caplog.records if r.name.endswith("saga_facts_consumer")]
    assert record.levelno == logging.ERROR, shape
    assert (record.topic, record.partition, record.offset) == (TOPIC, 2, 41)  # type: ignore[attr-defined]
    assert record.length == len(value)  # type: ignore[attr-defined]


async def test_an_unknown_event_type_is_warned_distinctly_from_a_malformed_envelope(
    envelope_bytes: Callable[..., bytes], caplog: pytest.LogCaptureFixture
) -> None:
    value = envelope_bytes("stock.reserved.v1", eventType="warehouse.moved.v7")
    dispatcher, scope = RecordingDispatcher(), ScopeSpy()

    with caplog.at_level(logging.DEBUG):
        await task_over(dispatcher, scope).handle(message(value))

    assert dispatcher.sent == []
    assert scope.built == 0
    [record] = [r for r in caplog.records if r.name.endswith("saga_facts_consumer")]
    assert record.levelno == logging.WARNING
    assert record.eventType == "warehouse.moved.v7"  # type: ignore[attr-defined]
    assert (record.topic, record.partition, record.offset) == (TOPIC, 2, 41)  # type: ignore[attr-defined]


async def test_a_processing_failure_propagates_so_the_offset_is_not_committed(
    envelope_bytes: Callable[..., bytes],
) -> None:
    dispatcher = RecordingDispatcher(failure=RuntimeError("the unit of work failed"))

    with pytest.raises(RuntimeError, match="the unit of work failed"):
        await task_over(dispatcher, ScopeSpy()).handle(message(envelope_bytes("stock.reserved.v1")))

    assert len(dispatcher.sent) == 1


async def test_a_well_formed_envelope_with_a_poisoned_payload_is_dispatched_not_acknowledged(
    envelope_bytes: Callable[..., bytes],
) -> None:
    # The payload is validated INSIDE the processing unit (the command handler), so this layer must
    # hand it over: validating here would turn a retryable poison into a silent acknowledgement.
    value = envelope_bytes("stock.reserved.v1", payload={"unexpected": 1})
    dispatcher = RecordingDispatcher()

    await task_over(dispatcher, ScopeSpy()).handle(message(value))

    [(command, _)] = dispatcher.sent
    assert type(command) is HandleStockReservedFactCommand


async def test_run_hands_the_subscriber_the_handler_and_the_stop_event() -> None:
    received: list[tuple[object, asyncio.Event]] = []

    class Subscriber:
        async def run(self, handler: object, stop: asyncio.Event) -> None:
            received.append((handler, stop))

    task = SagaFactsConsumerTask(
        subscriber=Subscriber(),
        dispatcher=cast("Dispatcher[OrdersScope]", RecordingDispatcher()),
        scope_factory=ScopeSpy(),
    )
    stop = asyncio.Event()

    await task.run(stop)

    assert received == [(task.handle, stop)]
