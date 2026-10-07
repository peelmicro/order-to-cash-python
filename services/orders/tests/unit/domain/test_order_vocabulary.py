"""The closed vocabularies (`design.md` L1 - L3): tokens transcribed from the specification.

Every set below is a LITERAL typed from `domain-model.md` section 3.1 / 3.3 and `asyncapi.yaml`,
never read back from the constant the code holds (tasks.md trap 3). The contract half (the same
tokens against the generated enums) is
`services/orders/tests/unit/test_order_domain_contract_parity.py`.
"""

from enum import Enum, StrEnum

import pytest

from otc_orders.domain.errors import InvalidOrderSnapshotError
from otc_orders.domain.value_objects.cancellation_reason import (
    CancellationReason,
    parse_cancellation_reason,
)
from otc_orders.domain.value_objects.compensation_step import CompensationStepKind
from otc_orders.domain.value_objects.order_status import OrderStatus, parse_order_status

STATUS_TOKENS = {
    "placed",
    "stock_reserved",
    "credit_approved",
    "confirmed",
    "despatched",
    "invoiced",
    "paid",
    "completed",
    "cancelled",
}
REASON_TOKENS = {"stock_rejected", "credit_rejected", "operator_cancelled"}
STEP_TOKENS = {"stock_released", "credit_released"}


def test_order_status_tokens_are_exactly_the_nine_of_the_specification() -> None:
    assert len(OrderStatus) == 9
    assert {member.value for member in OrderStatus} == STATUS_TOKENS


def test_cancellation_reason_tokens_are_exactly_the_three_of_the_specification() -> None:
    assert len(CancellationReason) == 3
    assert {member.value for member in CancellationReason} == REASON_TOKENS


def test_compensation_step_kinds_are_exactly_the_two_of_the_specification() -> None:
    assert len(CompensationStepKind) == 2
    assert {member.value for member in CompensationStepKind} == STEP_TOKENS


@pytest.mark.parametrize("vocabulary", [OrderStatus, CancellationReason, CompensationStepKind])
def test_the_vocabularies_are_enums_not_str_subclasses(vocabulary: type[Enum]) -> None:
    # A StrEnum would let a raw row string pass a membership test unparsed (tasks.md trap 4).
    assert not issubclass(vocabulary, str)
    assert not issubclass(vocabulary, StrEnum)
    for member in vocabulary:
        assert member != member.value


class _SneakyStatus(StrEnum):
    PLACED = "placed"


@pytest.mark.parametrize(
    "token",
    [
        "Placed",
        " placed",
        "placed ",
        "",
        _SneakyStatus.PLACED,
        b"placed",
        None,
    ],
    ids=["capital", "leading-space", "trailing-space", "empty", "str-subclass", "bytes", "none"],
)
def test_parse_is_exact_and_refuses_everything_outside_the_closed_set(token: object) -> None:
    with pytest.raises(InvalidOrderSnapshotError) as raised:
        parse_order_status(token)
    assert raised.value.code == "order.snapshot_invalid"


def test_parse_accepts_each_real_token_and_returns_its_member() -> None:
    expected = {
        "placed": OrderStatus.PLACED,
        "stock_reserved": OrderStatus.STOCK_RESERVED,
        "credit_approved": OrderStatus.CREDIT_APPROVED,
        "confirmed": OrderStatus.CONFIRMED,
        "despatched": OrderStatus.DESPATCHED,
        "invoiced": OrderStatus.INVOICED,
        "paid": OrderStatus.PAID,
        "completed": OrderStatus.COMPLETED,
        "cancelled": OrderStatus.CANCELLED,
    }
    assert {token: parse_order_status(token) for token in STATUS_TOKENS} == expected
    assert {token: parse_cancellation_reason(token) for token in REASON_TOKENS} == {
        "stock_rejected": CancellationReason.STOCK_REJECTED,
        "credit_rejected": CancellationReason.CREDIT_REJECTED,
        "operator_cancelled": CancellationReason.OPERATOR_CANCELLED,
    }
