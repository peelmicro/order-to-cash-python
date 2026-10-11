"""J6 (PR15): every field of a document is a pure function of the SET of facts applied.

* Through Kafka (design 11.3, #8's advisory A6: its determinism test did not go through Kafka): two
  orders' facts, DUPLICATED and SHUFFLED across the three real topics; group `g1` into database A,
  group `g2` into database B, every document's raw BSON equal; then group `g3` into database A
  again: every outcome DUPLICATE, bytes unchanged, zero frames on NATS.
* Through the writer: every permutation of one order's six facts, each followed by a full second
  pass (duplicates), yields the same bytes.

The topics are this test's PRIVATE topics (`Topics` in `conftest.py`: the real ones are shared by
every service's tests for the whole session, and a group starting at `earliest` would replay all of
it). Restart model: NEW CONSUMER GROUPS (design 11.2b).
"""

import asyncio
import dataclasses
import itertools
import random
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient
from pymongo import AsyncMongoClient

import otc_projector.application
from otc_cqrs import HandlerRegistry
from otc_projector.application.handlers import ProjectFactHandler
from otc_projector.application.messages import ProjectFactCommand
from otc_projector.application.outcome import ProjectionOutcome
from otc_projector.application.scope import ProjectorScope
from otc_projector.composition import Externals, Wiring

pytestmark = pytest.mark.integration

SEED = 4242


def at(second: int) -> datetime:
    return datetime(2026, 6, 1, 9, 0, second, 0, tzinfo=UTC)


def eid(order: int, n: int) -> uuid.UUID:
    return uuid.UUID(f"{order:04x}{n:04x}-0000-4000-8000-{order * 1000 + n:012x}")


def six_facts(facts: Any, order: uuid.UUID, number: int, reference: str) -> list[Any]:
    """placed t1, reserved t2, approved t3, confirmed t3 (cites approved: a live tie), despatched
    t5, invoiced t6: one tie group inside an otherwise instant-ordered timeline."""
    spec = [
        ("order.placed.v1", 1, 1, 90, {"order_reference": reference}),
        ("stock.reserved.v1", 2, 2, 1, {}),
        ("credit.approved.v1", 3, 3, 2, {}),
        ("order.confirmed.v1", 3, 4, 3, {}),
        ("order.despatched.v1", 5, 5, 4, {}),
        ("invoice.issued.v1", 6, 6, 5, {}),
    ]
    return [
        facts.build(
            event_type,
            correlation_id=order,
            event_id=eid(number, n),
            causation_id=eid(number, cause) if cause < 90 else eid(number, 99),
            occurred_at=at(second),
            payload=payload,
        )
        for event_type, second, n, cause, payload in spec
    ]


async def committed(bootstrap: str, group: str) -> dict[tuple[str, int], int]:
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        offsets = await admin.list_consumer_group_offsets(group)
        return {(tp.topic, tp.partition): meta.offset for tp, meta in offsets.items()}
    finally:
        await admin.close()


async def end_offsets(bootstrap: str, topics: tuple[str, ...]) -> dict[tuple[str, int], int]:
    consumer = AIOKafkaConsumer(bootstrap_servers=bootstrap)
    await consumer.start()
    try:
        from aiokafka import TopicPartition

        partitions = [
            TopicPartition(topic, partition)
            for topic in topics
            for partition in sorted(consumer.partitions_for_topic(topic) or ())
        ]
        if not partitions:
            await consumer.topics()
            partitions = [
                TopicPartition(topic, partition)
                for topic in topics
                for partition in sorted(consumer.partitions_for_topic(topic) or ())
            ]
        ends = await consumer.end_offsets(partitions)
        return {(tp.topic, tp.partition): offset for tp, offset in ends.items()}
    finally:
        await consumer.stop()


async def wait_for(claim: str, check: Any, seconds: float = 90.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while True:
        outcome = check()
        if hasattr(outcome, "__await__"):
            outcome = await outcome
        if outcome:
            return
        if loop.time() > deadline:
            pytest.fail(f"{claim}: not observed within {seconds} s")
        await asyncio.sleep(0.1)


async def raw_documents(model: Any, orders: list[uuid.UUID]) -> dict[str, bytes]:
    return {str(order): await model.raw(order) for order in orders}


def recording_externals(outcomes: list[ProjectionOutcome]) -> Externals:
    class Recording:
        def __init__(self, scope: ProjectorScope) -> None:
            self._inner = ProjectFactHandler(scope)

        async def handle(self, command: ProjectFactCommand, /) -> ProjectionOutcome:
            outcome = await self._inner.handle(command)
            outcomes.append(outcome)
            return outcome

    def wire() -> Wiring:
        registry = HandlerRegistry[ProjectorScope]()
        registry.register_command(ProjectFactCommand, Recording)
        return registry.build(otc_projector.application), registry.registered_factories()

    return Externals(wire=wire)


async def test_pr15_replaying_the_topics_into_a_new_group_reproduces_byte_identical_documents(
    runtime_env: Any, produce: Any, facts: Any, new_reference: Any, frames_factory: Any
) -> None:
    order_one, order_two = uuid.UUID(int=0x15AAAA01), uuid.UUID(int=0x15BBBB02)
    events = six_facts(facts, order_one, 1, new_reference()) + six_facts(
        facts, order_two, 2, new_reference()
    )
    shuffled = [*events, *events]  # every fact TWICE
    random.Random(SEED).shuffle(shuffled)  # noqa: S311 - a reproducible test shuffle
    await produce(shuffled)

    database_b = f"{runtime_env.database}_b"
    env_b = dataclasses.replace(runtime_env, database=database_b)
    model_a, model_b = runtime_env.read_model(), env_b.read_model()
    orders = [order_one, order_two]

    async def all_applied(model: Any) -> bool:
        for order in orders:
            found = await model.collection.find_one({"_id": str(order)})
            if found is None or len(found["processedEventKeys"]) < 6:
                return False
        return True

    try:
        first = await runtime_env.start("replay-g1")
        await wait_for("g1 applied all twelve facts into database A", lambda: all_applied(model_a))
        await first.stop()
        second = await env_b.start("replay-g2")
        await wait_for("g2 applied all twelve facts into database B", lambda: all_applied(model_b))
        await second.stop()

        bytes_a, bytes_b = (
            await raw_documents(model_a, orders),
            await raw_documents(model_b, orders),
        )
        for order in orders:
            assert bytes_a[str(order)] == bytes_b[str(order)], (
                f"order {order}: a replay into a new group produced different bytes"
            )
            document = await model_a.document(order)
            assert len(document["events"]) == 6, "a duplicate produced a second entry"
            assert document["status"] == "invoiced"

        # g3 into database A again: every outcome DUPLICATE, bytes unchanged, zero frames
        whole = await frames_factory("readmodel.>")
        outcomes: list[ProjectionOutcome] = []
        third = await runtime_env.start("replay-g3", externals=recording_externals(outcomes))
        ends = await end_offsets(runtime_env.kafka, runtime_env.topics.all)

        async def caught_up() -> bool:
            done = await committed(runtime_env.kafka, "replay-g3")
            return all(done.get(tp, 0) >= end for tp, end in ends.items() if end > 0)

        await wait_for("g3 consumed every retained record", caught_up)
        await third.stop()
        assert outcomes, "g3 saw no record"
        assert set(outcomes) == {ProjectionOutcome.DUPLICATE}, (
            f"g3 applied {outcomes.count(ProjectionOutcome.PROCESSED)} facts that g1 had applied"
        )
        assert await raw_documents(model_a, orders) == bytes_a, "g3 changed a document"
        # a barrier on the same subscription: once it arrived, everything published before it has
        await whole.connection.publish("readmodel.barrier", b"__barrier__")
        await whole.connection.flush()
        await wait_for("the NATS barrier", lambda: whole.barriers >= 1)
        assert whole.received == [], f"g3 emitted {len(whole.received)} frame(s) for duplicates"
    finally:
        await model_a.client.close()
        await model_b.client.close()
        cleanup: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(runtime_env.mongo_uri)
        try:
            await cleanup.drop_database(database_b)
        finally:
            await cleanup.close()


async def test_pr15_shuffled_and_duplicated_application_yields_byte_identical_documents(
    read_model: Any, facts: Any
) -> None:
    order = uuid.UUID(int=0x15CCCC03)
    events = six_facts(facts, order, 3, "ORD-710001")
    reference: bytes | None = None
    for permutation in itertools.permutations(range(6)):
        await read_model.collection.delete_many({})
        sequence = [events[i] for i in permutation]
        for event in [*sequence, *reversed(sequence)]:  # a full second pass: all duplicates
            await read_model.apply(event)
        stored = await read_model.raw(order)
        if reference is None:
            reference = stored
        assert stored == reference, f"permutation {permutation} produced different bytes"
    assert reference is not None
