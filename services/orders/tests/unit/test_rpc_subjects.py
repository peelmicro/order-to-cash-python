"""The NATS subjects the Orders service uses equal the channel addresses of `asyncapi.yaml`.

Ported from #8's `RpcSubjectsTests`. Every other test addresses NATS by a hand-typed literal, so
without this a drift between the spec and the code AND those tests would stay green. The channels
are found by their channel id in the parsed document, never by grepping for the literal.
"""

from pathlib import Path
from typing import Any

import yaml

from otc_orders.infrastructure.messaging.subjects import (
    ORDERS_CREATE_SUBJECT,
    STOCK_CHECK_SUBJECT,
)

ASYNCAPI = Path(__file__).resolve().parents[4] / "specs" / "shared" / "asyncapi.yaml"


def channel_address(channel_id: str) -> str:
    document: dict[str, Any] = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    address = document["channels"][channel_id]["address"]
    assert isinstance(address, str)
    return address


def test_the_orders_create_subject_is_the_address_of_the_orders_create_channel() -> None:
    assert channel_address("ordersCreate") == ORDERS_CREATE_SUBJECT, (
        "channel ordersCreate: the subject Orders answers is not the spec's address"
    )


def test_the_stock_check_subject_is_the_address_of_the_stock_check_channel() -> None:
    assert channel_address("stockCheck") == STOCK_CHECK_SUBJECT, (
        "channel stockCheck: the subject Orders calls is not the spec's address"
    )
