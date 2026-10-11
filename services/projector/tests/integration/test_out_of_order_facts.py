"""J2 (R52, PR11, PR12): out-of-order facts never regress the document.

The reference-fact case is named for what it PROVES: no two facts write one reference field, so
the overwrite case (`$ifNull` against a non-null stored reference) is UNREACHABLE through the
projection, and the `$ifNull` proof is `unit/test_delta_to_pipeline.py::test_pr11_*` on the emitted
tree (#7's review N6). What this integration case proves is the other half: each reference fact
fills ITS OWN field and nothing else, whatever the arrival order.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

pytestmark = pytest.mark.integration

ORDER = uuid.UUID("0a0b0c0d-9999-4000-8000-0000000000c1")


def at(second: int) -> datetime:
    return datetime(2026, 5, 2, 9, 0, second, 0, tzinfo=UTC)


async def test_r52_appends_the_timeline_entry_without_regressing_the_document_status_or_overwriting_newer_references(  # noqa: E501
    read_model: Any, facts: Any
) -> None:
    despatched = facts.build(
        "order.despatched.v1",
        correlation_id=ORDER,
        occurred_at=at(5),
        payload={"despatch_reference": "DES-717171"},
    )
    placed = facts.build("order.placed.v1", correlation_id=ORDER, occurred_at=at(1))
    await read_model.apply(despatched)  # the document does not exist: a placeholder is created
    after_first = await read_model.document(ORDER)
    assert after_first["status"] == "despatched"
    assert after_first["headerComplete"] is False
    await read_model.apply(placed)  # placed (rank 1) after despatched (rank 5)
    document = await read_model.document(ORDER)
    assert document["status"] == "despatched", "a late order.placed regressed the status"
    assert document["statusRank"] == 5
    assert document["references"]["despatchReference"] == "DES-717171"
    assert len(document["events"]) == 2
    assert document["headerComplete"] is True
    assert document["orderReference"] == "ORD-000101"
    assert [e["eventType"] for e in document["events"]] == [
        "order.placed.v1",
        "order.despatched.v1",
    ]
    # a status-less fact after a terminal status leaves the status alone
    completed = facts.build("order.completed.v1", correlation_id=ORDER, occurred_at=at(8))
    released = facts.build("credit.released.v1", correlation_id=ORDER, occurred_at=at(9))
    await read_model.apply(completed)
    await read_model.apply(released)  # credit.released arrives AFTER order.completed
    document = await read_model.document(ORDER)
    assert document["status"] == "completed", "credit.released after completed changed the status"
    assert document["statusRank"] == 98
    assert len(document["events"]) == 4


async def test_pr12_a_status_less_fact_on_an_absent_order_keeps_the_placeholder_status(
    read_model: Any, facts: Any
) -> None:
    """A rank-0 fact against a rank-0 placeholder: a `>=` instead of `>` would write `null`."""
    event = facts.build("stock.rejected.v1", correlation_id=ORDER, occurred_at=at(2))
    await read_model.apply(event)
    document = await read_model.document(ORDER)
    assert document["status"] == "placed", f"the status became {document['status']!r}"
    assert document["statusRank"] == 0


@pytest.mark.parametrize(
    ("event_type", "field", "payload"),
    [
        ("order.despatched.v1", "despatchReference", {"despatch_reference": "DES-717171"}),
        ("invoice.issued.v1", "invoiceReference", {"invoice_reference": "INV-838383"}),
        ("payment.received.v1", "paymentReference", {"payment_reference": "PAY-949494"}),
    ],
)
async def test_pr11_each_reference_fact_fills_only_its_own_reference(
    read_model: Any, facts: Any, event_type: str, field: str, payload: dict[str, str]
) -> None:
    await read_model.apply(facts.build(event_type, correlation_id=ORDER, payload=payload))
    references = (await read_model.document(ORDER))["references"]
    assert references[field] == next(iter(payload.values()))
    assert all(value is None for name, value in references.items() if name != field), references
