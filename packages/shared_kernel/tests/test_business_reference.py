"""`OrderNumber` and its three siblings: one sequential-reference shape (domain-model.md 2.3)."""

from typing import Any

import pytest

from otc_shared_kernel import (
    BusinessReference,
    CreditLineReference,
    DespatchReference,
    DomainError,
    InvalidBusinessReferenceError,
    InvoiceReference,
    OrderNumber,
)

KINDS: list[tuple[type[BusinessReference], str, str]] = [
    (OrderNumber, "ORD", "order_number.invalid"),
    (DespatchReference, "DES", "despatch_reference.invalid"),
    (InvoiceReference, "INV", "invoice_reference.invalid"),
    (CreditLineReference, "CR", "credit_line_reference.invalid"),
]
KIND_IDS = [prefix for _, prefix, _ in KINDS]


@pytest.mark.parametrize(("kind", "prefix", "code"), KINDS, ids=KIND_IDS)
def test_reference_is_the_prefix_plus_a_zero_padded_sequence(
    kind: type[BusinessReference], prefix: str, code: str
) -> None:
    assert str(kind.from_sequence(1)) == f"{prefix}-000001"
    assert kind.from_sequence(42).value == f"{prefix}-000042"
    assert kind.from_sequence(999_999).value == f"{prefix}-999999"


@pytest.mark.parametrize(("kind", "prefix", "code"), KINDS, ids=KIND_IDS)
def test_reference_grows_beyond_six_digits_rather_than_truncating(
    kind: type[BusinessReference], prefix: str, code: str
) -> None:
    assert kind.from_sequence(1_000_000).value == f"{prefix}-1000000"
    assert kind.from_sequence(12_345_678).value == f"{prefix}-12345678"
    assert kind.from_sequence(1_000_000).sequence == 1_000_000


@pytest.mark.parametrize(("kind", "prefix", "code"), KINDS, ids=KIND_IDS)
def test_reference_parse_round_trips_the_sequence(
    kind: type[BusinessReference], prefix: str, code: str
) -> None:
    for sequence in (1, 7, 100_000, 999_999, 1_000_000, 987_654_321):
        reference = kind.from_sequence(sequence)
        assert kind.parse(reference.value) == reference
        assert kind.parse(reference.value).sequence == sequence
        assert reference.sequence == sequence


@pytest.mark.parametrize(("kind", "prefix", "code"), KINDS, ids=KIND_IDS)
def test_reference_refuses_malformed_text(
    kind: type[BusinessReference], prefix: str, code: str
) -> None:
    other = "DES" if prefix != "DES" else "INV"
    for bad in (
        f"{other}-000001",  # a sibling's prefix
        f"{prefix.lower()}-000001",
        f"{prefix}000001",
        f"{prefix}_000001",
        f"{prefix}-",
        f"{prefix}-00001",  # five digits
        f"{prefix}-000000",  # sequence zero
        f"{prefix}-0000001",  # extra padding: not canonical
        f"{prefix}-00000001",
        f"{prefix}-12345a",
        f"{prefix}--00001",
        f"{prefix}-+00001",
        f"{prefix}-000001\n",
        f" {prefix}-000001",
        f"{prefix}-000001 ",
        f"{prefix}-٠٠٠٠٠١",  # Arabic-Indic digits  # noqa: RUF001
        f"{prefix}X-000001",
        f"X{prefix}-000001",
        f"{prefix}-{'9' * 20}",  # beyond the bigint counter
        "",
    ):
        with pytest.raises(InvalidBusinessReferenceError) as raised:
            kind.parse(bad)
        assert isinstance(raised.value, DomainError)
        assert raised.value.code == code


@pytest.mark.parametrize(("kind", "prefix", "code"), KINDS, ids=KIND_IDS)
@pytest.mark.parametrize("bad", [0, -1, True, False, 1.0, 2.5, "7", None, 2**63])
def test_reference_from_sequence_refuses_a_non_positive_or_non_int_sequence(
    kind: type[BusinessReference], prefix: str, code: str, bad: Any
) -> None:
    with pytest.raises(InvalidBusinessReferenceError) as raised:
        kind.from_sequence(bad)
    assert raised.value.code == code


@pytest.mark.parametrize(("kind", "prefix", "code"), KINDS, ids=KIND_IDS)
@pytest.mark.parametrize("bad", [None, 1, b"ORD-000001", ["x"]])
def test_reference_refuses_a_non_str_value(
    kind: type[BusinessReference], prefix: str, code: str, bad: Any
) -> None:
    with pytest.raises(InvalidBusinessReferenceError):
        kind(bad)


def test_the_four_error_codes_are_distinct_and_stable() -> None:
    # Read from the production classes, not from this file's own table (a literal compared to a
    # literal passes under a sibling substitution).
    codes = [
        kind.ERROR_CODE
        for kind in (OrderNumber, DespatchReference, InvoiceReference, CreditLineReference)
    ]
    assert codes == [
        "order_number.invalid",
        "despatch_reference.invalid",
        "invoice_reference.invalid",
        "credit_line_reference.invalid",
    ]
    assert len(set(codes)) == 4
    assert [code for _, _, code in KINDS] == codes


def test_references_of_different_kinds_are_never_equal_and_equal_ones_hash_alike() -> None:
    assert OrderNumber.from_sequence(1) == OrderNumber.parse("ORD-000001")
    assert hash(OrderNumber.from_sequence(1)) == hash(OrderNumber.parse("ORD-000001"))
    assert OrderNumber.from_sequence(1) != OrderNumber.from_sequence(2)
    values = {
        kind.from_sequence(1)
        for kind in (OrderNumber, DespatchReference, InvoiceReference, CreditLineReference)
    }
    assert len(values) == 4
    order: Any = OrderNumber.from_sequence(1)
    assert order != DespatchReference.from_sequence(1)


def test_the_base_reference_is_abstract_and_references_are_immutable() -> None:
    with pytest.raises(TypeError):
        BusinessReference("ORD-000001")
    with pytest.raises(AttributeError):
        OrderNumber.from_sequence(1).value = "ORD-000002"  # type: ignore[misc]
