"""The saga's topics and subjects equal the channel addresses of `asyncapi.yaml` (task 2.5, 4.2).

Ported from #8's `SagaFactTopicsTests` / `SagaRpcSubjectsTests`. Every other test addresses Kafka
and NATS by a hand-typed literal, so without this a drift between the spec and the code AND those
tests would stay green. The channels are found by their channel id in the parsed document.
"""

from pathlib import Path
from typing import Any

import yaml

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.infrastructure.messaging.fact_topics import SAGA_FACT_TOPICS
from otc_orders.infrastructure.messaging.saga_subjects import SAGA_SUBJECTS

ASYNCAPI = Path(__file__).resolve().parents[5] / "specs" / "shared" / "asyncapi.yaml"

TOPIC_CHANNELS = ("ordersFacts", "fulfillmentFacts", "billingFacts")
SUBJECT_CHANNELS = {
    SagaCommandKind.STOCK_RESERVE: "stockReserve",
    SagaCommandKind.STOCK_RELEASE: "stockRelease",
    SagaCommandKind.DESPATCH_CREATE: "despatchCreate",
    SagaCommandKind.CREDIT_HOLD: "creditHold",
    SagaCommandKind.INVOICE_ISSUE: "invoiceIssue",
    SagaCommandKind.CREDIT_RELEASE: "creditRelease",
}


def channel_address(channel_id: str) -> str:
    document: dict[str, Any] = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    address = document["channels"][channel_id]["address"]
    assert isinstance(address, str)
    return address


def test_the_three_consumed_topics_equal_the_asyncapi_fact_channel_addresses() -> None:
    assert len(SAGA_FACT_TOPICS) == 3
    for channel_id, topic in zip(TOPIC_CHANNELS, SAGA_FACT_TOPICS, strict=True):
        assert channel_address(channel_id) == topic, (
            f"channel {channel_id}: the topic the saga consumes is not the spec's address"
        )


def test_the_six_saga_subjects_equal_the_asyncapi_channel_addresses() -> None:
    assert set(SAGA_SUBJECTS) == set(SagaCommandKind) == set(SUBJECT_CHANNELS)
    for kind, channel_id in SUBJECT_CHANNELS.items():
        assert channel_address(channel_id) == SAGA_SUBJECTS[kind], (
            f"channel {channel_id}: the subject used for {kind.value} is not the spec's address"
        )


def test_the_command_kind_tokens_are_the_stored_wire_tokens() -> None:
    assert {kind.value for kind in SagaCommandKind} == {
        "stock.reserve",
        "stock.release",
        "despatch.create",
        "credit.hold",
        "invoice.issue",
        "credit.release",
    }
    assert max(len(kind.value) for kind in SagaCommandKind) == 15, "fits varchar(30)"
