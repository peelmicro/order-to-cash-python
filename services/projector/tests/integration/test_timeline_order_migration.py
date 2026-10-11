"""H2 (PR32, PR35): bringing documents to the current timeline-order version at boot.

Documents are hand-built at version 1 (the old order: a tie group stored in the wrong causal order),
not produced by the projector, because the migration is for documents that predate the rule.
"""

import logging
from typing import Any

import pytest

from otc_projector.infrastructure.persistence.read_model_document import placeholder
from otc_projector.infrastructure.persistence.timeline_order_migration import (
    migrate_timeline_order,
)

pytestmark = pytest.mark.integration

TIE = "2026-03-01T10:00:00.000Z"
LATER = "2026-03-01T10:00:01.000Z"


def entry(event_id: str, cause: str | None, at: str = TIE) -> dict[str, Any]:
    document: dict[str, Any] = {
        "eventId": event_id,
        "eventType": "x.y.v1",
        "occurredAt": at,
        "summary": f"summary of {event_id}",
    }
    if cause is not None:
        document["causationId"] = cause
    return document


def document(order_id: str, version: int, events: list[dict[str, Any]]) -> dict[str, Any]:
    base = placeholder(order_id, LATER)
    base["events"] = events
    base["timelineOrderVersion"] = version
    base["processedEventKeys"] = sorted(f"projector:{e['eventId']}" for e in events)
    return base


async def test_pr32_a_document_at_version_one_is_re_sorted_and_stamped(read_model: Any) -> None:
    # the chain c-root <- b-middle <- a-leaf, stored the way version 1 stored it: by eventId
    stale = document(
        "order-v1",
        1,
        [entry("a-leaf", "b-middle"), entry("b-middle", "c-root"), entry("c-root", "command-1")],
    )
    await read_model.collection.insert_one(stale)
    result = await migrate_timeline_order(read_model.collection)
    after = await read_model.document("order-v1")
    assert [e["eventId"] for e in after["events"]] == ["c-root", "b-middle", "a-leaf"]
    assert after["timelineOrderVersion"] == 2
    assert result.migrated == 1
    # no other client-visible field moved
    for field in ("updatedAt", "status", "statusRank", "references", "processedEventKeys"):
        assert after[field] == stale[field], field
    assert all("__depth" not in e for e in after["events"]), "the depth leaked into the document"


async def test_pr32_a_current_document_receives_no_write(read_model: Any) -> None:
    current = document("order-v2", 2, [entry("a-leaf", "b-middle"), entry("b-middle", "c-root")])
    await read_model.collection.insert_one(current)
    before = await read_model.raw("order-v2")
    read_model.log.clear()
    result = await migrate_timeline_order(read_model.collection)
    after = await read_model.raw("order-v2")
    assert after == before, "a current document was rewritten"
    assert result.migrated == 0, "a current document was counted as migrated"
    written = [n for n in read_model.log.against("order_timeline") if n == "update"]
    assert len(written) == 1, "the migration issues one update_many whose filter selects nothing"


async def test_pr35_never_invents_a_causation_id_and_reports_both_counts(
    read_model: Any, caplog: pytest.LogCaptureFixture
) -> None:
    await read_model.collection.insert_one(
        document("order-without-edge", 1, [entry("z-last", None), entry("a-first", None, LATER)])
    )
    await read_model.collection.insert_one(
        document("order-with-edges", 1, [entry("m", "c-0"), entry("n", "m")])
    )
    with caplog.at_level(logging.INFO, logger="otc_projector.persistence.timeline_order_migration"):
        result = await migrate_timeline_order(read_model.collection)
    migrated = await read_model.document("order-without-edge")
    assert all("causationId" not in e for e in migrated["events"]), "an edge was invented"
    assert result.migrated == 2
    assert result.still_without_causation_id == 1
    messages = [r.getMessage() for r in caplog.records]
    assert any("2 document(s) migrated" in m and "1 of them still hold" in m for m in messages), (
        messages
    )
