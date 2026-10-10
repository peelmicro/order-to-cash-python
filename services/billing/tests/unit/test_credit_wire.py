"""Results -> reply models -> bytes (task E4; L21, L22). The reply key sets are parsed from the
bytes `to_wire_json` produced, never from the model: an absent optional field is OMITTED.

Loop scope: nothing here is async.
"""

import json
from typing import Any

from otc_billing.application.messages import (
    CreditPage,
    CreditViewData,
    HoldOutcomeKind,
    HoldResult,
    ReleaseResult,
)
from otc_billing.domain.reasons import CreditRejectionReason
from otc_billing.presentation import credit_wire
from otc_contracts import from_wire_json
from otc_contracts.generated import asyncapi


def keys_of(model: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(credit_wire.encode(model))
    return parsed


def test_an_approved_hold_carries_held_amount_and_no_reason() -> None:
    reply = keys_of(
        credit_wire.hold_reply(
            HoldResult(
                outcome=HoldOutcomeKind.APPROVED,
                order_reference="ORD-000101",
                credit_code="CR-000321",
                currency="EUR",
                held_amount=250,
                available_credit=450,
                reason=None,
            )
        )
    )
    assert reply["outcome"] == "approved"
    assert reply == {
        "outcome": "approved",
        "orderReference": "ORD-000101",
        "creditCode": "CR-000321",
        "currency": "EUR",
        "heldAmount": 250,
        "availableCredit": 450,
    }, "an approved reply has no `reason` key"


def test_a_rejected_hold_carries_a_reason_and_no_held_amount() -> None:
    reply = keys_of(
        credit_wire.hold_reply(
            HoldResult(
                outcome=HoldOutcomeKind.REJECTED,
                order_reference="ORD-000101",
                credit_code="CR-000321",
                currency="EUR",
                held_amount=None,
                available_credit=700,
                reason=CreditRejectionReason.SIMULATED_CENTS_RULE,
            )
        )
    )
    assert reply["outcome"] == "rejected"
    assert "heldAmount" not in reply, "a rejected reply has no `heldAmount` key"
    assert reply["reason"] == "simulated_cents_rule"
    assert reply["availableCredit"] == 700


def test_already_held_carries_the_recorded_held_amount_and_the_current_available_credit() -> None:
    reply = keys_of(
        credit_wire.hold_reply(
            HoldResult(
                outcome=HoldOutcomeKind.ALREADY_HELD,
                order_reference="ORD-000101",
                credit_code="CR-000321",
                currency="EUR",
                held_amount=300,  # the RECORDED hold
                available_credit=1000,  # the CURRENT credit (a different number)
                reason=None,
            )
        )
    )
    assert reply["outcome"] == "already_held"
    assert (reply["heldAmount"], reply["availableCredit"]) == (300, 1000)
    assert "reason" not in reply


def test_a_zero_held_amount_is_written_not_omitted() -> None:
    reply = keys_of(
        credit_wire.hold_reply(
            HoldResult(
                outcome=HoldOutcomeKind.APPROVED,
                order_reference="ORD-000101",
                credit_code="CR-000321",
                currency="EUR",
                held_amount=0,
                available_credit=1000,
                reason=None,
            )
        )
    )
    assert reply["heldAmount"] == 0


def test_a_release_reply_both_ways() -> None:
    released = keys_of(
        credit_wire.release_reply(
            ReleaseResult(
                released=True,
                order_reference="ORD-000101",
                credit_code="CR-000321",
                currency="EUR",
                released_amount=250,
                available_credit_after=1000,
            )
        )
    )
    assert released["released"] is True
    assert released == {
        "released": True,
        "orderReference": "ORD-000101",
        "creditCode": "CR-000321",
        "currency": "EUR",
        "releasedAmount": 250,
        "availableCreditAfter": 1000,
    }
    repeat = keys_of(
        credit_wire.release_reply(
            ReleaseResult(
                released=False,
                order_reference="ORD-000101",
                credit_code="CR-000321",
                currency="EUR",
                released_amount=None,
                available_credit_after=1000,
            )
        )
    )
    assert repeat["released"] is False
    assert "releasedAmount" not in repeat, "released: false has no `releasedAmount` key"
    assert repeat["availableCreditAfter"] == 1000


def test_a_list_reply_carries_the_page_and_every_view_field() -> None:
    payload = credit_wire.encode(
        credit_wire.list_reply(
            CreditPage(
                items=(
                    CreditViewData(
                        credit_code="CR-000321",
                        retailer_code="RETAIL-77",
                        company_code="SUPPLY-CO",
                        currency="EUR",
                        credit_limit=1000,
                        active_holds=250,
                        open_exposure=100,
                        available_credit=650,
                    ),
                ),
                page=2,
                page_size=10,
                total=11,
            )
        )
    )
    decoded = from_wire_json(asyncapi.CreditListReplyPayload, payload)
    assert (decoded.page.page, decoded.page.page_size, decoded.page.total) == (2, 10, 11)
    [item] = decoded.items
    assert (item.active_holds, item.open_exposure, item.available_credit) == (250, 100, 650)
    assert item.credit_limit == 1000
    assert (item.credit_code, item.retailer_code, item.company_code) == (
        "CR-000321",
        "RETAIL-77",
        "SUPPLY-CO",
    )
