"""A6: the consumed topics are exactly three, each equal to `asyncapi.yaml`'s channel address."""

from pathlib import Path
from typing import Any

import yaml

from otc_projector.infrastructure.messaging.fact_topics import PROJECTOR_FACT_TOPICS

ASYNCAPI = Path(__file__).resolve().parents[4] / "specs" / "shared" / "asyncapi.yaml"


def document() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    return loaded


def test_the_projector_consumes_exactly_the_three_asyncapi_fact_channel_addresses() -> None:
    channels = document()["channels"]
    expected = tuple(
        channels[c]["address"] for c in ("ordersFacts", "fulfillmentFacts", "billingFacts")
    )
    assert expected == PROJECTOR_FACT_TOPICS
    assert len(PROJECTOR_FACT_TOPICS) == 3
    assert len(set(PROJECTOR_FACT_TOPICS)) == 3


def test_the_topics_are_exactly_the_channels_the_projector_operations_receive_from() -> None:
    d = document()
    channels = {
        d["channels"][op["channel"]["$ref"].rsplit("/", 1)[1]]["address"]
        for name, op in d["operations"].items()
        if name.startswith("projectorConsumes")
    }
    assert channels == set(PROJECTOR_FACT_TOPICS)
