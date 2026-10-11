"""The consumed topics equal the asyncapi channel addresses, and the ledger's consumer name is
`notifications` (R17: `(eventId, consumer)`; `asyncapi.yaml`: "Consumer name — notifications")."""

from pathlib import Path
from typing import Any

import yaml

from otc_notifications.infrastructure.messaging.consumer_name import ConsumerName
from otc_notifications.infrastructure.messaging.fact_topics import NOTIFICATION_FACT_TOPICS
from otc_notifications.infrastructure.persistence import delivery_ledger
from otc_notifications.infrastructure.settings import KafkaSettings

ASYNCAPI = Path(__file__).resolve().parents[4] / "specs" / "shared" / "asyncapi.yaml"


def document() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    return loaded


def test_the_three_consumed_topics_equal_the_asyncapi_fact_channel_addresses() -> None:
    channels = document()["channels"]
    expected = tuple(
        channels[c]["address"] for c in ("ordersFacts", "fulfillmentFacts", "billingFacts")
    )
    assert expected == NOTIFICATION_FACT_TOPICS
    assert len(set(NOTIFICATION_FACT_TOPICS)) == 3


def test_the_topics_are_exactly_the_channels_the_notifications_operations_receive_from() -> None:
    d = document()
    channels = {
        d["channels"][op["channel"]["$ref"].rsplit("/", 1)[1]]["address"]
        for name, op in d["operations"].items()
        if name.startswith("notificationsConsume")
    }
    assert channels == set(NOTIFICATION_FACT_TOPICS)


def test_the_ledger_consumer_name_is_notifications_and_is_the_default_group() -> None:
    assert delivery_ledger.CONSUMER is ConsumerName.NOTIFICATIONS
    assert ConsumerName.NOTIFICATIONS.value == "notifications"
    assert KafkaSettings.model_validate({}).group_id == ConsumerName.NOTIFICATIONS.value
