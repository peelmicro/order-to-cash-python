"""The projection (`application/projection.py`): C3, C4, C5, C6, C7.

Fixtures never satisfy a relation by accident: every sentinel in a test is distinct from every other
sentinel of that test and from the builders' defaults, and no sentinel contains another.
"""

import ast
import re
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from otc_contracts import FACT_MODELS
from otc_projector.application.projection import project
from otc_projector.domain.status_rank import STATUS_RANK

SRC = Path(__file__).resolve().parents[2] / "src" / "otc_projector"
PROJECTION = SRC / "application" / "projection.py"
REPO = Path(__file__).resolve().parents[4]


# ------------------------------------------------------------------------------------- C3 / PR2


def case_classes(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.match_case) and isinstance(node.pattern, ast.MatchClass):
            assert isinstance(node.pattern.cls, ast.Name)
            names.add(node.pattern.cls.id)
    return names


def test_pr2_projects_every_fact_models_entry_and_fails_in_both_directions_when_the_registry_and_the_match_disagree(  # noqa: E501
    facts: Any,
) -> None:
    # direction 1: every registered fact projects a sample without raising, and its entry names it
    for event_type in FACT_MODELS:
        event = facts.build(event_type)
        assert project(event).entry.event_type == event_type, event_type
    # direction 2: the classes the match names are exactly the registry's classes
    registered = {model.__name__ for model in FACT_MODELS.values()}
    matched = case_classes(PROJECTION)
    assert matched == registered, (
        f"match arms without a registry entry: {sorted(matched - registered)}; "
        f"registry entries without an arm: {sorted(registered - matched)}"
    )


# --------------------------------------------------------------------------------------- C4 / PR12

# Copied once from `specs/projector_read_model/requirements.md` PR12's table (lines 66-77): the
# implied status per eventType. The ranks are NOT typed here: they are compared through
# `STATUS_RANK`, whose values `test_read_model_constants.py` pins to the shared fixture.
PR12_STATUS = {
    "order.placed.v1": "placed",
    "stock.reserved.v1": "stock_reserved",
    "credit.approved.v1": "credit_approved",
    "order.confirmed.v1": "confirmed",
    "order.despatched.v1": "despatched",
    "invoice.issued.v1": "invoiced",
    "payment.received.v1": "paid",
    "order.completed.v1": "completed",
    "order.cancelled.v1": "cancelled",
    "stock.rejected.v1": None,
    "stock.released.v1": None,
    "credit.rejected.v1": None,
    "credit.released.v1": None,
    "order.saga_failed.v1": None,
}


@pytest.mark.parametrize("event_type", sorted(FACT_MODELS))
def test_pr12_maps_each_of_the_fourteen_facts_to_the_tables_status_and_rank(
    facts: Any, event_type: str
) -> None:
    delta = project(facts.build(event_type))
    expected = PR12_STATUS[event_type]
    assert delta.implied_status == expected, f"{event_type}: implied status"
    assert delta.status_rank == (0 if expected is None else STATUS_RANK[expected]), event_type


def test_pr12_the_table_covers_exactly_the_fourteen_facts() -> None:
    assert set(PR12_STATUS) == set(FACT_MODELS)
    assert len(PR12_STATUS) == 14
    assert sum(1 for status in PR12_STATUS.values() if status is None) == 5


# --------------------------------------------------------------------------------------- C5 / PR37

ENVELOPE_SENTINELS = {
    "event_id": UUID("aaaaaaaa-0001-4000-8000-000000000001"),
    "aggregate_id": UUID("aaaaaaaa-0002-4000-8000-000000000002"),
    "correlation_id": UUID("aaaaaaaa-0003-4000-8000-000000000003"),
    "causation_id": UUID("aaaaaaaa-0004-4000-8000-000000000004"),
}


def test_pr37_every_envelope_field_reaches_the_entry_verbatim_sentinel_per_field(
    facts: Any,
) -> None:
    from datetime import UTC, datetime

    occurred_at = datetime(2031, 5, 6, 7, 8, 9, 321000, tzinfo=UTC)
    event = facts.build("stock.reserved.v1", occurred_at=occurred_at, **ENVELOPE_SENTINELS)
    delta = project(event)
    assert delta.entry.event_id == "aaaaaaaa-0001-4000-8000-000000000001", "eventId"
    assert delta.entry.event_type == "stock.reserved.v1", "eventType"
    assert delta.order_id == "aaaaaaaa-0003-4000-8000-000000000003", "correlationId -> order id"
    assert delta.entry.causation_id == "aaaaaaaa-0004-4000-8000-000000000004", "causationId"
    assert delta.entry.occurred_at == occurred_at, "occurredAt"
    assert "aaaaaaaa-0002-4000-8000-000000000002" not in {
        delta.order_id,
        delta.entry.event_id,
        delta.entry.causation_id,
    }, "the aggregate id must reach nowhere"


def test_pr37_every_order_placed_field_reaches_the_header_verbatim_sentinel_per_field(
    facts: Any,
) -> None:
    from datetime import UTC, datetime

    order_date = datetime(2030, 2, 3, 4, 5, 6, 789000, tzinfo=UTC)
    lines = [
        {
            "product_code": "SENT-P1",
            "description": "d1",
            "quantity": 71,
            "unit_price": 8101,
            "line_discount": 17,
        },
        {
            "product_code": "SENT-P2",
            "description": "d2",
            "quantity": 73,
            "unit_price": 9203,
            "line_discount": 29,
        },
    ]
    event = facts.build(
        "order.placed.v1",
        payload={
            "order_reference": "ORD-777001",
            "order_date": order_date,
            "retailer_code": "RET-SENT",
            "company_code": "CMP-SENT",
            "buyer_gln": "1111111111116",
            "supplier_gln": "2222222222222",
            "currency": "SEK",
            "initial_amount": 4440005,
            "initial_discount": 3330007,
            "total_amount": 1110003,
            "lines": lines,
        },
    )
    delta = project(event)
    header = delta.header
    assert header is not None
    assert header.order_reference == "ORD-777001"
    assert header.order_date == order_date
    assert header.retailer_code == "RET-SENT"
    assert header.company_code == "CMP-SENT"
    assert header.retailer_gln == "1111111111116", "buyerGln -> retailer.gln"
    assert header.company_gln == "2222222222222", "supplierGln -> company.gln"
    assert header.currency == "SEK"
    assert header.initial_amount == 4440005
    assert header.initial_discount == 3330007
    assert header.total_amount == 1110003
    assert [(i.product_code, i.quantity, i.unit_price, i.line_discount) for i in header.items] == [
        ("SENT-P1", 71, 8101, 17),
        ("SENT-P2", 73, 9203, 29),
    ]
    assert delta.entry.summary == "Order ORD-777001 placed for RET-SENT"


def test_pr37_only_order_placed_carries_a_header(facts: Any) -> None:
    carriers = {t for t in FACT_MODELS if project(facts.build(t)).header is not None}
    assert carriers == {"order.placed.v1"}


# --------------------------------------------------------------------------------------- C6 / PR46

BRANCHES = [
    # (cancellationReason, compensation steps, note)
    ("operator_cancelled", [], "Cliente pidió anulación"),
    ("operator_cancelled", ["stock_released"], "$status refund"),
    ("operator_cancelled", ["stock_released", "credit_released"], " spaced "),
    ("operator_cancelled", [], None),
    ("stock_rejected", [], None),
    ("credit_rejected", ["stock_released"], None),
]


def steps(names: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "step": name,
            "event_id": f"0000000{index}-0000-4000-8000-00000000000{index}",
            "event_type": "stock.released.v1" if name == "stock_released" else "credit.released.v1",
            "occurred_at": f"2026-03-1{index}T10:00:00.000Z",
        }
        for index, name in enumerate(names, start=1)
    ]


@pytest.mark.parametrize(("reason", "step_names", "note"), BRANCHES)
def test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one(
    facts: Any, reason: str, step_names: list[str], note: str | None
) -> None:
    payload: dict[str, Any] = {
        "cancellation_reason": reason,
        "compensation_steps": steps(step_names),
    }
    if note is not None:
        payload["note"] = note
    detail = project(facts.build("order.cancelled.v1", payload=payload)).entry.detail
    assert detail is not None
    if note is None:
        assert "note" not in detail, f"a note appeared where the fact had none: {detail}"
    else:
        assert "note" in detail, f"the operator's note {note!r} did not reach detail: {detail}"
        assert detail["note"] == note, "the operator's note was altered on its way to the entry"
    assert detail["cancellationReason"] == reason
    assert [s["step"] for s in detail["compensationSteps"]] == step_names  # type: ignore[attr-defined]


# --------------------------------------------------------------------------------------- C7 / PR36

DOMAIN_MODEL = REPO / "specs" / "shared" / "domain-model.md"


def fourteen_event_types() -> set[str]:
    text = DOMAIN_MODEL.read_text(encoding="utf-8")
    section = text.split("### 7.2 The fourteen facts", 1)[1].split("### 7.3", 1)[0]
    return set(re.findall(r"`([a-z]+\.[a-z_]+\.v[0-9]+)`", section))


# `(file, line, classification)` of every event-type literal under `services/projector/src` outside
# a docstring. EXPECTED EMPTY: the projector decides which facts it handles by class (`FACT_MODELS`
# through `parse_fact`, the `FactEvent` match), never by a second list of strings. A log message
# that must name a type would be added here with its classification.
CLASSIFIED_HITS: set[tuple[str, int, str]] = set()


def docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                ids.add(id(first.value))
    return ids


def event_type_hits(root: Path, event_types: set[str]) -> set[tuple[str, int]]:
    hits = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = docstring_nodes(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and any(literal in node.value for literal in event_types)
            ):
                hits.add((str(path.relative_to(root)), node.lineno))
    return hits


def test_pr36_the_expected_set_is_the_fourteen_facts_read_from_the_domain_model() -> None:
    assert fourteen_event_types() == set(FACT_MODELS)
    assert len(fourteen_event_types()) == 14


def test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set() -> (  # noqa: E501
    None
):
    hits = event_type_hits(SRC, fourteen_event_types())
    classified = {(file, line) for file, line, _ in CLASSIFIED_HITS}
    assert hits == classified, (
        f"unclassified eventType literals under services/projector/src: {sorted(hits - classified)}"
        f"; classified but gone: {sorted(classified - hits)}"
    )


@pytest.mark.parametrize(
    "scratch",
    [
        'HANDLED = {"order.placed.v1", "stock.reserved.v1"}\n',
        'TEXT = """\norder.placed.v1\n"""\n',
        'from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    HANDLED = "order.placed.v1"\n',
        'MESSAGE = f"handled {1} order.placed.v1"\n',
    ],
    ids=["a set literal", "a triple-quoted string", "an if TYPE_CHECKING block", "an f-string"],
)
def test_pr36_sentinel_the_scan_finds_a_literal_in_every_hiding_place(
    tmp_path: Path, scratch: str
) -> None:
    (tmp_path / "scratch.py").write_text(scratch, encoding="utf-8")
    assert event_type_hits(tmp_path, fourteen_event_types()), scratch
