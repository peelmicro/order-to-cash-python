"""D4 (PR41, ledger L21, L22): ids are lowercase hyphenated strings, instants are `.mmmZ` strings,
integers keep their Python value; `detail` carries camelCase keys.

The rendering is checked on the emitted pipeline and on the placeholder, and `bson.encode` is the
instrument for the native-`UUID` trap (pymongo refuses a `uuid.UUID` under its default
representation: it raises).
"""

import re
import uuid
from typing import Any

import bson
import pytest

from otc_projector.application.projection import project
from otc_projector.infrastructure.persistence.delta_to_pipeline import delta_to_pipeline
from otc_projector.infrastructure.persistence.read_model_document import placeholder

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
INSTANT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def strings_under(tree: Any, key_path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str]]:
    found: list[tuple[tuple[str, ...], str]] = []
    if isinstance(tree, dict):
        for name, value in tree.items():
            found.extend(strings_under(value, (*key_path, name)))
    elif isinstance(tree, list):
        for item in tree:
            found.extend(strings_under(item, key_path))
    elif isinstance(tree, str):
        found.append((key_path, tree))
    return found


def entry_of(pipeline: list[dict[str, object]]) -> dict[str, Any]:
    events: Any = pipeline[0]["$set"]
    concat = events["events"]["$let"]["vars"]["all"]["$concatArrays"]
    entry: dict[str, Any] = concat[1][0]["$literal"]
    return entry


def test_pr41_ids_are_lowercase_hyphenated_strings_instants_are_mmmz_strings_and_integers_keep_their_python_value(  # noqa: E501
    facts: Any,
) -> None:
    event = facts.build("order.cancelled.v1")
    delta = project(event)
    pipeline = delta_to_pipeline(delta, "projector:" + delta.entry.event_id)
    entry = entry_of(pipeline)
    for field in ("eventId", "causationId"):
        assert isinstance(entry[field], str), field
        assert UUID_PATTERN.match(entry[field]), f"{field} is not a lowercase hyphenated id"
    assert INSTANT_PATTERN.match(entry["occurredAt"])
    holder = placeholder(delta.order_id, entry["occurredAt"])
    for field in ("_id", "orderId"):
        value = holder[field]
        assert isinstance(value, str), field
        assert UUID_PATTERN.match(value), f"{field} is not a lowercase hyphenated id"
    assert INSTANT_PATTERN.match(str(holder["updatedAt"]))
    # the `$max` operands of `updatedAt` are compared as TEXT on the server: both must be `.mmmZ`
    # instants (an `isoformat()` there ends `+00:00` and orders wrongly against `...Z`)
    updated_at = pipeline[0]["$set"]["updatedAt"]["$max"]  # type: ignore[index]
    assert len(updated_at) == 2
    for operand in updated_at:
        text = operand["$literal"] if "$literal" in operand else operand["$ifNull"][1]["$literal"]
        assert INSTANT_PATTERN.match(text), f"updatedAt operand {text!r} is not a .mmmZ instant"
    # `bson.encode` succeeds: no native UUID, no datetime, no Decimal anywhere in the stage
    assert bson.encode({"pipeline": pipeline}), "the stage could not be BSON-encoded"
    assert bson.encode(holder)
    # an integer keeps its Python value
    placed = delta_to_pipeline(project(facts.build("order.placed.v1")), "projector:x")
    totals = placed[0]["$set"]["totals.totalAmount"]  # type: ignore[index]
    assert totals == {"$literal": 124254}


def test_pr41_a_native_uuid_would_be_refused_by_the_driver() -> None:
    with pytest.raises(ValueError, match=r"cannot encode native uuid\.UUID"):
        bson.encode({"_id": uuid.UUID("0a0b0c0d-0000-4000-8000-0000000000aa")})


def test_pr41_detail_from_compensation_steps_carries_camel_case_keys_and_mmmz_instants(
    facts: Any,
) -> None:
    steps = [
        {
            "step": "stock_released",
            "event_id": "44444444-4444-4444-8444-444444444444",
            "event_type": "stock.released.v1",
            "occurred_at": "2026-03-11T12:00:00.123Z",
        }
    ]
    event = facts.build("order.cancelled.v1", payload={"compensation_steps": steps})
    delta = project(event)
    assert delta.entry.detail is not None
    step = delta.entry.detail["compensationSteps"][0]  # type: ignore[index]
    assert set(step) == {"step", "eventId", "eventType", "occurredAt"}, "snake_case leaked"
    assert INSTANT_PATTERN.match(step["occurredAt"])
    assert UUID_PATTERN.match(step["eventId"])
    entry = entry_of(delta_to_pipeline(delta, "projector:x"))
    assert entry["detail"]["compensationSteps"][0]["occurredAt"] == "2026-03-11T12:00:00.123Z"
