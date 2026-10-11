"""J4, J5 (R28, R24, PR10, PR31): the causal order on the server.

The live tie-group shapes (design 5.4): `stock.released.v1` -> `order.cancelled.v1` (R28) and
`payment.received.v1` -> `credit.released.v1` -> `order.completed.v1` (R24), each fact citing the
`eventId` of the previous one and reusing its `occurredAt`. The `eventId`s are chosen so that the
fallback (`eventId` ascending) ALONE would invert the expected order, and the facts are DELIVERED in
the inverting order.
"""

import random
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_projector.domain.timeline_order import TimelinePosition, causal_order
from otc_projector.infrastructure.persistence.timeline_order import timeline_order_expression

pytestmark = pytest.mark.integration

ORDER = uuid.UUID("0a0b0c0d-bbbb-4000-8000-0000000000e1")
INSTANT = datetime(2026, 5, 3, 9, 0, 0, 123000, tzinfo=UTC)


def eid(text: str) -> uuid.UUID:
    return uuid.UUID(text)


async def test_r28_stock_released_precedes_the_order_cancelled_that_names_it_with_adversarial_event_ids(  # noqa: E501
    read_model: Any, facts: Any
) -> None:
    released_id = eid("ffffffff-0000-4000-8000-000000000001")  # the LARGEST id, yet first
    cancelled_id = eid("00000000-0000-4000-8000-000000000002")  # the smallest id, yet last
    released = facts.build(
        "stock.released.v1",
        correlation_id=ORDER,
        event_id=released_id,
        causation_id=eid("11111111-0000-4000-8000-0000000000aa"),
        occurred_at=INSTANT,
    )
    cancelled = facts.build(
        "order.cancelled.v1",
        correlation_id=ORDER,
        event_id=cancelled_id,
        causation_id=released_id,
        occurred_at=INSTANT,
    )
    await read_model.apply(cancelled)  # delivered in the inverting order
    await read_model.apply(released)
    document = await read_model.document(ORDER)
    assert [e["eventId"] for e in document["events"]] == [str(released_id), str(cancelled_id)], (
        "R28: stock.released must precede the order.cancelled that names it"
    )


async def test_r24_the_completion_triple_is_stored_in_causal_order_with_adversarial_event_ids(
    read_model: Any, facts: Any
) -> None:
    payment_id = eid("cccccccc-0000-4000-8000-000000000001")
    release_id = eid("bbbbbbbb-0000-4000-8000-000000000002")
    completed_id = eid("aaaaaaaa-0000-4000-8000-000000000003")
    payment = facts.build(
        "payment.received.v1",
        correlation_id=ORDER,
        event_id=payment_id,
        causation_id=eid("11111111-0000-4000-8000-0000000000bb"),
        occurred_at=INSTANT,
    )
    release = facts.build(
        "credit.released.v1",
        correlation_id=ORDER,
        event_id=release_id,
        causation_id=payment_id,
        occurred_at=INSTANT,
    )
    completed = facts.build(
        "order.completed.v1",
        correlation_id=ORDER,
        event_id=completed_id,
        causation_id=release_id,
        occurred_at=INSTANT,
    )
    for event in (completed, release, payment):  # fully reversed
        await read_model.apply(event)
    document = await read_model.document(ORDER)
    assert [e["eventId"] for e in document["events"]] == [
        str(payment_id),
        str(release_id),
        str(completed_id),
    ], "R24: payment.received, credit.released, order.completed must be stored in causal order"
    assert document["status"] == "completed"


# ------------------------------------------------------------------- J5: the differential test

SEED = 20261011
SETS = 250
INSTANTS = ["2026-05-03T09:00:00.000Z", "2026-05-03T09:00:00.001Z", "2026-05-03T09:00:00.002Z"]


def generated_sets(seed: int, count: int) -> list[list[TimelinePosition]]:
    rng = random.Random(seed)  # noqa: S311 - a reproducible test generator, not security
    sets: list[list[TimelinePosition]] = []
    for _ in range(count):
        size = rng.randint(0, 9)
        ids = [f"e{rng.randrange(10_000):05d}" for _ in range(size)]
        ids = list(dict.fromkeys(ids))  # distinct eventIds
        entries = []
        for event_id in ids:
            kind = rng.random()
            cause: str | None
            if kind < 0.2:
                cause = None  # no causationId
            elif kind < 0.35:
                cause = "foreign-command-id"  # names nothing
            elif kind < 0.42:
                cause = event_id  # a self-edge
            else:
                cause = rng.choice(ids)  # an edge, possibly across groups, possibly a cycle
            entries.append(TimelinePosition(event_id, rng.choice(INSTANTS), cause))
        rng.shuffle(entries)
        sets.append(entries)
    return sets


async def server_order(read_model: Any, entries: list[TimelinePosition]) -> list[str]:
    documents = [
        {
            "eventId": e.event_id,
            "occurredAt": e.occurred_at,
            **({"causationId": e.causation_id} if e.causation_id is not None else {}),
        }
        for e in entries
    ]
    pipeline = [
        {"$documents": [{"events": documents}]},
        {"$set": {"events": timeline_order_expression("$events")}},
    ]
    database = read_model.client.get_database(read_model.database)
    cursor = await database.aggregate(pipeline)
    (result,) = [row async for row in cursor]
    return [e["eventId"] for e in result["events"]]


async def test_pr10_the_pipeline_agrees_with_the_reference_rule_on_generated_entry_sets(
    read_model: Any,
) -> None:
    print(f"differential seed {SEED}, {SETS} sets")
    disagreements = []
    for index, entries in enumerate(generated_sets(SEED, SETS)):
        expected = [e.event_id for e in causal_order(entries)]
        actual = await server_order(read_model, entries)
        if actual != expected:
            disagreements.append((index, entries, expected, actual))
    assert disagreements == [], (
        f"seed {SEED}: the server disagrees with the reference rule on set "
        f"{disagreements[0][0]}: entries {disagreements[0][1]}, "
        f"reference {disagreements[0][2]}, server {disagreements[0][3]}"
    )


async def test_pr10_the_generator_exercises_ties_cycles_foreign_causes_and_missing_edges() -> None:
    sets = generated_sets(SEED, SETS)
    flat = [e for s in sets for e in s]
    assert any(len(s) == 0 for s in sets), "no empty set"
    assert any(e.causation_id is None for e in flat), "no entry without a causationId"
    assert any(e.causation_id == "foreign-command-id" for e in flat), "no foreign cause"
    assert any(e.causation_id == e.event_id for e in flat), "no self-edge"
    cycles = 0
    for s in sets:
        by_id = {e.event_id: e for e in s}
        for e in s:
            seen = {e.event_id}
            cursor = by_id.get(e.causation_id) if e.causation_id else None
            while cursor is not None and cursor.event_id not in seen:
                seen.add(cursor.event_id)
                cursor = by_id.get(cursor.causation_id) if cursor.causation_id else None
            if cursor is not None and cursor.event_id != e.event_id:
                cycles += 1
    assert cycles > 0, "no cycle of length > 1"
    assert any(len({e.occurred_at for e in s}) < len(s) and len(s) > 2 for s in sets), (
        "no tie group with several entries"
    )


async def test_pr31_a_cycle_a_foreign_cause_and_a_missing_causation_id_all_terminate_with_every_entry_once(  # noqa: E501
    read_model: Any, facts: Any
) -> None:
    a, b, c = (eid(f"{n}0000000-0000-4000-8000-00000000000{n}") for n in (1, 2, 3))
    d, f = eid("40000000-0000-4000-8000-000000000004"), eid("50000000-0000-4000-8000-000000000005")
    spec = [
        # a <-> b is a two-cycle; c cites a command id (foreign); d has a self-edge; f is plain
        ("order.confirmed.v1", a, b),
        ("order.despatched.v1", b, a),
        ("invoice.issued.v1", c, eid("99999999-0000-4000-8000-000000000009")),
        ("payment.received.v1", d, d),
        ("order.completed.v1", f, eid("88888888-0000-4000-8000-000000000008")),
    ]
    for event_type, event_id, cause in spec:
        await read_model.apply(
            facts.build(
                event_type,
                correlation_id=ORDER,
                event_id=event_id,
                causation_id=cause,
                occurred_at=INSTANT,
            )
        )
    document = await read_model.document(ORDER)
    stored = [e["eventId"] for e in document["events"]]
    assert sorted(stored) == sorted(str(x) for x in (a, b, c, d, f)), "an entry was lost or doubled"
    # a second apply of an unrelated fact (a later instant) leaves the stored order identical
    later = facts.build(
        "credit.released.v1",
        correlation_id=ORDER,
        occurred_at=datetime(2026, 5, 3, 9, 0, 5, tzinfo=UTC),
    )
    await read_model.apply(later)
    again = [e["eventId"] for e in (await read_model.document(ORDER))["events"]]
    assert again[:-1] == stored, "applying an unrelated fact reordered the earlier entries"
    assert again[-1] == str(later.event_id)
    # and the reference rule predicts exactly the stored order
    entries = [
        TimelinePosition(str(event_id), "2026-05-03T09:00:00.123Z", str(cause))
        for _, event_id, cause in spec
    ]
    assert [e.event_id for e in causal_order(entries)] == stored
