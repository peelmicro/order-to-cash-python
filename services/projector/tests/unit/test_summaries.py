"""C2 / PR16, PR46: the fourteen summaries, each asserted as the WHOLE string.

Every expected string is #7's (`../order-to-cash-nestjs/apps/projector/src/domain/summaries.ts`
lines 29-114, the line cited beside each case) and, where the seed fabricates the same fact, the
seed's own (`services/seed/src/otc_seed/domain/data/sagas.py:510-566, 824-854`); the two agree for
every one of them (no disagreement to record). Money cases cover three exponents, a negative amount
and a value past 2**53 (the money path is integer `divmod`, never `/`).
"""

from collections.abc import Callable
from typing import Any

import pytest

from otc_projector.application import summaries

RESERVATION_1 = "11111111-1111-4111-8111-111111111111"
RESERVATION_2 = "22222222-2222-4222-8222-222222222222"
STEP_EVENT = "33333333-3333-4333-8333-333333333333"
RELEASED = [
    {"reservation_id": RESERVATION_1, "product_code": "WIDGET-R1", "units": 6},
    {"reservation_id": RESERVATION_2, "product_code": "WIDGET-R2", "units": 7},
]


def payload(facts: Any, event_type: str, **overrides: Any) -> Any:
    return facts.build(event_type, payload=overrides).payload


def test_pr16_order_placed(facts: Any) -> None:  # summaries.ts:30
    assert summaries.order_placed(payload(facts, "order.placed.v1")).text == (
        "Order ORD-000101 placed for ACME"
    )


def test_pr16_stock_reserved(facts: Any) -> None:  # summaries.ts:34
    assert summaries.stock_reserved(payload(facts, "stock.reserved.v1")).text == (
        "Stock reserved for 2 line(s)"
    )


def test_pr16_stock_rejected(facts: Any) -> None:  # summaries.ts:38-45
    result = summaries.stock_rejected(payload(facts, "stock.rejected.v1", reason="unknown_product"))
    assert result.text == "Stock rejected: 11 unit(s) short on WIDGET-S1"
    assert result.detail == {
        "shortages": [
            {"productCode": "WIDGET-S1", "requested": 9, "available": 2},
            {"productCode": "WIDGET-S2", "requested": 5, "available": 1},
        ],
        "reason": "unknown_product",
    }


def test_pr16_stock_released_without_the_compensation_suffix(facts: Any) -> None:  # :48-55
    result = summaries.stock_released(payload(facts, "stock.released.v1", released=RELEASED))
    assert result.text == "13 unit(s) released back to stock"
    assert result.detail == {
        "released": [
            {"reservationId": RESERVATION_1, "productCode": "WIDGET-R1", "units": 6},
            {"reservationId": RESERVATION_2, "productCode": "WIDGET-R2", "units": 7},
        ],
        "reason": "order_cancelled",
    }


def test_pr16_stock_released_with_the_compensation_suffix_for_a_credit_rejection(
    facts: Any,
) -> None:  # :50
    result = summaries.stock_released(payload(facts, "stock.released.v1", reason="credit_rejected"))
    assert result.text == "13 unit(s) released back to stock (compensation)"
    assert result.detail is not None
    assert result.detail["reason"] == "credit_rejected"


def test_pr16_credit_approved(facts: Any) -> None:  # :58
    assert summaries.credit_approved(payload(facts, "credit.approved.v1")).text == (
        "Credit hold of 92.45 EUR approved"
    )


def test_pr16_credit_rejected(facts: Any) -> None:  # :62-67
    result = summaries.credit_rejected(
        payload(facts, "credit.rejected.v1", reason="simulated_cents_rule")
    )
    assert result.text == "Credit hold of 5 000 JPY rejected (simulated_cents_rule)"
    assert result.detail == {"reason": "simulated_cents_rule", "requestedAmount": 5000}


@pytest.mark.parametrize(
    ("reason", "suffix"), [("invoice_paid", "invoice paid"), ("order_cancelled", "order cancelled")]
)
def test_pr16_credit_released_for_each_reason(facts: Any, reason: str, suffix: str) -> None:  # :70
    result = summaries.credit_released(payload(facts, "credit.released.v1", reason=reason))
    assert result.text == f"Credit exposure released — {suffix}"


def test_pr16_order_confirmed(facts: Any) -> None:  # :75
    assert summaries.order_confirmed(payload(facts, "order.confirmed.v1")).text == (
        "Order confirmed (ORDRSP)"
    )


def test_pr16_order_despatched(facts: Any) -> None:  # :79
    assert summaries.order_despatched(payload(facts, "order.despatched.v1")).text == (
        "Despatch DES-000203 created"
    )


def test_pr16_invoice_issued(facts: Any) -> None:  # :83
    assert summaries.invoice_issued(payload(facts, "invoice.issued.v1")).text == (
        "Invoice INV-000304 issued"
    )


def test_pr16_payment_received(facts: Any) -> None:  # :87
    assert summaries.payment_received(payload(facts, "payment.received.v1")).text == (
        "Payment PAY-A-5001 received"
    )


def test_pr16_order_completed(facts: Any) -> None:  # :91
    assert summaries.order_completed(payload(facts, "order.completed.v1")).text == (
        "Order ORD-000112 completed"
    )


def test_pr16_order_cancelled(facts: Any) -> None:  # :95-101
    steps = [
        {
            "step": "stock_released",
            "event_id": STEP_EVENT,
            "event_type": "stock.released.v1",
            "occurred_at": "2026-03-11T12:00:00.123Z",
            "summary": "released stock",
        }
    ]
    result = summaries.order_cancelled(
        payload(
            facts,
            "order.cancelled.v1",
            cancellation_reason="operator_cancelled",
            compensation_steps=steps,
        )
    )
    assert result.text == "Order ORD-000113 cancelled (operator_cancelled)"
    assert result.detail == {
        "cancellationReason": "operator_cancelled",
        "compensationSteps": [
            {
                "step": "stock_released",
                "eventId": STEP_EVENT,
                "eventType": "stock.released.v1",
                "occurredAt": "2026-03-11T12:00:00.123Z",
                "summary": "released stock",
            }
        ],
    }


def test_pr16_order_saga_failed(facts: Any) -> None:  # :107-113
    result = summaries.order_saga_failed(payload(facts, "order.saga_failed.v1"))
    assert result.text == 'Saga command "reserve_stock" dead-lettered after 5 attempt(s)'
    assert result.detail == {
        "command": "reserve_stock",
        "attempts": 5,
        "lastError": "connection refused",
    }


@pytest.mark.parametrize(
    ("amount", "currency", "text"),
    [
        (9245, "EUR", "92.45 EUR"),
        (5000, "JPY", "5 000 JPY"),
        (12345, "BHD", "12.345 BHD"),
        (-9245, "EUR", "-92.45 EUR"),
        (2**62, "EUR", "46 116 860 184 273 879.04 EUR"),
    ],
)
def test_pr16_money_is_formatted_with_the_iso_4217_exponent_by_integer_arithmetic(
    facts: Any, amount: int, currency: str, text: str
) -> None:
    result = summaries.credit_approved(
        payload(facts, "credit.approved.v1", held_amount=amount, currency=currency)
    )
    assert result.text == f"Credit hold of {text} approved"


def test_pr16_detail_is_present_only_for_the_five_named_facts(facts: Any) -> None:
    builders: dict[str, Callable[[Any], summaries.Summary]] = {
        "order.placed.v1": summaries.order_placed,
        "stock.reserved.v1": summaries.stock_reserved,
        "stock.rejected.v1": summaries.stock_rejected,
        "stock.released.v1": summaries.stock_released,
        "credit.approved.v1": summaries.credit_approved,
        "credit.rejected.v1": summaries.credit_rejected,
        "credit.released.v1": summaries.credit_released,
        "order.confirmed.v1": summaries.order_confirmed,
        "order.despatched.v1": summaries.order_despatched,
        "invoice.issued.v1": summaries.invoice_issued,
        "payment.received.v1": summaries.payment_received,
        "order.completed.v1": summaries.order_completed,
        "order.cancelled.v1": summaries.order_cancelled,
        "order.saga_failed.v1": summaries.order_saga_failed,
    }
    five = {
        "stock.rejected.v1",
        "stock.released.v1",
        "credit.rejected.v1",
        "order.cancelled.v1",
        "order.saga_failed.v1",
    }
    with_detail = {
        event_type
        for event_type, build in builders.items()
        if build(facts.build(event_type).payload).detail is not None
    }
    assert len(builders) == 14
    assert with_detail == five
