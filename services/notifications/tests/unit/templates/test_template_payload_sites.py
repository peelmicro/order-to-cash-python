"""The population of payload sites of the seven templates, enumerated from the MODELS and driven
(acceptance 4; #8 ids 58 and 59: 45 of 68 template mutations survived, and the population was
counted three times as 14, 89 and 95 because each count was scoped by the question of whoever made
it, the 95th site being a nested list element).

The population here is every leaf of the fact's own model (envelope included), walked by
`leaves()` through nested models and lists, element by element, derived from the fixture and so
from the generated model, not from the template source. Each leaf is CORRUPTED (replaced by
variant B's value for the same path) and the message re-rendered:

* a leaf whose corruption changes the message must NOT be in `NOT_RENDERED` (the literal is exact
  in that direction: a field the template starts rendering must be taken out of it, deliberately);
* a leaf whose corruption changes nothing MUST be in `NOT_RENDERED` (a field the template silently
  stopped rendering fails by name);
* `NOT_RENDERED` is a literal per fact with the reason, and every entry must be a real leaf.

This proves each rendered site is READ (delete the read and the corruption changes nothing) and each
declared-unrendered field is NOT. WHICH value reaches WHERE (a swap between two rendered fields) is
`test_template_rendering.py`'s exact text and the committed source sweep
`scripts/notification-template-sweep.py`. Sentinels: a template that ignores a leaf, and one that
renders an envelope id, must be caught.
"""

import copy
import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from otc_notifications.application.templates.invoice_issued import render_invoice_issued
from otc_notifications.application.templates.order_cancelled import render_order_cancelled
from otc_notifications.application.templates.order_completed import render_order_completed
from otc_notifications.application.templates.order_confirmed import render_order_confirmed
from otc_notifications.application.templates.order_despatched import render_order_despatched
from otc_notifications.application.templates.order_placed import render_order_placed
from otc_notifications.application.templates.payment_received import render_payment_received

RENDERERS: dict[str, Callable[[Any], Any]] = {
    "order.placed.v1": render_order_placed,
    "order.confirmed.v1": render_order_confirmed,
    "order.despatched.v1": render_order_despatched,
    "invoice.issued.v1": render_invoice_issued,
    "payment.received.v1": render_payment_received,
    "order.completed.v1": render_order_completed,
    "order.cancelled.v1": render_order_cancelled,
}

ENVELOPE_NOT_RENDERED = {"event_id", "aggregate_id", "causation_id", "occurred_at"}
"""The envelope fields no template renders: `eventId` becomes the Message-Id in `dispatch`, not in
the template; `aggregateId` and `causationId` and `occurredAt` are not part of any email. Only
`correlation_id` is rendered (subject, text and HTML). `event_type` selects the template and is not
perturbed."""

NOT_RENDERED: dict[str, set[str]] = {
    "order.placed.v1": {
        "payload.buyer_gln",
        "payload.supplier_gln",
        "payload.lines[0].product_code",
        "payload.lines[0].description",
        "payload.lines[0].quantity",
        "payload.lines[0].unit_price",
        "payload.lines[0].line_discount",
        "payload.lines[1].product_code",
        "payload.lines[1].description",
        "payload.lines[1].quantity",
        "payload.lines[1].unit_price",
        "payload.lines[1].line_discount",
        "payload.initial_amount",
        "payload.initial_discount",
    },
    "order.confirmed.v1": set(),
    "order.despatched.v1": set(),
    "invoice.issued.v1": {
        "payload.lines[0].product_code",
        "payload.lines[0].units",
        "payload.lines[0].unit_price",
        "payload.lines[1].product_code",
        "payload.lines[1].units",
        "payload.lines[1].unit_price",
        "payload.amount",
        "payload.discount",
    },
    "payment.received.v1": set(),
    "order.completed.v1": set(),
    "order.cancelled.v1": {
        "payload.compensation_steps[0].event_id",
        "payload.compensation_steps[0].event_type",
        "payload.compensation_steps[0].occurred_at",
        "payload.compensation_steps[0].summary",
        "payload.compensation_steps[1].event_id",
        "payload.compensation_steps[1].event_type",
        "payload.compensation_steps[1].occurred_at",
        "payload.compensation_steps[1].summary",
        "payload.note",
    },
}


def leaf_paths(value: Any, path: str = "") -> list[str]:
    if isinstance(value, dict):
        return [
            p for key, item in value.items() for p in leaf_paths(item, f"{path}.{key}".lstrip("."))
        ]
    if isinstance(value, list):
        return [p for i, item in enumerate(value) for p in leaf_paths(item, f"{path}[{i}]")]
    return [path]


def get(data: Any, path: str) -> Any:
    for part in _parts(path):
        data = data[part]
    return data


def put(data: dict[str, Any], path: str, value: Any) -> None:
    *head, last = _parts(path)
    target: Any = data
    for part in head:
        target = target[part]
    target[last] = value


def _parts(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for chunk in path.split("."):
        name, _, rest = chunk.partition("[")
        parts.append(name)
        while rest:
            index, _, rest = rest.partition("]")
            parts.append(int(index))
            rest = rest.removeprefix("[")
    return parts


def rendered(message: Any) -> tuple[str, str, str, str]:
    return (message.to, message.subject, message.text_body, message.html_body)


def changed_paths(
    facts: Any, event_type: str, render: Callable[[Any], Any]
) -> tuple[set[str], set[str]]:
    """`(changed, in_one_body_only)`: the leaves whose corruption changes the message, and those
    among them that reach the TEXT body or the HTML body but not both (every rendered leaf is in
    both: a read dropped from one body is a defect the union alone would hide)."""
    base = facts.event_dict(event_type, "A")
    other = facts.event_dict(event_type, "B")
    baseline = render(facts.event_from(event_type, base))
    changed: set[str] = set()
    one_body_only: set[str] = set()
    for path in leaf_paths({k: v for k, v in base.items() if k != "event_type"}):
        assert get(base, path) != get(other, path), f"{path} is the same in both variants"
        corrupted = copy.deepcopy(base)
        put(corrupted, path, get(other, path))
        message = render(facts.event_from(event_type, corrupted))
        if rendered(message) != rendered(baseline):
            changed.add(path)
            if (message.text_body != baseline.text_body) != (
                message.html_body != baseline.html_body
            ):
                one_body_only.add(path)
    return changed, one_body_only


@pytest.mark.parametrize("event_type", sorted(RENDERERS))
def test_every_rendered_site_is_read_and_every_unrendered_field_is_not(
    facts: Any, event_type: str
) -> None:
    base = facts.event_dict(event_type, "A")
    population = set(leaf_paths({k: v for k, v in base.items() if k != "event_type"}))
    declared = NOT_RENDERED[event_type] | ENVELOPE_NOT_RENDERED
    assert declared <= population, f"declared but not a leaf: {sorted(declared - population)}"

    changed, one_body_only = changed_paths(facts, event_type, RENDERERS[event_type])

    assert changed == population - declared, (
        f"rendered but declared unrendered (or the reverse): "
        f"unexpectedly unchanged {sorted((population - declared) - changed)}; "
        f"unexpectedly changed {sorted(changed & declared)}"
    )
    assert one_body_only == set(), (
        f"reaches only one of the text and HTML bodies: {sorted(one_body_only)}"
    )


def test_the_population_of_leaves_is_the_recorded_count(facts: Any) -> None:
    """The unit of the claim is the LEAF of a notified fixture: the five envelope fields (not
    `event_type`) plus every payload leaf, list elements counted one by one. The counts are literals
    so a field added to a payload, or a fixture list that grows, names itself. Total: 114 leaves,
    55 rendered (corruption changes the message), 59 declared unrendered (28 envelope + 31
    payload)."""
    counts = {
        event_type: len(
            leaf_paths({k: v for k, v in facts.event_dict(event_type).items() if k != "event_type"})
        )
        for event_type in sorted(RENDERERS)
    }
    assert counts == {
        "invoice.issued.v1": 20,
        "order.cancelled.v1": 21,
        "order.completed.v1": 11,
        "order.confirmed.v1": 11,
        "order.despatched.v1": 14,
        "order.placed.v1": 25,
        "payment.received.v1": 12,
    }
    assert sum(counts.values()) == 114
    unrendered = sum(len(v) + len(ENVELOPE_NOT_RENDERED) for v in NOT_RENDERED.values())
    assert unrendered == 59
    assert sum(counts.values()) - unrendered == 55


def test_sentinel_a_template_that_ignores_a_leaf_is_caught(facts: Any) -> None:
    def ignores_company(event: Any) -> Any:
        message = render_order_confirmed(event)
        return dataclasses.replace(
            message,
            text_body=message.text_body.replace(f"Company: {event.payload.company_code}\n", ""),
            html_body=message.html_body.replace(
                f"<li>Company: {event.payload.company_code}</li>\n", ""
            ),
        )

    changed, _ = changed_paths(facts, "order.confirmed.v1", ignores_company)
    assert "payload.company_code" not in changed, "the sentinel template really ignores the field"
    population = set(
        leaf_paths(
            {k: v for k, v in facts.event_dict("order.confirmed.v1").items() if k != "event_type"}
        )
    )
    assert changed != population - ENVELOPE_NOT_RENDERED, "and the guard's equation notices"


def test_sentinel_a_template_that_renders_an_envelope_id_is_caught(facts: Any) -> None:
    def renders_aggregate_id(event: Any) -> Any:
        message = render_order_completed(event)
        return dataclasses.replace(
            message, text_body=message.text_body + f"\nAggregate: {event.aggregate_id}"
        )

    changed, _ = changed_paths(facts, "order.completed.v1", renders_aggregate_id)
    assert "aggregate_id" in changed, "the sentinel renders it"
    assert changed & ENVELOPE_NOT_RENDERED, (
        "and the guard sees an envelope field it declared unrendered"
    )


def test_sentinel_a_read_dropped_from_one_body_only_is_caught(facts: Any) -> None:
    def drops_company_from_the_text(event: Any) -> Any:
        message = render_order_confirmed(event)
        return dataclasses.replace(
            message,
            text_body=message.text_body.replace(f"Company: {event.payload.company_code}\n", ""),
        )

    changed, one_body_only = changed_paths(facts, "order.confirmed.v1", drops_company_from_the_text)

    assert "payload.company_code" in changed, (
        "the HTML still renders it, so the union alone is blind"
    )
    assert one_body_only == {"payload.company_code"}
