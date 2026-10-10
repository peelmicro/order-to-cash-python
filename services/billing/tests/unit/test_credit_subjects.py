"""The six NATS subjects Billing answers equal the channel addresses of `asyncapi.yaml` (tasks E2).

Every other test addresses NATS by a hand-typed literal, so without this a drift between the spec
and the code AND those tests would stay green. The channels are found by their channel id in the
parsed document, never by grepping for the literal. The responder's route table equals exactly these
six subjects (subject coverage, BI31); the population is `ROUTES` and `CHANNELS`, not a count.

Loop scope: nothing here is async.
"""

from pathlib import Path
from typing import Any

import yaml

from otc_billing.infrastructure.messaging.subjects import (
    CREDIT_HOLD_SUBJECT,
    CREDIT_LIST_SUBJECT,
    CREDIT_RELEASE_SUBJECT,
    INVOICE_ISSUE_SUBJECT,
    INVOICE_LIST_SUBJECT,
    PAYMENT_REGISTER_SUBJECT,
)
from otc_billing.presentation.credit_responder import ROUTES

ASYNCAPI = Path(__file__).resolve().parents[4] / "specs" / "shared" / "asyncapi.yaml"

CHANNELS = {
    "creditHold": CREDIT_HOLD_SUBJECT,
    "creditRelease": CREDIT_RELEASE_SUBJECT,
    "creditList": CREDIT_LIST_SUBJECT,
    "invoiceIssue": INVOICE_ISSUE_SUBJECT,
    "invoiceList": INVOICE_LIST_SUBJECT,
    "paymentRegister": PAYMENT_REGISTER_SUBJECT,
}


def channel_address(channel_id: str) -> str:
    document: dict[str, Any] = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    address = document["channels"][channel_id]["address"]
    assert isinstance(address, str)
    return address


def test_each_of_the_six_subjects_is_the_address_of_its_asyncapi_channel() -> None:
    assert len(CHANNELS) == 6
    for channel_id, subject in CHANNELS.items():
        assert channel_address(channel_id) == subject, (
            f"channel {channel_id}: the subject Billing answers is not the spec's address"
        )


def test_the_six_subjects_are_pairwise_distinct_and_are_exactly_the_route_table() -> None:
    assert len(set(CHANNELS.values())) == 6
    assert set(ROUTES) == {channel_address(c) for c in CHANNELS}
    assert set(ROUTES) == set(CHANNELS.values())
    assert len(ROUTES) == 6
