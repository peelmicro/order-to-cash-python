"""The five NATS subjects Fulfillment answers equal the channel addresses of `asyncapi.yaml` (F1).

Ported from #8's `StockSubjectsTests` and Orders' `test_rpc_subjects.py`. Every other test addresses
NATS by a hand-typed literal, so without this a drift between the spec and the code AND those tests
would stay green. The channels are found by their channel id in the parsed document, never by
grepping for the literal.
"""

from pathlib import Path
from typing import Any

import yaml

from otc_fulfillment.infrastructure.messaging.subjects import (
    STOCK_CHECK_SUBJECT,
    STOCK_LIST_SUBJECT,
    STOCK_RELEASE_SUBJECT,
    STOCK_REPLENISH_SUBJECT,
    STOCK_RESERVE_SUBJECT,
)

ASYNCAPI = Path(__file__).resolve().parents[4] / "specs" / "shared" / "asyncapi.yaml"

CHANNELS = {
    "stockCheck": STOCK_CHECK_SUBJECT,
    "stockReserve": STOCK_RESERVE_SUBJECT,
    "stockRelease": STOCK_RELEASE_SUBJECT,
    "stockList": STOCK_LIST_SUBJECT,
    "stockReplenish": STOCK_REPLENISH_SUBJECT,
}


def channel_address(channel_id: str) -> str:
    document: dict[str, Any] = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    address = document["channels"][channel_id]["address"]
    assert isinstance(address, str)
    return address


def test_f1_each_of_the_five_subjects_is_the_address_of_its_asyncapi_channel() -> None:
    assert len(CHANNELS) == 5
    for channel_id, subject in CHANNELS.items():
        assert channel_address(channel_id) == subject, (
            f"channel {channel_id}: the subject Fulfillment answers is not the spec's address"
        )


def test_f1_the_five_subjects_are_pairwise_distinct() -> None:
    assert len(set(CHANNELS.values())) == 5
