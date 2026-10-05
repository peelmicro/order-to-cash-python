"""Feature 8 acceptance item 2: the ONE serializer configuration, one claim per test.

camelCase through one alias mechanism, compact JSON, non-ASCII raw, `.mmmZ` instants, None decided
per field against the spec, and integers strict when parsing.
"""

import ast
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError

from otc_contracts import format_instant, from_wire_json, to_wire_json
from otc_contracts.generated import asyncapi, openapi
from otc_contracts.generated.asyncapi import (
    CancellationReason,
    Envelope,
    InvoiceStatus,
    InvoiceView,
    Money,
    OrderCancelledPayload,
    OrderLine,
    OrderPlacedPayload,
)
from otc_contracts.generated.nullable import NULLABLE_FIELDS
from otc_contracts.generated.openapi import OrderReferences
from otc_contracts.wire import WireModel

GENERATED_DIR = Path(asyncapi.__file__).parent


# ----------------------------------------------------------------------------- the Instant format
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 8, 30, 16, 20, 20, 442000, tzinfo=UTC), "2026-08-30T16:20:20.442Z"),
        (datetime(2026, 8, 30, 16, 20, 20, 0, tzinfo=UTC), "2026-08-30T16:20:20.000Z"),
        (datetime(2026, 8, 30, 16, 20, 20, 7000, tzinfo=UTC), "2026-08-30T16:20:20.007Z"),
        # sub-millisecond precision is truncated, not rounded (.fff in #8, toISOString in #7)
        (datetime(2026, 8, 30, 16, 20, 20, 442999, tzinfo=UTC), "2026-08-30T16:20:20.442Z"),
        (datetime(2026, 8, 30, 16, 20, 20, 999999, tzinfo=UTC), "2026-08-30T16:20:20.999Z"),
        # an aware non-UTC instant is converted to UTC
        (
            datetime(2026, 8, 30, 18, 20, 20, 442000, tzinfo=timezone(timedelta(hours=2))),
            "2026-08-30T16:20:20.442Z",
        ),
        (datetime(5, 1, 2, 3, 4, 5, tzinfo=UTC), "0005-01-02T03:04:05.000Z"),
    ],
)
def test_instant_is_written_as_yyyy_mm_ddthh_mm_ss_mmmz(value: datetime, expected: str) -> None:
    assert format_instant(value) == expected


def test_a_naive_datetime_has_no_instant_and_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        format_instant(datetime(2026, 8, 30, 16, 20, 20))


def test_pydantic_default_datetime_output_is_not_the_wire_format() -> None:
    """Evidence for why the writer formats instants itself: the library default writes
    microseconds (`.442000Z`), which would break byte-exactness on every golden."""

    class Holder(BaseModel):
        at: datetime

    default = Holder(at=datetime(2026, 8, 30, 16, 20, 20, 442000, tzinfo=UTC)).model_dump_json()
    assert default == '{"at":"2026-08-30T16:20:20.442000Z"}'


def test_the_serializer_writes_instants_inside_a_model_as_mmmz() -> None:
    line = from_wire_json(
        OrderPlacedPayload,
        '{"orderReference":"ORD-000011","retailerCode":"R","companyCode":"C",'
        '"buyerGln":"5400000000034","supplierGln":"5400000000386","currency":"EUR",'
        '"orderDate":"2026-08-30T18:20:20.442123+02:00","lines":[{"productCode":"P",'
        '"quantity":1,"unitPrice":1,"lineDiscount":0}],"initialAmount":1,'
        '"initialDiscount":0,"totalAmount":1}',
    )
    # parse accepts a non-UTC offset and sub-millisecond precision; write normalises both
    assert '"orderDate":"2026-08-30T16:20:20.442Z"' in to_wire_json(line)


def test_a_naive_instant_is_refused_when_parsing() -> None:
    with pytest.raises(ValidationError):
        from_wire_json(
            asyncapi.OrderCancelledEvent,
            '{"eventId":"6f69651a-46aa-4895-a70b-55a4804f405b","eventType":"order.cancelled.v1",'
            '"aggregateId":"28211434-b1a5-41ab-96ed-d5265e03913b",'
            '"correlationId":"28211434-b1a5-41ab-96ed-d5265e03913b",'
            '"causationId":"1760967f-161e-4ccd-9294-86c15dfe0b4e",'
            '"occurredAt":"2026-08-30T17:03:45.767","payload":{}}',
        )


# ------------------------------------------------------------------- compact JSON, raw non-ASCII
def test_output_is_compact_with_no_space_after_separators() -> None:
    assert (
        to_wire_json(Money(amount=124250, currency="EUR")) == '{"amount":124250,"currency":"EUR"}'
    )


def test_non_ascii_text_is_written_raw_not_as_u_escapes() -> None:
    line = OrderLine(
        product_code="PRD-0008",
        description="Líquido — 日本 ñ",
        quantity=1,
        unit_price=1,
        line_discount=0,
    )
    written = to_wire_json(line)
    assert "Líquido — 日本 ñ" in written
    assert "\\u" not in written


def test_pydantic_default_json_is_already_compact_and_raw_but_the_writer_does_not_rely_on_it() -> (
    None
):
    """Evidence: `model_dump_json` (2.13.5) writes compact separators and raw non-ASCII."""

    class Text(BaseModel):
        a: str
        b: int

    assert Text(a="é—日本", b=1).model_dump_json() == '{"a":"é—日本","b":1}'


# --------------------------------------------------------------------- ONE alias mechanism
def test_the_wire_is_camel_case_and_python_names_are_snake_case() -> None:
    line = OrderLine(
        product_code="P",
        quantity=1,
        unit_price=2,
        line_discount=3,
    )
    assert to_wire_json(line) == '{"productCode":"P","quantity":1,"unitPrice":2,"lineDiscount":3}'
    assert list(OrderLine.model_fields) == [
        "product_code",
        "description",
        "quantity",
        "unit_price",
        "line_discount",
    ]


def test_parsing_accepts_the_alias_only_never_the_snake_case_name() -> None:
    with pytest.raises(ValidationError):
        from_wire_json(
            OrderLine, '{"product_code":"P","quantity":1,"unit_price":2,"line_discount":3}'
        )


def _alias_keywords(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        f"{path.name}:{node.lineno} {node.arg}="
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword)
        and node.arg in {"alias", "validation_alias", "serialization_alias", "populate_by_name"}
    ]


@pytest.mark.parametrize("module", ["asyncapi.py", "openapi.py", "nullable.py"])
def test_no_generated_field_carries_its_own_alias(module: str) -> None:
    """The alias generator on `WireModel` is the ONLY mechanism; the generator runs `--no-alias`."""
    assert _alias_keywords(GENERATED_DIR / module) == []


def test_the_alias_generator_is_declared_exactly_once_in_the_package() -> None:
    package = GENERATED_DIR.parent
    sources = {p.name: p.read_text(encoding="utf-8") for p in package.glob("*.py")}
    assert [n for n, s in sources.items() if "alias_generator" in s] == ["wire.py"]
    assert WireModel.model_config["alias_generator"] is not None


# ------------------------------------------------------------------------------ None, per field
def test_a_not_required_field_that_is_none_is_absent_not_null() -> None:
    line = OrderLine(product_code="P", description=None, quantity=1, unit_price=1, line_discount=0)
    assert "description" not in to_wire_json(line)
    cancelled = OrderCancelledPayload.model_fields
    assert "note" in cancelled  # the optional field exists; None below must still be absent
    written = to_wire_json(
        OrderCancelledPayload(
            order_reference="ORD-000041",
            retailer_code="R",
            company_code="C",
            cancellation_reason=CancellationReason.credit_rejected,
            cancelled_at=datetime(2026, 1, 1, tzinfo=UTC),
            compensation_steps=[],
            note=None,
        )
    )
    assert "note" not in written
    assert "null" not in written


def test_a_nullable_field_that_is_none_is_written_as_an_explicit_null() -> None:
    assert '"paidAt":null' in to_wire_json(_invoice_view(paid_at=None))
    refs = to_wire_json(OrderReferences())
    assert refs == ('{"despatchReference":null,"invoiceReference":null,"paymentReference":null}')


def _invoice_view(paid_at: datetime | None) -> InvoiceView:
    return InvoiceView(
        invoice_id=UUID("11111111-1111-4111-8111-111111111111"),
        invoice_reference="INV-000027",
        invoice_date=datetime(2026, 1, 1, tzinfo=UTC),
        order_reference="ORD-000011",
        retailer_code="R",
        company_code="C",
        currency="EUR",
        amount=1,
        discount=0,
        total_amount=1,
        status=InvoiceStatus.issued,
        paid_at=paid_at,
    )


def test_a_set_nullable_field_keeps_its_value() -> None:
    written = to_wire_json(_invoice_view(paid_at=datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)))
    assert '"paidAt":"2026-01-02T03:04:05.678Z"' in written


def test_the_nullable_table_holds_exactly_these_fields() -> None:
    """The per-field table the serializer reads, as a literal (the spec test proves it equals the
    spec; this one pins what the serializer will do)."""
    assert {k: sorted(v) for k, v in NULLABLE_FIELDS.items()} == {
        "asyncapi.InvoiceView": ["paidAt"],
        "openapi.Invoice": ["paidAt"],
        "openapi.OrderDetail": ["cancellationReason"],
        "openapi.OrderReferences": ["despatchReference", "invoiceReference", "paymentReference"],
        "openapi.OrderStreamUpdate": ["cancellationReason"],
        "openapi.OrderSummary": ["cancellationReason"],
        "openapi.StreamReady": ["orderId"],
    }


def test_every_nullable_table_entry_names_a_real_generated_field() -> None:
    for key, names in NULLABLE_FIELDS.items():
        module_name, class_name = key.split(".")
        module = {"asyncapi": asyncapi, "openapi": openapi}[module_name]
        model: Any = getattr(module, class_name)
        wire_names = {_camel(n) for n in model.model_fields}
        assert set(names) <= wire_names, f"{key}: {names} not among {sorted(wire_names)}"


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p.title() for p in rest)


# ------------------------------------------------------------------------- integer strictness
VALID_LINE = '{{"productCode":"P","quantity":{q},"unitPrice":{u},"lineDiscount":{d}}}'


@pytest.mark.parametrize("bad", ['"8934"', "8934.0", "true", "false", "8934.5", "1e3", "null"])
@pytest.mark.parametrize("field", ["q", "u", "d"])
def test_a_money_or_quantity_integer_field_refuses_a_string_float_or_bool(
    field: str, bad: str
) -> None:
    values = {"q": "1", "u": "1", "d": "0"}
    values[field] = bad
    with pytest.raises(ValidationError):
        from_wire_json(OrderLine, VALID_LINE.format(**values))


def test_a_plain_integer_is_accepted_and_stays_an_int() -> None:
    line = from_wire_json(OrderLine, VALID_LINE.format(q="6", u="1489", d="0"))
    assert type(line.unit_price) is int
    assert line.unit_price == 1489


@pytest.mark.parametrize("amount", [str(2**63), str(-(2**63) - 1)])
def test_money_beyond_the_int64_the_spec_declares_is_refused(amount: str) -> None:
    with pytest.raises(ValidationError):
        from_wire_json(Money, f'{{"amount":{amount},"currency":"EUR"}}')


def test_the_int64_bounds_themselves_are_accepted() -> None:
    assert from_wire_json(Money, f'{{"amount":{2**63 - 1},"currency":"EUR"}}').amount == 2**63 - 1
    assert from_wire_json(Money, f'{{"amount":{-(2**63)},"currency":"EUR"}}').amount == -(2**63)


@pytest.mark.parametrize("quantity", ["0", "-1"])
def test_a_quantity_below_one_is_refused(quantity: str) -> None:
    with pytest.raises(ValidationError):
        from_wire_json(OrderLine, VALID_LINE.format(q=quantity, u="1", d="0"))


def test_strict_mode_is_a_model_config_decision_not_a_per_call_flag() -> None:
    assert WireModel.model_config["strict"] is True


def test_a_value_with_no_wire_representation_is_refused_not_guessed() -> None:
    """A `Decimal` in an untyped payload is refused: money is never a decimal on the wire."""
    envelope = Envelope(
        event_id=UUID("11111111-1111-4111-8111-111111111111"),
        event_type="order.placed.v1",
        aggregate_id=UUID("22222222-2222-4222-8222-222222222222"),
        correlation_id=UUID("22222222-2222-4222-8222-222222222222"),
        causation_id=UUID("33333333-3333-4333-8333-333333333333"),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"amount": Decimal("89.34")},
    )
    with pytest.raises(TypeError, match="Decimal has no wire representation"):
        to_wire_json(envelope)
