"""E4 (PR23, PR25, PR26): the five conformance cases of the idempotent-consumer pattern, proven over
REAL MongoDB with the real variant (`infrastructure/messaging/idempotent_consumer.py`). This file
is the one its banner names after `Behavioural conformance:` and the Orders parity guard demands
exists.

The subject is the real `IdempotentConsumer` over the real driver; the pipeline is a dedup-only
`$set` (it records the key and nothing else); the work is the post-apply callback, COUNTED. Every
case asserts the returned outcome AND the counter: the attempt, not only the residue.

Restart model (design 11.2): case 3 is a NEW `AsyncMongoClient` and a NEW instance in the same
process, on the same database: the in-process half of "a fresh instance still sees the key". The
process-restart half is the live walkthrough. Loop scope: the function loop of each test; each
client is closed in the test that created it.
"""

import uuid
from collections.abc import Mapping
from typing import Any

import pytest
from pymongo import AsyncMongoClient

from otc_projector.infrastructure.messaging.consumer_name import ConsumerName
from otc_projector.infrastructure.messaging.idempotent_consumer import (
    ConsumptionOutcome,
    IdempotentConsumer,
)

pytestmark = pytest.mark.integration

SCOPE = "scope-0001"


def dedup_only(key: str) -> list[dict[str, object]]:
    return [
        {
            "$set": {
                "processedEventKeys": {
                    "$sortArray": {
                        "input": {
                            "$setUnion": [
                                {"$ifNull": ["$processedEventKeys", []]},
                                {"$literal": [key]},
                            ]
                        },
                        "sortBy": 1,
                    }
                }
            }
        }
    ]


class Counter:
    """The post-apply work: how many times it ran, and with what."""

    def __init__(self) -> None:
        self.documents: list[Mapping[str, Any]] = []

    async def __call__(self, document: Mapping[str, Any]) -> None:
        self.documents.append(document)

    @property
    def count(self) -> int:
        return len(self.documents)


async def collection_for(uri: str, database: str) -> tuple[Any, Any]:
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(uri)
    collection = client.get_database(database).get_collection("conformance")
    return client, collection


async def run(
    consumer: IdempotentConsumer,
    event_id: uuid.UUID,
    counter: Counter,
    name: ConsumerName = ConsumerName.PROJECTOR,
) -> ConsumptionOutcome:
    return await consumer.run_once(
        scope_id=SCOPE, event_id=event_id, consumer=name, stages=dedup_only, after_applied=counter
    )


async def with_scope(fresh_mongo_database: Any) -> tuple[Any, IdempotentConsumer]:
    client, collection = await collection_for(fresh_mongo_database.uri, fresh_mongo_database.name)
    await collection.insert_one({"_id": SCOPE, "processedEventKeys": []})
    return client, IdempotentConsumer(collection)


async def test_pr25_case_1_the_first_call_is_processed_and_the_post_apply_work_runs_once(
    fresh_mongo_database: Any,
) -> None:
    client, consumer = await with_scope(fresh_mongo_database)
    try:
        counter = Counter()
        event = uuid.uuid4()
        assert await run(consumer, event, counter) is ConsumptionOutcome.PROCESSED
        assert counter.count == 1, "the post-apply work did not run exactly once"
        stored = await client.get_database(fresh_mongo_database.name).conformance.find_one(
            {"_id": SCOPE}
        )
        assert stored["processedEventKeys"] == [f"projector:{event}"]
    finally:
        await client.close()


async def test_pr25_case_2_the_same_event_and_consumer_again_is_a_duplicate_and_work_does_not_run(
    fresh_mongo_database: Any,
) -> None:
    client, consumer = await with_scope(fresh_mongo_database)
    try:
        counter = Counter()
        event = uuid.uuid4()
        assert await run(consumer, event, counter) is ConsumptionOutcome.PROCESSED
        assert await run(consumer, event, counter) is ConsumptionOutcome.DUPLICATE
        assert counter.count == 1, "the work ran again for a duplicate"
    finally:
        await client.close()


async def test_pr25_case_3_a_fresh_instance_over_a_new_client_on_the_same_database_still_sees_it(
    fresh_mongo_database: Any,
) -> None:
    first_client, first = await with_scope(fresh_mongo_database)
    second_client, second_collection = await collection_for(
        fresh_mongo_database.uri, fresh_mongo_database.name
    )
    try:
        counter = Counter()
        event = uuid.uuid4()
        assert await run(first, event, counter) is ConsumptionOutcome.PROCESSED
        second = IdempotentConsumer(second_collection)
        assert second is not first
        again = await run(second, event, counter)
        assert again is ConsumptionOutcome.DUPLICATE, (
            "case 3: a fresh instance over a new client did not see the recorded key"
        )
        assert counter.count == 1, "a fresh instance re-ran the work"
    finally:
        await first_client.close()
        await second_client.close()


async def test_pr25_case_4_two_distinct_events_are_both_processed(
    fresh_mongo_database: Any,
) -> None:
    client, consumer = await with_scope(fresh_mongo_database)
    try:
        counter = Counter()
        assert await run(consumer, uuid.uuid4(), counter) is ConsumptionOutcome.PROCESSED
        assert await run(consumer, uuid.uuid4(), counter) is ConsumptionOutcome.PROCESSED
        assert counter.count == 2
    finally:
        await client.close()


async def test_pr25_case_5_the_same_event_under_a_different_consumer_name_runs(
    fresh_mongo_database: Any,
) -> None:
    client, consumer = await with_scope(fresh_mongo_database)
    try:
        counter = Counter()
        event = uuid.uuid4()
        assert await run(consumer, event, counter) is ConsumptionOutcome.PROCESSED
        other = await run(consumer, event, counter, ConsumerName.NOTIFICATIONS)
        assert other is ConsumptionOutcome.PROCESSED, (
            "case 5: the same eventId under another consumer name was treated as a duplicate"
        )
        assert await run(consumer, event, counter) is ConsumptionOutcome.DUPLICATE
        assert counter.count == 2
        stored = await client.get_database(fresh_mongo_database.name).conformance.find_one(
            {"_id": SCOPE}
        )
        assert stored["processedEventKeys"] == sorted(
            [f"projector:{event}", f"notifications:{event}"]
        )
    finally:
        await client.close()


async def test_pr26_the_post_apply_callback_runs_once_on_processed_and_never_on_duplicate(
    fresh_mongo_database: Any,
) -> None:
    client, consumer = await with_scope(fresh_mongo_database)
    try:
        counter = Counter()
        event = uuid.uuid4()
        assert await run(consumer, event, counter) is ConsumptionOutcome.PROCESSED
        assert counter.count == 1
        # the callback receives the POST-apply document: it already holds the key
        assert counter.documents[0]["processedEventKeys"] == [f"projector:{event}"]
        for _ in range(3):
            assert await run(consumer, event, counter) is ConsumptionOutcome.DUPLICATE
        assert counter.count == 1, "the callback ran for a duplicate"
    finally:
        await client.close()


async def test_pr23_the_key_is_recorded_by_the_same_write_that_applies_the_projection(
    read_model: Any, facts: Any
) -> None:
    """One command in the driver's stream carries BOTH the dedup key and the projection."""
    event = facts.build("order.confirmed.v1")
    read_model.log.clear()
    await read_model.apply(event)
    carriers = [
        (name, command)
        for name, command in read_model.log.full_commands
        if "$setUnion" in repr(command) and "processedEventKeys" in repr(command)
    ]
    assert [name for name, _ in carriers] == ["findAndModify"], (
        f"the dedup key is written by {[name for name, _ in carriers]}"
    )
    (_, command) = carriers[0]
    assert "$concatArrays" in repr(command), "the same write must also append the timeline entry"
    assert f"projector:{event.event_id}" in repr(command)
    # and no other command in the stream mentions the key
    others = [
        name
        for name, other in read_model.log.full_commands
        if name != "findAndModify" and f"projector:{event.event_id}" in repr(other)
    ]
    assert others == []
