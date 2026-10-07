"""The root `kafka_server` fixture, asserted against the broker rather than against its own
arguments (feature 14 task 2.2): the topic exists with the partition count `R15` needs."""

from typing import Any

from aiokafka.admin import AIOKafkaAdminClient

ORDERS_FACTS_TOPIC = "otc.orders.facts.v1"
EXPECTED_PARTITIONS = 6  # .env.example KAFKA_TOPIC_PARTITIONS; one partition would make R15 vacuous


class FixtureServer:
    """The shape of the root conftest's `KafkaServer` (conftest modules are not importable)."""

    bootstrap_servers: str


async def test_the_kafka_fixture_topic_has_six_partitions(kafka_server: FixtureServer) -> None:
    # Function loop: the admin client is created and closed inside this test's own loop. The count
    # is what the BROKER reports in its metadata, not the fixture's own constant.
    admin = AIOKafkaAdminClient(bootstrap_servers=kafka_server.bootstrap_servers)
    await admin.start()
    try:
        described: list[dict[str, Any]] = await admin.describe_topics([ORDERS_FACTS_TOPIC])
    finally:
        await admin.close()
    assert len(described) == 1, described
    assert described[0]["topic"] == ORDERS_FACTS_TOPIC
    partitions = described[0]["partitions"]
    assert len(partitions) == EXPECTED_PARTITIONS, (
        f"{ORDERS_FACTS_TOPIC} has {len(partitions)} partitions on the broker: {partitions}"
    )
