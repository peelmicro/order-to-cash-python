"""E6 (PR7): concurrent applies from SEPARATE `AsyncMongoClient`s, each its own connection pool.

One client would serialise on its pool and prove nothing (#7's reviewer opened twelve; #8 L24).
Every wait is bounded by `asyncio.timeout` with a message naming the claim: this project's pytest
has no timeout plugin, and a hung `gather` would hang the suite.

The server re-evaluates a losing `findAndModify`'s predicate after a write conflict and matches
nothing: a server property, here PROVEN rather than assumed, in a client shape (asyncio, one loop)
that #7 and #8 did not have.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from otc_projector.application.outcome import ProjectionOutcome

pytestmark = pytest.mark.integration

CLIENTS = 8
ROUNDS = 6
BOUND_SECONDS = 90


async def bounded[T](claim: str, work: Awaitable[T]) -> T:
    try:
        async with asyncio.timeout(BOUND_SECONDS):
            return await work
    except TimeoutError:
        pytest.fail(f"{claim}: did not finish within {BOUND_SECONDS} s")


async def close_all(models: list[Any]) -> None:
    for model in models:
        await model.client.close()


async def test_pr7_concurrent_deliveries_of_one_event_id_from_separate_clients_apply_exactly_once(
    new_model_factory: Callable[[], Any], facts: Any
) -> None:
    models = [new_model_factory() for _ in range(CLIENTS)]
    try:
        for round_number in range(ROUNDS):
            order = uuid.UUID(int=0xC0FFEE00 + round_number)
            event = facts.build("order.confirmed.v1", correlation_id=order)
            results = await bounded(
                f"PR7 same-eventId round {round_number}",
                asyncio.gather(*(model.apply(event) for model in models)),
            )
            outcomes = [r.outcome for r in results]
            assert outcomes.count(ProjectionOutcome.PROCESSED) == 1, (
                f"round {round_number}: {outcomes.count(ProjectionOutcome.PROCESSED)} PROCESSED"
            )
            assert outcomes.count(ProjectionOutcome.DUPLICATE) == CLIENTS - 1
            callbacks = sum(len(r.documents) for r in results)
            assert callbacks == 1, f"round {round_number}: the callback ran {callbacks} times"
            document = await models[0].document(order)
            assert len(document["events"]) == 1, "the entry was appended more than once"
            assert document["processedEventKeys"] == [f"projector:{event.event_id}"]
    finally:
        await close_all(models)


async def test_pr7_concurrent_first_facts_for_an_absent_order_end_in_one_document_holding_both(
    new_model_factory: Callable[[], Any], facts: Any
) -> None:
    models = [new_model_factory() for _ in range(CLIENTS)]
    try:
        for round_number in range(ROUNDS):
            order = uuid.UUID(int=0xBEEF0000 + round_number)
            types = ["order.confirmed.v1", "order.despatched.v1"] * (CLIENTS // 2)
            events = [
                facts.build(
                    event_type,
                    correlation_id=order,
                    event_id=uuid.UUID(int=0xE0000000 + round_number * 100 + index),
                )
                for index, event_type in enumerate(types)
            ]
            try:
                results = await bounded(
                    f"PR7 absent-order round {round_number}",
                    asyncio.gather(*(m.apply(e) for m, e in zip(models, events, strict=True))),
                )
            except Exception as error:
                pytest.fail(f"PR7: an error escaped the race for an absent order: {error!r}")
            assert all(r.outcome is ProjectionOutcome.PROCESSED for r in results)
            count = await models[0].collection.count_documents({"_id": str(order)})
            assert count == 1, f"round {round_number}: {count} documents for one order"
            document = await models[0].document(order)
            assert {e["eventId"] for e in document["events"]} == {str(e.event_id) for e in events}
            assert len(document["events"]) == CLIENTS
            assert len(document["processedEventKeys"]) == CLIENTS
    finally:
        await close_all(models)
