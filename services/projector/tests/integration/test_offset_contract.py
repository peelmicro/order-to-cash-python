"""I4 (PR5, PR38): the offset contract, read from the BROKER and never inferred from a redelivery.

* A handler that raises leaves the group's committed offsets unchanged (the record is sought back
  and delivered again); the successful redelivery advances them by exactly one. The committed
  offsets are read with an admin client over every partition the group has committed.
* A fact produced BEFORE the group ever subscribed is projected: a new group starts at `earliest`
  (aiokafka's default is `latest`).

The offset case uses a PRIVATE topic of three partitions (the shared fact topics carry whatever
earlier tests produced, and a replaying group would consume it all), and its handler blocks on the
third call, so consumption stops after exactly one commit.
"""

import asyncio
import uuid
from typing import Any

import pytest
from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

from otc_projector.application.ports.fact_stream import FactMessage
from otc_projector.infrastructure.messaging.kafka_fact_subscriber import KafkaFactSubscriber
from otc_projector.infrastructure.settings import KafkaSettings

pytestmark = pytest.mark.integration


async def committed(bootstrap: str, group: str) -> dict[tuple[str, int], int]:
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        offsets = await admin.list_consumer_group_offsets(group)
        return {(tp.topic, tp.partition): meta.offset for tp, meta in offsets.items()}
    finally:
        await admin.close()


async def until(claim: str, event: asyncio.Event, seconds: float = 60.0) -> None:
    try:
        async with asyncio.timeout(seconds):
            await event.wait()
    except TimeoutError:
        pytest.fail(f"{claim}: not observed within {seconds} s")


async def test_pr38_a_raising_handler_leaves_the_committed_offset_unchanged_read_from_the_broker(
    kafka_server: Any,
) -> None:
    bootstrap = kafka_server.bootstrap_servers
    topic = f"offset-contract-{uuid.uuid4().hex[:8]}"
    group = f"offset-group-{uuid.uuid4().hex[:8]}"
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        await admin.create_topics([NewTopic(name=topic, num_partitions=3, replication_factor=1)])
    finally:
        await admin.close()
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap)
    await producer.start()
    try:
        await producer.send_and_wait(topic, b"first", key=b"k1", partition=0)
        await producer.send_and_wait(topic, b"second", key=b"k2", partition=0)
    finally:
        await producer.stop()

    calls: list[bytes] = []
    first_failed = asyncio.Event()
    third_started = asyncio.Event()
    release = asyncio.Event()

    async def handler(message: FactMessage) -> None:
        calls.append(message.value)
        if len(calls) == 1:
            first_failed.set()
            raise RuntimeError("the handler raises on its first call")
        if len(calls) == 3:
            third_started.set()
            await release.wait()  # consumption stops here: exactly one commit has happened

    settings = KafkaSettings.model_validate(
        {
            "KAFKA_BROKERS": bootstrap,
            "PROJECTOR_KAFKA_CLIENT_ID": f"offset-client-{group}",
            "PROJECTOR_CONSUMER_GROUP": group,
        }
    )
    subscriber = KafkaFactSubscriber(settings, topics=(topic,))
    stop = asyncio.Event()
    task = asyncio.create_task(subscriber.run(handler, stop), name="offset-contract-subscriber")
    try:
        await until("the first (raising) handler call", first_failed)
        # the handler has RAISED: the broker's committed offsets must not have moved
        assert await committed(bootstrap, group) == {}, (
            "an offset was committed although the handler raised"
        )
        await until("the third handler call (after the redelivery succeeded)", third_started)
        offsets = await committed(bootstrap, group)
        assert calls[:2] == [b"first", b"first"], f"the record was not redelivered: {calls}"
        assert sum(offsets.values()) == 1, (
            f"the committed offsets advanced by {sum(offsets.values())}, not by exactly one: "
            f"{offsets}"
        )
        assert offsets == {(topic, 0): 1}
    finally:
        release.set()
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_pr5_a_fact_produced_before_the_group_ever_subscribed_is_projected(
    runtime_env: Any, produce: Any, facts: Any, new_reference: Any
) -> None:
    order = uuid.UUID("0a0b0c0d-7777-4000-8000-0000000000a1")
    reference = new_reference()
    # produced FIRST: the group below has never existed
    await produce(
        [
            facts.build(
                "order.placed.v1", correlation_id=order, payload={"order_reference": reference}
            )
        ]
    )
    group = f"never-used-{uuid.uuid4().hex[:8]}"
    model = runtime_env.read_model()
    try:
        await runtime_env.start(group)
        deadline = asyncio.get_running_loop().time() + 60
        document: dict[str, Any] | None = None
        while asyncio.get_running_loop().time() < deadline:
            document = await model.collection.find_one({"_id": str(order)})
            if document is not None and document["headerComplete"]:
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail(
                "PR5: a fact produced before the group subscribed was not projected in 60 s"
            )
        assert document is not None
        assert document["orderReference"] == reference
    finally:
        await model.client.close()
