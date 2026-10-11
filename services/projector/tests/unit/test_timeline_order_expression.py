"""D3 (PR10): the pipeline expression's shape, and that the apply and the migration share it."""

from pathlib import Path
from typing import Any

from otc_projector.infrastructure.persistence.timeline_order import timeline_order_expression

INFRA = Path(__file__).resolve().parents[2] / "src" / "otc_projector" / "infrastructure"


def find_key(tree: Any, key: str) -> list[Any]:
    """Every value stored under `key` anywhere in a nested dict/list tree."""
    found: list[Any] = []
    if isinstance(tree, dict):
        for name, value in tree.items():
            if name == key:
                found.append(value)
            found.extend(find_key(value, key))
    elif isinstance(tree, list):
        for item in tree:
            found.extend(find_key(item, key))
    return found


def test_pr10_the_events_stage_sorts_by_occurred_at_depth_event_id_and_discards_the_depth() -> None:
    expression = timeline_order_expression("$events")
    sort_by = find_key(expression, "$sortArray")
    assert len(sort_by) == 1, "the expression must sort the entries exactly once"
    assert list(sort_by[0]["sortBy"]) == ["occurredAt", "__depth", "eventId"], (
        "dict key order IS the sort order: it must be occurredAt, __depth, eventId"
    )
    assert all(direction == 1 for direction in sort_by[0]["sortBy"].values())
    unsets = find_key(expression, "$unsetField")
    assert len(unsets) == 1, "the depth must be discarded by exactly one $unsetField"
    assert unsets[0] == {"field": "__depth", "input": "$$e"}, "the depth must be discarded"
    # the outer $map applies the $unsetField to the sorted array
    outer = expression["$let"]["in"]["$let"]["in"]["$map"]  # type: ignore[index]
    assert "$sortArray" in outer["input"]
    assert outer["in"] == {"$unsetField": {"field": "__depth", "input": "$$e"}}


def test_pr10_the_apply_and_the_migration_call_the_same_function() -> None:
    """Both modules reference `timeline_order_expression`; neither carries a copy of the ordering.

    The apply legitimately holds ONE `$sortArray` of its own (the dedup keys); what no module but
    `timeline_order.py` may hold is the causal ordering: the depth field, the `$reduce` fixpoint, or
    a sort by `occurredAt`.
    """
    sources = {
        name: (INFRA / "persistence" / f"{name}.py").read_text(encoding="utf-8")
        for name in ("delta_to_pipeline", "timeline_order_migration")
    }
    for name, source in sources.items():
        assert "timeline_order_expression(" in source, f"{name} does not call the shared expression"
        for owned in ('"__depth"', '"$reduce"', '"occurredAt": 1', "DEPTH_FIELD"):
            assert owned not in source, f"{name} carries its own copy of the ordering ({owned})"
    assert '"$sortArray"' not in sources["timeline_order_migration"], "the migration sorts itself"
    assert sources["delta_to_pipeline"].count('"$sortArray"') == 1, "only the dedup keys are sorted"
