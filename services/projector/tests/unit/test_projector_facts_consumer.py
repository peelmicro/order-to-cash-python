"""I3 (PR3, PR4, PR36): the consumer task's routing, over a recording dispatcher.

`handle` is driven directly with `FactMessage`s, the way the subscriber drives it. A return means
the offset is committed; a raise means it is not (the subscriber seeks back and retries).
"""

import json
import logging
from typing import Any, cast

import pytest

from otc_contracts import FACT_MODELS
from otc_cqrs import Dispatcher
from otc_projector.application.messages import ProjectFactCommand
from otc_projector.application.ports.fact_stream import FactMessage, FactStreamSubscriber
from otc_projector.application.scope import ProjectorScope
from otc_projector.presentation.projector_facts_consumer import ProjectorFactsConsumerTask

LOGGER = "otc_projector.presentation.projector_facts_consumer"


class RecordingDispatcher:
    def __init__(self) -> None:
        self.sent: list[ProjectFactCommand] = []

    async def send(self, command: ProjectFactCommand, scope: object) -> None:
        self.sent.append(command)


class NoSubscriber:
    async def run(self, handler: Any, stop: Any) -> None:
        raise AssertionError("not driven in these tests")


def task_over(dispatcher: RecordingDispatcher) -> ProjectorFactsConsumerTask:
    return ProjectorFactsConsumerTask(
        subscriber=cast("FactStreamSubscriber", NoSubscriber()),
        dispatcher=cast("Dispatcher[ProjectorScope]", dispatcher),
        scope_factory=lambda: cast("ProjectorScope", object()),
    )


def message(value: bytes, offset: int = 41) -> FactMessage:
    return FactMessage(
        topic="otc.orders.facts.v1", partition=3, offset=offset, key=None, value=value, headers=()
    )


def valid_document(facts: Any, event_type: str = "order.placed.v1") -> dict[str, Any]:
    document: dict[str, Any] = json.loads(facts.wire(facts.build(event_type)))
    return document


@pytest.mark.parametrize(
    "case",
    ["not json", "not an object", "missing field", "naive occurredAt", "empty value", "upper case"],
)
async def test_pr3_a_malformed_envelope_is_logged_and_committed_with_no_dispatch(
    facts: Any, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    document = valid_document(facts)
    value: bytes
    if case == "not json":
        value = b"{not json"
    elif case == "not an object":
        value = b'["order.placed.v1"]'
    elif case == "missing field":
        del document["causationId"]
        value = json.dumps(document).encode()
    elif case == "naive occurredAt":
        document["occurredAt"] = "2026-03-01T10:00:00.000"
        value = json.dumps(document).encode()
    elif case == "empty value":
        value = b""
    else:
        document["eventType"] = "Order.Placed.v1"
        value = json.dumps(document).encode()
    dispatcher = RecordingDispatcher()
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        await task_over(dispatcher).handle(message(value, offset=77))  # returns: committed
    assert dispatcher.sent == [], f"{case}: a malformed record was dispatched"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1, f"{case}: {[r.getMessage() for r in caplog.records]}"
    assert errors[0].__dict__["offset"] == 77
    assert errors[0].__dict__["partition"] == 3
    assert errors[0].__dict__["topic"] == "otc.orders.facts.v1"


@pytest.mark.parametrize("event_type", ["order.shipped.v1", "order.placed.v2"])
async def test_pr4_an_unregistered_event_type_is_logged_and_committed_never_silently(
    facts: Any, caplog: pytest.LogCaptureFixture, event_type: str
) -> None:
    document = valid_document(facts)
    document["eventType"] = event_type
    dispatcher = RecordingDispatcher()
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        await task_over(dispatcher).handle(message(json.dumps(document).encode(), offset=5))
    assert dispatcher.sent == []
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1, "an unregistered type must be logged, never silently dropped"
    assert event_type in errors[0].getMessage()
    assert errors[0].__dict__["offset"] == 5
    assert errors[0].__dict__["partition"] == 3
    assert errors[0].__dict__["topic"] == "otc.orders.facts.v1"


async def test_pr4_a_registered_type_with_an_invalid_payload_propagates(facts: Any) -> None:
    document = valid_document(facts)
    document["payload"] = {}
    dispatcher = RecordingDispatcher()
    with pytest.raises(ValueError, match="orderReference"):
        await task_over(dispatcher).handle(message(json.dumps(document).encode()))
    assert dispatcher.sent == []


@pytest.mark.parametrize("event_type", sorted(FACT_MODELS))
async def test_pr36_each_of_the_fourteen_facts_reaches_the_dispatcher_typed_by_the_registry(
    facts: Any, event_type: str
) -> None:
    dispatcher = RecordingDispatcher()
    event = facts.build(event_type)
    await task_over(dispatcher).handle(message(facts.wire(event)))
    assert len(dispatcher.sent) == 1
    sent = dispatcher.sent[0].event
    assert isinstance(sent, FACT_MODELS[event_type])
    assert sent == event
