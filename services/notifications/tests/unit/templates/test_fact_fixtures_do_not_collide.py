"""The fixtures cannot satisfy an assertion's relation by accident (#8 ids 58, 59, 60).

Over the whole population of leaf values of each notified fixture (the envelope's ids and instant
included, lists walked element by element), in both variants:

* EQUALITY: no two leaves are equal, so a transposition (rendering `aggregateId` where
  `correlationId` belongs) is visible;
* CONTAINMENT: no text leaf contains another, so `assert "credit.release" in text` cannot pass on
  `credit.released.v1` (#8's `OrderCancelledTemplate.cs:16` survivor was exactly this).

Integers take part in equality but not in containment (a short integer is a substring of many
UUIDs by nature; the rendered form of an amount is checked by `test_template_rendering.py`).
The sentinels build a colliding fixture and must be reported.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

import pytest

from otc_contracts import format_instant

NOTIFIED = (
    "order.placed.v1",
    "order.confirmed.v1",
    "order.despatched.v1",
    "invoice.issued.v1",
    "payment.received.v1",
    "order.completed.v1",
    "order.cancelled.v1",
)


def leaves(value: Any, path: str = "") -> list[tuple[str, str | int]]:
    """Every scalar of a constructor-style dict: `(path, text-or-int)`."""
    if isinstance(value, dict):
        return [leaf for key, item in value.items() for leaf in leaves(item, f"{path}.{key}")]
    if isinstance(value, list):
        return [leaf for i, item in enumerate(value) for leaf in leaves(item, f"{path}[{i}]")]
    if isinstance(value, datetime):
        return [(path, format_instant(value))]
    if isinstance(value, UUID):
        return [(path, str(value))]
    assert isinstance(value, str | int), (path, value)
    return [(path, value)]


def collisions(data: dict[str, Any]) -> list[str]:
    found = []
    items = leaves({key: value for key, value in data.items() if key != "event_type"})
    for i, (path_a, a) in enumerate(items):
        for path_b, b in items[i + 1 :]:
            if a == b:
                found.append(f"EQUAL {path_a} == {path_b} == {a!r}")
            elif isinstance(a, str) and isinstance(b, str) and (a in b or b in a):
                found.append(f"CONTAINS {path_a}={a!r} / {path_b}={b!r}")
    return found


@pytest.mark.parametrize("variant", ["A", "B"])
@pytest.mark.parametrize("event_type", NOTIFIED)
def test_no_two_leaves_of_a_notified_fixture_are_equal_and_no_text_contains_another(
    facts: Any, event_type: str, variant: str
) -> None:
    assert collisions(facts.event_dict(event_type, variant)) == []


@pytest.mark.parametrize("event_type", NOTIFIED)
def test_variant_b_differs_from_variant_a_at_every_leaf(facts: Any, event_type: str) -> None:
    a = leaves(facts.event_dict(event_type, "A"))
    b = leaves(facts.event_dict(event_type, "B"))
    assert [path for path, _ in a] == [path for path, _ in b], "the same shape"
    same = [
        path for (path, x), (_, y) in zip(a, b, strict=True) if x == y and "event_type" not in path
    ]
    assert same == [], "leaves identical in both variants (a perturbation there would be a no-op)"


def test_sentinel_an_equal_pair_is_reported(facts: Any) -> None:
    data = facts.event_dict("order.confirmed.v1")
    data["aggregate_id"] = data["correlation_id"]
    assert any(c.startswith("EQUAL") for c in collisions(data))


def test_sentinel_a_prefix_collision_is_reported(facts: Any) -> None:
    """#8's survivor shape: one value is a prefix of another."""
    data = facts.event_dict("order.cancelled.v1")
    data["payload"]["compensation_steps"][0]["step"] = "credit.release"
    data["payload"]["compensation_steps"][1]["event_type"] = "credit.released.v1"
    assert any(c.startswith("CONTAINS") for c in collisions(data))


def test_sentinel_a_collision_inside_a_list_element_is_reported(facts: Any) -> None:
    data = facts.event_dict("order.despatched.v1")
    data["payload"]["lines"][1]["product_code"] = data["payload"]["lines"][0]["product_code"]
    assert any(c.startswith("EQUAL") for c in collisions(data))
