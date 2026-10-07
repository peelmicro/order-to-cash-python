"""`orders.create` on the wire (feature 15): request decoding, the command, the reply, the errors.

Pure: no broker, no database. The reply fixture uses three pairwise-distinct, non-zero money values
(2500 / 50 / 2450); swapping any two fields of the reply mapping fails
`test_the_reply_maps_each_money_field_from_its_own_source`.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_contracts.generated.asyncapi import Code
from otc_orders.application.commands.place_order import (
    OrderDiscountNotSupportedError,
    PlaceOrderError,
    PlaceOrderResult,
    ReferenceDataNotFoundError,
    StockUnavailableError,
)
from otc_orders.application.ports.stock_availability import (
    StockAvailabilityLineResult,
    StockCheckBusinessError,
    StockCheckError,
    StockCheckTimeoutError,
    StockCheckTransportError,
)
from otc_orders.infrastructure.persistence.range_guards import QuantityOutOfRangeError
from otc_orders.presentation.orders_create import (
    InvalidOrdersCreateRequestError,
    decode_request,
    encode,
    map_error,
    to_command,
    to_reply,
)
from otc_shared_kernel import DomainError, Money, OrderNumber, Quantity, UniqueId

AT = datetime(2026, 10, 6, 9, 15, 30, 987000, tzinfo=UTC)
SUBJECT = "fulfillment.stock.check"


def request_body(**changes: Any) -> bytes:
    body = {
        "requestId": str(uuid.UUID("11111111-2222-4333-8444-555555555555")),
        "retailerCode": "RET-01",
        "companyCode": "CMP-01",
        "currency": "EUR",
        "lines": [
            {"productCode": "SKU-A", "quantity": 3, "unitPrice": 1999, "lineDiscount": 250},
            {"productCode": "SKU-B", "quantity": 2},
        ],
        "orderDiscount": 0,
        "notes": "dock 4",
    } | changes
    return json.dumps({k: v for k, v in body.items() if v is not None}).encode()


def test_a_request_decodes_into_a_command_keeping_absent_prices_absent() -> None:
    command = to_command(decode_request(request_body()))

    assert command.request_id == uuid.UUID("11111111-2222-4333-8444-555555555555")
    assert (command.retailer_code, command.company_code, command.currency) == (
        "RET-01",
        "CMP-01",
        "EUR",
    )
    assert [(x.product_code, x.quantity, x.unit_price, x.line_discount) for x in command.lines] == [
        ("SKU-A", Quantity(3), 1999, 250),
        ("SKU-B", Quantity(2), None, None),
    ]
    assert (command.order_discount, command.notes) == (0, "dock 4")


def test_a_minimal_request_leaves_the_optional_fields_none() -> None:
    body = request_body(requestId=None, orderDiscount=None, notes=None)

    command = to_command(decode_request(body))

    assert (command.request_id, command.order_discount, command.notes) == (None, None, None)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (request_body(retailerCode=""), "orders.create request is invalid: retailerCode."),
        (request_body(retailerCode="R" * 21), "orders.create request is invalid: retailerCode."),
        (request_body(retailerCode="  "), "orders.create request is invalid: blank retailerCode."),
        (request_body(companyCode=""), "orders.create request is invalid: companyCode."),
        (request_body(companyCode="C" * 21), "orders.create request is invalid: companyCode."),
        (request_body(companyCode="  "), "orders.create request is invalid: blank companyCode."),
        (
            request_body(lines=[{"productCode": "", "quantity": 1}]),
            "orders.create request is invalid: lines.0.productCode.",
        ),
        (
            request_body(lines=[{"productCode": "P" * 31, "quantity": 1}]),
            "orders.create request is invalid: lines.0.productCode.",
        ),
        (
            request_body(lines=[{"productCode": "  ", "quantity": 1}]),
            "orders.create request is invalid: blank lines.0.productCode.",
        ),
        (request_body(currency="eur"), "orders.create request is invalid: currency."),
        (request_body(lines=[]), "orders.create request is invalid: lines."),
        (
            request_body(lines=[{"productCode": "SKU-A", "quantity": 0}]),
            "orders.create request is invalid: lines.0.quantity.",
        ),
        (b"not json", "orders.create request is invalid: (body)."),
    ],
)
def test_a_request_that_breaks_the_wire_contract_names_exactly_what_it_broke(
    body: bytes, message: str
) -> None:
    with pytest.raises(InvalidOrdersCreateRequestError) as refused:
        decode_request(body)

    assert str(refused.value) == message


def result(**changes: Any) -> PlaceOrderResult:
    fields: dict[str, Any] = {
        "order_id": UniqueId(uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")),
        "order_reference": OrderNumber("ORD-000123"),
        "currency": "EUR",
        "initial_amount": Money(2500, "EUR"),
        "initial_discount": Money(50, "EUR"),
        "total_amount": Money(2450, "EUR"),
        "order_date": AT,
    }
    return PlaceOrderResult(**(fields | changes))


def test_the_reply_maps_each_money_field_from_its_own_source() -> None:
    values = (2500, 50, 2450)
    assert len(set(values)) == 3  # the fixture cannot satisfy a swap
    assert 0 not in values

    reply = to_reply(result())

    assert reply.initial_amount == 2500
    assert reply.initial_discount == 50
    assert reply.total_amount == 2450


@pytest.mark.parametrize("currency", ["JPY", "KWD", "EUR"])
def test_the_reply_carries_the_currency_of_the_result_not_a_constant(currency: str) -> None:
    # distinct amounts, so the money check holds too; the currency is the only thing that varies
    placed = result(
        currency=currency,
        initial_amount=Money(7000, currency),
        initial_discount=Money(300, currency),
        total_amount=Money(6700, currency),
    )

    reply = to_reply(placed)

    assert reply.currency == currency
    assert (reply.initial_amount, reply.initial_discount, reply.total_amount) == (7000, 300, 6700)
    assert json.loads(encode(reply))["currency"] == currency


def test_the_reply_wire_form_is_compact_camel_case_with_a_millisecond_instant() -> None:
    wire = encode(to_reply(result())).decode()

    assert wire == (
        '{"orderId":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","orderReference":"ORD-000123",'
        '"status":"placed","currency":"EUR","initialAmount":2500,"initialDiscount":50,'
        '"totalAmount":2450,"orderDate":"2026-10-06T09:15:30.987Z"}'
    )


def mapped(error: Exception) -> dict[str, Any]:
    wire: dict[str, Any] = json.loads(encode(map_error(error, AT)))
    assert wire["occurredAt"] == "2026-10-06T09:15:30.987Z"
    return wire


def test_a_wire_shape_refusal_is_validation_failed_without_details() -> None:
    wire = mapped(InvalidOrdersCreateRequestError("orders.create request is invalid: lines."))

    assert wire["code"] == "VALIDATION_FAILED"
    assert "details" not in wire


def test_a_shortage_is_stock_unavailable_with_the_short_lines_in_the_shortage_shape() -> None:
    error = StockUnavailableError((StockAvailabilityLineResult("SKU-B", 2, 1, False),))

    wire = mapped(error)

    assert wire["code"] == "STOCK_UNAVAILABLE"
    assert wire["details"] == {
        "shortages": [{"productCode": "SKU-B", "requested": 2, "available": 1}]
    }


def test_a_stock_check_timeout_is_timeout_with_the_subject_and_the_budget() -> None:
    wire = mapped(StockCheckTimeoutError(SUBJECT, 1500))

    assert (wire["code"], wire["details"]) == (
        "TIMEOUT",
        {"subject": SUBJECT, "timeoutMs": 1500},
    )


def test_a_stock_check_transport_failure_is_unavailable_with_the_subject() -> None:
    wire = mapped(StockCheckTransportError(SUBJECT, "no responder is subscribed"))

    assert (wire["code"], wire["details"]) == ("UNAVAILABLE", {"subject": SUBJECT})


def test_the_two_transport_failures_never_map_to_the_same_code() -> None:
    timeout = map_error(StockCheckTimeoutError(SUBJECT, 1), AT).code
    transport = map_error(StockCheckTransportError(SUBJECT, "x"), AT).code
    assert {timeout, transport} == {Code.timeout, Code.unavailable}


@pytest.mark.parametrize("code", [c.value for c in Code])
def test_a_responder_error_with_a_wire_code_passes_through_with_its_message(code: str) -> None:
    wire = mapped(StockCheckBusinessError(SUBJECT, code, "the responder's words"))

    assert (wire["code"], wire["message"], wire["details"]) == (
        code,
        "the responder's words",
        {"subject": SUBJECT},
    )


def test_a_responder_error_with_a_code_outside_the_wire_enum_is_unavailable_carrying_it() -> None:
    wire = mapped(StockCheckBusinessError(SUBJECT, "WAREHOUSE_ON_FIRE", "boom"))

    assert wire["code"] == "UNAVAILABLE"
    assert wire["details"] == {"subject": SUBJECT, "responderCode": "WAREHOUSE_ON_FIRE"}


def test_unknown_reference_data_is_not_found_with_field_and_value() -> None:
    wire = mapped(ReferenceDataNotFoundError("retailerCode", "NOPE"))

    assert (wire["code"], wire["details"]) == (
        "NOT_FOUND",
        {"field": "retailerCode", "value": "NOPE"},
    )


def test_an_order_discount_is_validation_failed_without_details() -> None:
    wire = mapped(OrderDiscountNotSupportedError(150, "EUR"))

    assert wire["code"] == "VALIDATION_FAILED"
    assert "details" not in wire


@pytest.mark.parametrize(
    ("amount", "currency", "text"),
    [(150, "EUR", "1.50 EUR"), (150, "JPY", "150 JPY"), (1500, "KWD", "1.500 KWD")],
)
def test_the_order_discount_message_is_scaled_by_the_currency_exponent_never_raw_minor_units(
    amount: int, currency: str, text: str
) -> None:
    message = mapped(OrderDiscountNotSupportedError(amount, currency))["message"]

    assert message.startswith(f"orderDiscount {text} was supplied, but the Order aggregate")


def test_any_other_application_refusal_is_validation_failed() -> None:
    assert mapped(PlaceOrderError("something the client did"))["code"] == "VALIDATION_FAILED"


def test_a_domain_error_is_validation_failed_with_its_code_under_the_key_code() -> None:
    wire = mapped(DomainError("order.total_must_not_be_negative", "total below zero"))

    assert wire["code"] == "VALIDATION_FAILED"
    assert wire["details"] == {"code": "order.total_must_not_be_negative"}
    assert wire["message"] == "total below zero"


def test_a_storage_range_refusal_is_a_domain_error_too() -> None:
    error = QuantityOutOfRangeError("order_items.quantity", 2**31, 1, 2**31 - 1)

    assert mapped(error)["details"] == {"code": "quantity.out_of_range"}


def test_an_unexpected_exception_is_internal_error_and_never_leaks_its_text() -> None:
    wire = mapped(RuntimeError("SELECT secret FROM vault -- /home/app/.pgpass"))

    assert wire["code"] == "INTERNAL_ERROR"
    assert "vault" not in wire["message"]
    assert ".pgpass" not in wire["message"]
    assert "details" not in wire


def test_a_stock_check_error_of_an_unclassified_kind_is_unavailable_not_internal_error() -> None:
    wire = mapped(StockCheckError(SUBJECT, "unclassified"))

    assert (wire["code"], wire["details"]) == ("UNAVAILABLE", {"subject": SUBJECT})
