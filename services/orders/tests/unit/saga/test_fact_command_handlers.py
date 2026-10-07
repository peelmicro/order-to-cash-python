"""`SagaFactCommandHandler` and `build_saga_fact` (task 3.13, 3.14, 6.8; L22, L23, L25, L31).

The step itself is stubbed (`SagaFactHandler.handle` returns a canned result), so these tests are
about what the command handler does AROUND it: building the fact from the envelope, and publishing
the dispatch-owed event only for a processed step that owed a command, after the step returned.
"""

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from otc_contracts import Envelope, from_wire_json
from otc_contracts.generated.asyncapi import StockReservedPayload
from otc_cqrs import Dispatcher
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.dispatch_events import (
    CreditRejectionRecorded,
    OrderConfirmedBySaga,
    OrderMarkedDespatched,
    OrderMarkedStockReserved,
    OrderPlacedFactRecorded,
)
from otc_orders.application.saga.fact import SagaFact
from otc_orders.application.saga.fact_command_handlers import (
    FactPayloadError,
    SagaFactCommandHandler,
    build_saga_fact,
)
from otc_orders.application.saga.fact_commands import (
    FACT_COMMANDS,
    HandleStockReservedFactCommand,
)
from otc_orders.application.saga.fact_handler import (
    SagaFactHandler,
    SagaFactOutcome,
    SagaFactResult,
)
from otc_orders.application.scope import MissingBindingError, OrdersScope
from otc_shared_kernel import InvalidUniqueIdError

EVENT_ID = uuid.UUID("00000000-0000-4000-8000-0000000000e1")
ORDER_ID = uuid.UUID("00000000-0000-4000-8000-0000000000d1")


def command_for(event_type: str, raw: bytes, topic: str = "otc.fulfillment.facts.v1") -> Any:
    envelope = from_wire_json(Envelope[dict[str, Any]], raw)
    return FACT_COMMANDS[event_type](envelope=envelope, topic=topic)


def test_an_offset_instant_with_microseconds_becomes_the_same_utc_millisecond(
    envelope_bytes: Callable[..., bytes],
) -> None:
    raw = envelope_bytes("stock.reserved.v1", occurredAt="2026-10-02T12:15:04.120456+02:00")

    fact = build_saga_fact(command_for("stock.reserved.v1", raw))

    assert fact.occurred_at == datetime(2026, 10, 2, 10, 15, 4, 120000, tzinfo=UTC)
    assert fact.occurred_at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_the_fact_is_built_from_the_envelope_with_its_typed_payload_and_topic(
    envelope_bytes: Callable[..., bytes],
) -> None:
    fact = build_saga_fact(
        command_for("stock.reserved.v1", envelope_bytes("stock.reserved.v1"), topic="t.test")
    )

    assert fact.event_id.value == EVENT_ID
    assert fact.correlation_id.value == ORDER_ID
    assert fact.event_type == "stock.reserved.v1"
    assert fact.topic == "t.test"
    assert isinstance(fact.payload, StockReservedPayload)
    assert fact.payload.order_reference == "ORD-000007"


def test_the_correlation_id_is_compared_as_a_uuid_value(
    envelope_bytes: Callable[..., bytes],
) -> None:
    raw = envelope_bytes("stock.reserved.v1", correlationId=str(ORDER_ID).upper())
    assert json.loads(raw)["correlationId"] != str(ORDER_ID), "the fixture is written in upper case"

    fact = build_saga_fact(command_for("stock.reserved.v1", raw))

    assert fact.correlation_id.value == ORDER_ID


def test_a_poisoned_payload_fails_the_build_so_the_record_is_redelivered(
    envelope_bytes: Callable[..., bytes],
) -> None:
    raw = envelope_bytes("stock.reserved.v1", payload={"orderReference": "ORD-000007"})

    with pytest.raises(ValueError, match="StockReservedEvent"):
        build_saga_fact(command_for("stock.reserved.v1", raw))


def test_a_nil_correlation_id_fails_the_build_it_is_never_silently_acknowledged(
    envelope_bytes: Callable[..., bytes],
) -> None:
    raw = envelope_bytes("stock.reserved.v1", correlationId=str(uuid.UUID(int=0)))

    with pytest.raises(InvalidUniqueIdError):
        build_saga_fact(command_for("stock.reserved.v1", raw))


def test_an_event_type_with_no_model_is_a_payload_error(
    envelope_bytes: Callable[..., bytes],
) -> None:
    command = command_for("stock.reserved.v1", envelope_bytes("stock.reserved.v1"))
    forged = HandleStockReservedFactCommand(
        envelope=command.envelope.model_copy(update={"event_type": "no.such.v1"}),
        topic="t",
    )

    with pytest.raises(FactPayloadError, match=r"no\.such\.v1"):
        build_saga_fact(forged)


class RecordingDispatcher:
    def __init__(self, calls: list[str]) -> None:
        self.published: list[tuple[object, object]] = []
        self._calls = calls

    async def publish(self, event: object, scope: object) -> None:
        self._calls.append("publish")
        self.published.append((event, scope))


def scope_with(
    dispatcher: RecordingDispatcher | None, consumption: object | None = object()
) -> OrdersScope:
    return OrdersScope(
        unit_of_work=cast("Any", object()),
        catalog=cast("Any", object()),
        stock=cast("Any", object()),
        clock=cast("Any", object()),
        dispatcher=cast("Dispatcher[OrdersScope] | None", dispatcher),
        fact_consumption=cast("Any", consumption),
    )


def stub_the_step(
    monkeypatch: pytest.MonkeyPatch, result: SagaFactResult, calls: list[str]
) -> list[SagaFact]:
    seen: list[SagaFact] = []

    async def handle(self: SagaFactHandler, fact: SagaFact) -> SagaFactResult:
        seen.append(fact)
        calls.append("step returned")
        return result

    monkeypatch.setattr(SagaFactHandler, "handle", handle)
    return seen


@pytest.mark.parametrize(
    ("kind", "event_type"),
    [
        (SagaCommandKind.STOCK_RESERVE, OrderPlacedFactRecorded),
        (SagaCommandKind.CREDIT_HOLD, OrderMarkedStockReserved),
        (SagaCommandKind.STOCK_RELEASE, CreditRejectionRecorded),
        (SagaCommandKind.DESPATCH_CREATE, OrderConfirmedBySaga),
        (SagaCommandKind.INVOICE_ISSUE, OrderMarkedDespatched),
    ],
)
async def test_a_dispatch_owed_event_is_published_only_for_a_processed_fact_that_enqueued_a_command(
    kind: SagaCommandKind,
    event_type: type,
    envelope_bytes: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    dispatcher = RecordingDispatcher(calls)
    stub_the_step(monkeypatch, SagaFactResult(SagaFactOutcome.PROCESSED, kind), calls)
    scope = scope_with(dispatcher)
    command = command_for("stock.reserved.v1", envelope_bytes("stock.reserved.v1"))

    result = await SagaFactCommandHandler(scope).handle(command)

    assert result == SagaFactResult(SagaFactOutcome.PROCESSED, kind)
    [(event, used_scope)] = dispatcher.published
    assert type(event) is event_type
    assert event.order_id.value == ORDER_ID  # type: ignore[attr-defined]
    assert event.triggering_event_id.value == EVENT_ID  # type: ignore[attr-defined]
    assert used_scope is scope
    assert calls == ["step returned", "publish"], "published strictly after the step returned"


@pytest.mark.parametrize(
    "result",
    [
        SagaFactResult(SagaFactOutcome.DUPLICATE, None),
        SagaFactResult(SagaFactOutcome.IGNORED, None),
        SagaFactResult(SagaFactOutcome.PROCESSED, None),
        SagaFactResult(SagaFactOutcome.DUPLICATE, SagaCommandKind.STOCK_RESERVE),
        SagaFactResult(SagaFactOutcome.IGNORED, SagaCommandKind.STOCK_RESERVE),
    ],
    ids=[
        "duplicate",
        "ignored",
        "processed without a command",
        "duplicate with a kind",
        "ignored with a kind",
    ],
)
async def test_nothing_is_published_for_a_duplicate_an_ignored_fact_or_a_step_that_owed_nothing(
    result: SagaFactResult, envelope_bytes: Callable[..., bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    dispatcher = RecordingDispatcher(calls)
    stub_the_step(monkeypatch, result, calls)
    command = command_for("stock.reserved.v1", envelope_bytes("stock.reserved.v1"))

    returned = await SagaFactCommandHandler(scope_with(dispatcher)).handle(command)

    assert returned == result
    assert dispatcher.published == []


async def test_the_step_receives_the_fact_built_from_the_command(
    envelope_bytes: Callable[..., bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    seen = stub_the_step(monkeypatch, SagaFactResult(SagaFactOutcome.IGNORED, None), calls)

    await SagaFactCommandHandler(scope_with(RecordingDispatcher(calls))).handle(
        command_for("stock.reserved.v1", envelope_bytes("stock.reserved.v1"), topic="t.seen")
    )

    [fact] = seen
    assert (fact.event_type, fact.topic) == ("stock.reserved.v1", "t.seen")
    assert fact.event_id.value == EVENT_ID


def test_a_scope_with_no_dispatcher_or_no_consumption_is_refused_when_the_handler_is_built() -> (
    None
):
    with pytest.raises(MissingBindingError) as no_dispatcher:
        SagaFactCommandHandler(scope_with(None))
    assert no_dispatcher.value.binding == "dispatcher"

    with pytest.raises(MissingBindingError) as no_consumption:
        SagaFactCommandHandler(scope_with(RecordingDispatcher([]), consumption=None))
    assert no_consumption.value.binding == "fact_consumption"
