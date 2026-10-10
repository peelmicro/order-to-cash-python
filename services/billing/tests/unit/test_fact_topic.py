"""`BILLING_FACTS_TOPIC` equals the Kafka topic of `asyncapi.yaml`'s `billingFacts` channel (F2).

#8 A6: the instrument really reads the file (pyyaml), it does not compare the constant with a
second hand-typed copy.

Loop scope: nothing here is async.
"""

from pathlib import Path
from typing import Any

import yaml

from otc_billing.infrastructure.outbox.topic import BILLING_FACTS_TOPIC

ASYNCAPI = Path(__file__).resolve().parents[4] / "specs" / "shared" / "asyncapi.yaml"


def test_the_billing_topic_is_the_kafka_binding_of_the_billing_facts_channel() -> None:
    document: dict[str, Any] = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    channel = document["channels"]["billingFacts"]
    topic = channel["bindings"]["kafka"]["topic"]
    assert isinstance(topic, str)
    assert topic == BILLING_FACTS_TOPIC, (
        "channel billingFacts: the topic the outbox publishes to is not the spec's"
    )
    assert channel["address"] == BILLING_FACTS_TOPIC
