"""`FULFILLMENT_FACTS_TOPIC` equals the Kafka topic of `asyncapi.yaml`'s `fulfillmentFacts` channel.

Ported from #8's `FulfillmentFactTopicTests`. #8 A6: the instrument really reads the file (pyyaml),
it does not compare the constant with a second hand-typed copy.
"""

from pathlib import Path
from typing import Any

import yaml

from otc_fulfillment.infrastructure.outbox.topic import FULFILLMENT_FACTS_TOPIC

ASYNCAPI = Path(__file__).resolve().parents[4] / "specs" / "shared" / "asyncapi.yaml"


def test_c5_the_fulfillment_topic_is_the_kafka_binding_of_the_fulfillment_facts_channel() -> None:
    document: dict[str, Any] = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    channel = document["channels"]["fulfillmentFacts"]
    topic = channel["bindings"]["kafka"]["topic"]
    assert isinstance(topic, str)
    assert topic == FULFILLMENT_FACTS_TOPIC, (
        "channel fulfillmentFacts: the topic the outbox publishes to is not the spec's"
    )
    assert channel["address"] == FULFILLMENT_FACTS_TOPIC
