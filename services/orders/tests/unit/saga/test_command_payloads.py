"""`build_command_payload`: the request of each saga command from the LOADED AGGREGATE.

R19, R20, design 9.4.

The fixture order has two lines of distinct products, quantities and prices, a non-round
`total_amount` distinct from `initial_amount` and `initial_discount`, and none of the three is
contained in another, so a field read from the wrong place cannot coincide with the right one.
"""

from collections.abc import Callable

import pytest

from otc_contracts import to_wire_json
from otc_contracts.generated.asyncapi import (
    CreditHoldRequestPayload,
    CreditReleaseRequestPayload,
    DespatchCreateRequestPayload,
    InvoiceIssueRequestPayload,
    Reason4,
    StockReleaseRequestPayload,
    StockReserveRequestPayload,
)
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.command_payloads import (
    UnsupportedReleaseTriggerError,
    build_command_payload,
)
from otc_orders.application.saga.fact import SagaFact
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus


def test_stock_reserve_has_exactly_one_line_per_order_line_with_the_right_units(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.PLACED)

    payload = build_command_payload(
        SagaCommandKind.STOCK_RESERVE, order, make_fact("order.placed.v1")
    )

    assert isinstance(payload, StockReserveRequestPayload)
    assert payload.order_reference == "ORD-000007"
    assert (payload.retailer_code, payload.company_code) == ("RET-01", "CMP-01")
    assert [(line.product_code, line.units) for line in payload.lines] == [
        ("SKU-A", 3),
        ("SKU-B", 2),
    ]


def test_credit_hold_amount_is_the_total_not_the_initial_amount_or_the_discount(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.STOCK_RESERVED)
    assert (
        order.initial_amount.amount,
        order.initial_discount.amount,
        order.total_amount.amount,
    ) == (8465, 350, 8115), "the fixture's three amounts are pairwise distinct"

    payload = build_command_payload(
        SagaCommandKind.CREDIT_HOLD, order, make_fact("stock.reserved.v1")
    )

    assert isinstance(payload, CreditHoldRequestPayload)
    assert (payload.amount.amount, payload.amount.currency) == (8115, "EUR")
    assert type(payload.amount.amount) is int
    assert payload.order_reference == "ORD-000007"


def test_invoice_issue_lines_carry_units_and_unit_price_and_the_initial_discount(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.DESPATCHED)

    payload = build_command_payload(
        SagaCommandKind.INVOICE_ISSUE, order, make_fact("order.despatched.v1")
    )

    assert isinstance(payload, InvoiceIssueRequestPayload)
    assert [(line.product_code, line.units, line.unit_price) for line in payload.lines] == [
        ("SKU-A", 3, 1999),
        ("SKU-B", 2, 1234),
    ]
    assert payload.discount == 350
    assert payload.currency == "EUR"
    assert (payload.retailer_code, payload.company_code) == ("RET-01", "CMP-01")


def test_despatch_create_and_credit_release_carry_the_aggregates_reference(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.CONFIRMED)
    fact = make_fact("credit.approved.v1")

    despatch = build_command_payload(SagaCommandKind.DESPATCH_CREATE, order, fact)
    release = build_command_payload(SagaCommandKind.CREDIT_RELEASE, order, fact)

    assert isinstance(despatch, DespatchCreateRequestPayload)
    assert despatch.order_reference == "ORD-000007"
    assert isinstance(release, CreditReleaseRequestPayload)
    assert (release.order_reference, release.retailer_code, release.company_code) == (
        "ORD-000007",
        "RET-01",
        "CMP-01",
    )


def test_stock_release_is_owed_by_credit_rejected_with_that_reason(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    payload = build_command_payload(
        SagaCommandKind.STOCK_RELEASE,
        order_in(OrderStatus.STOCK_RESERVED),
        make_fact("credit.rejected.v1"),
    )

    assert isinstance(payload, StockReleaseRequestPayload)
    assert payload.reason is Reason4.credit_rejected
    assert payload.order_reference == "ORD-000007"


@pytest.mark.parametrize(
    "event_type",
    [
        "order.placed.v1",
        "stock.reserved.v1",
        "stock.released.v1",
        "credit.approved.v1",
        "order.despatched.v1",
    ],
)
def test_stock_release_owed_by_any_fact_but_credit_rejected_raises(
    event_type: str, order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    with pytest.raises(UnsupportedReleaseTriggerError, match=event_type):
        build_command_payload(
            SagaCommandKind.STOCK_RELEASE,
            order_in(OrderStatus.STOCK_RESERVED),
            make_fact(event_type),
        )


def test_every_payload_serialises_through_the_one_serializer_as_compact_camel_case_json(
    order_in: Callable[..., Order], make_fact: Callable[..., SagaFact]
) -> None:
    order = order_in(OrderStatus.PLACED)
    text = to_wire_json(
        build_command_payload(SagaCommandKind.CREDIT_HOLD, order, make_fact("stock.reserved.v1"))
    )
    assert text == (
        '{"orderReference":"ORD-000007","retailerCode":"RET-01","companyCode":"CMP-01",'
        '"amount":{"amount":8115,"currency":"EUR"}}'
    )
