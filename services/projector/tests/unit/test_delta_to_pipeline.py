"""D2 (PR6, PR11, PR13, PR47): the emitted pipeline, as a tree.

`delta_to_pipeline` is pure, so its whole contract is checked on the tree it emits, with no server:
one stage; every value that came from a fact only ever appears inside a `$literal` (a string
beginning with `$` is evaluated by the server otherwise); every array and rank operand is
`$ifNull`-guarded; each reference and the cancellation reason are filled only if null.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from otc_projector.application.projection import project
from otc_projector.domain.projection_delta import (
    HeaderDelta,
    ItemDelta,
    ProjectionDelta,
    TimelineEntryDelta,
)
from otc_projector.infrastructure.persistence.delta_to_pipeline import delta_to_pipeline, literal

SENTINEL = "$SENTINEL"
INTEGER_SENTINELS = {910001, 910002, 910003, 910004, 910005, 910006, 910007, 910008}
KEY = "$SENTINEL_dedup_key"
INSTANT = datetime(2031, 4, 5, 6, 7, 8, 901000, tzinfo=UTC)
ORDER_DATE = datetime(2029, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
# the instants are not `$`-prefixed, but they come from the fact all the same: sentinels too
INSTANT_TEXTS = {"2031-04-05T06:07:08.901Z", "2029-01-02T03:04:05.678Z"}


def sentinel_delta() -> ProjectionDelta:
    return ProjectionDelta(
        order_id="$SENTINEL_order_id",
        entry=TimelineEntryDelta(
            event_id="$SENTINEL_event_id",
            event_type="$SENTINEL_event_type",
            occurred_at=INSTANT,
            summary="$SENTINEL_summary",
            causation_id="$SENTINEL_causation_id",
            detail={"note": "$SENTINEL_note", "lastError": "$$NOW $SENTINEL_x", "n": 910008},
        ),
        implied_status="$SENTINEL_status",
        status_rank=910001,
        cancellation_reason_if_absent="$SENTINEL_reason",
        despatch_reference_if_absent="$SENTINEL_despatch",
        invoice_reference_if_absent="$SENTINEL_invoice",
        payment_reference_if_absent="$SENTINEL_payment",
        header=HeaderDelta(
            order_reference="$SENTINEL_order_reference",
            order_date=ORDER_DATE,
            retailer_code="$SENTINEL_retailer",
            retailer_gln="$SENTINEL_retailer_gln",
            company_code="$SENTINEL_company",
            company_gln="$SENTINEL_company_gln",
            currency="$SENTINEL_currency",
            initial_amount=910002,
            initial_discount=910003,
            total_amount=910004,
            items=(
                ItemDelta(
                    product_code="$SENTINEL_product",
                    quantity=910005,
                    unit_price=910006,
                    line_discount=910007,
                ),
            ),
        ),
    )


def unwrapped_sentinels(tree: Any, inside_literal: bool = False) -> list[object]:
    """Every sentinel string or integer that appears OUTSIDE a `$literal` operand."""
    bad: list[object] = []
    if isinstance(tree, dict):
        for name, value in tree.items():
            bad.extend(unwrapped_sentinels(value, inside_literal or name == "$literal"))
    elif isinstance(tree, list | tuple):
        for item in tree:
            bad.extend(unwrapped_sentinels(item, inside_literal))
    elif not inside_literal and (
        (isinstance(tree, str) and (SENTINEL in tree or tree in INSTANT_TEXTS))
        or (isinstance(tree, int) and not isinstance(tree, bool) and tree in INTEGER_SENTINELS)
    ):
        bad.append(tree)
    return bad


def occurrences(tree: Any, value: object) -> int:
    if isinstance(tree, dict):
        return sum(occurrences(v, value) for v in tree.values())
    if isinstance(tree, list | tuple):
        return sum(occurrences(v, value) for v in tree)
    return int(tree == value)


def stage_fields(pipeline: list[dict[str, object]]) -> dict[str, Any]:
    assert len(pipeline) == 1, f"the apply must be ONE stage, got {len(pipeline)}"
    assert list(pipeline[0]) == ["$set"]
    fields: dict[str, Any] = pipeline[0]["$set"]  # type: ignore[assignment]
    return fields


def test_pr6_the_pipeline_is_exactly_one_set_stage(facts: Any) -> None:
    for event_type in ("order.placed.v1", "stock.released.v1", "order.cancelled.v1"):
        pipeline = delta_to_pipeline(project(facts.build(event_type)), "projector:x")
        assert len(pipeline) == 1
        assert list(pipeline[0]) == ["$set"]


def test_pr47_every_fact_value_in_the_pipeline_is_literal_wrapped() -> None:
    pipeline = delta_to_pipeline(sentinel_delta(), KEY)
    assert unwrapped_sentinels(pipeline) == [], "a fact value sits outside a $literal"
    # the instrument can say yes as well as no: the sentinels really are in the tree
    literals = [
        "$SENTINEL_event_id",
        "$SENTINEL_summary",
        "$SENTINEL_note",
        "$$NOW $SENTINEL_x",
        "$SENTINEL_status",
        "$SENTINEL_reason",
        "$SENTINEL_despatch",
        "$SENTINEL_invoice",
        "$SENTINEL_payment",
        "$SENTINEL_order_reference",
        "$SENTINEL_dedup_key",
        910001,
        910002,
        910006,
    ]
    for value in literals:
        assert occurrences(pipeline, value) >= 1, f"{value!r} is absent from the emitted tree"


@pytest.mark.parametrize(
    "mutation",
    ["entry", "updated_at", "dedup_key", "status", "reference", "header", "rank"],
)
def test_pr47_sentinel_the_walker_reports_an_unwrapped_value_in_each_position(
    mutation: str,
) -> None:
    pipeline = delta_to_pipeline(sentinel_delta(), KEY)
    fields = stage_fields(pipeline)
    if mutation == "entry":
        concat = fields["events"]["$let"]["vars"]["all"]["$concatArrays"]
        concat[1] = [concat[1][0]["$literal"]]
    elif mutation == "updated_at":
        fields["updatedAt"]["$max"][1] = "2031-04-05T06:07:08.901Z"
    elif mutation == "dedup_key":
        fields["processedEventKeys"]["$sortArray"]["input"]["$setUnion"][1] = [KEY]
    elif mutation == "status":
        fields["status"]["$cond"][1] = "$SENTINEL_status"
    elif mutation == "reference":
        fields["references.invoiceReference"]["$ifNull"][1] = "$SENTINEL_invoice"
    elif mutation == "header":
        fields["orderReference"] = "$SENTINEL_order_reference"
    else:
        fields["statusRank"]["$max"][1] = 910001
    assert unwrapped_sentinels(pipeline), f"the walker missed an unwrapped {mutation}"


def test_pr6_every_array_and_rank_operand_is_if_null_guarded(facts: Any) -> None:
    fields = stage_fields(
        delta_to_pipeline(project(facts.build("order.confirmed.v1")), "projector:x")
    )
    keys_input = fields["processedEventKeys"]["$sortArray"]["input"]["$setUnion"]
    assert keys_input[0] == {"$ifNull": ["$processedEventKeys", []]}
    events_input = fields["events"]["$let"]["vars"]["all"]["$concatArrays"]
    assert events_input[0] == {"$ifNull": ["$events", []]}
    rank_guard = {"$ifNull": ["$statusRank", 0]}
    assert fields["statusRank"]["$max"][0] == rank_guard
    assert fields["status"]["$cond"][0]["$gt"][1] == rank_guard
    assert fields["updatedAt"]["$max"][0]["$ifNull"][0] == "$updatedAt"


def test_pr6_status_rank_and_status_use_max_and_a_strict_greater_than(facts: Any) -> None:
    delta = project(facts.build("order.despatched.v1"))
    fields = stage_fields(delta_to_pipeline(delta, "projector:x"))
    assert "$max" in fields["statusRank"]
    assert "$gt" in fields["status"]["$cond"][0]
    assert "$gte" not in fields["status"]["$cond"][0]
    assert fields["status"]["$cond"][1] == literal("despatched")
    assert fields["status"]["$cond"][2] == "$status"
    assert fields["statusRank"]["$max"][1] == literal(delta.status_rank)


REFERENCE_FACTS = {
    "order.despatched.v1": ("references.despatchReference", "DES-000203"),
    "invoice.issued.v1": ("references.invoiceReference", "INV-000304"),
    "payment.received.v1": ("references.paymentReference", "PAY-A-5001"),
}
ALL_REFERENCES = {name for name, _ in REFERENCE_FACTS.values()}


@pytest.mark.parametrize("event_type", sorted(REFERENCE_FACTS))
def test_pr11_a_reference_fact_fills_only_its_own_reference_if_null(
    facts: Any, event_type: str
) -> None:
    fields = stage_fields(delta_to_pipeline(project(facts.build(event_type)), "projector:x"))
    own, value = REFERENCE_FACTS[event_type]
    assert fields[own] == {"$ifNull": [f"${own}", literal(value)]}
    for other in ALL_REFERENCES - {own}:
        assert fields[other] == {"$ifNull": [f"${other}", literal(None)]}, (
            f"{event_type} writes {other}"
        )


@pytest.mark.parametrize("event_type", ["order.placed.v1", "order.confirmed.v1"])
def test_pr11_a_fact_without_a_reference_fills_none(facts: Any, event_type: str) -> None:
    fields = stage_fields(delta_to_pipeline(project(facts.build(event_type)), "projector:x"))
    for name in ALL_REFERENCES:
        assert fields[name] == {"$ifNull": [f"${name}", literal(None)]}


def test_pr13_cancellation_reason_is_filled_only_if_null(facts: Any) -> None:
    cancelled = stage_fields(
        delta_to_pipeline(project(facts.build("order.cancelled.v1")), "projector:x")
    )
    assert cancelled["cancellationReason"] == {
        "$ifNull": ["$cancellationReason", literal("credit_rejected")]
    }
    other = stage_fields(
        delta_to_pipeline(project(facts.build("order.completed.v1")), "projector:x")
    )
    assert other["cancellationReason"] == {"$ifNull": ["$cancellationReason", literal(None)]}


HEADER_KEYS = {
    "orderReference",
    "orderDate",
    "retailer.code",
    "retailer.gln",
    "company.code",
    "company.gln",
    "currency",
    "totals.initialAmount",
    "totals.initialDiscount",
    "totals.totalAmount",
    "items",
    "headerComplete",
}


def test_pr9_order_placed_writes_the_header_unconditionally_and_marks_it_complete(
    facts: Any,
) -> None:
    fields = stage_fields(delta_to_pipeline(project(facts.build("order.placed.v1")), "projector:x"))
    assert set(fields) >= HEADER_KEYS
    for key in HEADER_KEYS:
        assert set(fields[key]) == {"$literal"}, f"{key} is conditional or unwrapped"
    assert fields["headerComplete"] == literal(True)
    assert fields["orderReference"] == literal("ORD-000101")


def test_pr9_a_fact_other_than_order_placed_writes_no_header_field(facts: Any) -> None:
    fields = stage_fields(
        delta_to_pipeline(project(facts.build("stock.reserved.v1")), "projector:x")
    )
    assert not HEADER_KEYS & set(fields)


def test_pr12_a_status_less_fact_writes_rank_zero(facts: Any) -> None:
    fields = stage_fields(
        delta_to_pipeline(project(facts.build("stock.rejected.v1")), "projector:x")
    )
    assert fields["statusRank"]["$max"][1] == literal(0)
    assert fields["status"]["$cond"][0]["$gt"][0] == literal(0)
    assert fields["status"]["$cond"][1] == literal(None)
