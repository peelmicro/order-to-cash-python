"""G2, G3, G4 (R55, PR17, PR18, PR19, PR33, PR42): the update signal against a real NATS and a real
MongoDB, through the real handler.

Subscriptions are created FIRST. 'Nothing was published' is proven with a barrier (see `Frames`),
never a sleep, and every wait is bounded by `asyncio.timeout` with a message naming the claim.
"""

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

from otc_projector.application.handlers import ProjectFactHandler
from otc_projector.application.messages import ProjectFactCommand
from otc_projector.application.outcome import ProjectionOutcome
from otc_projector.application.scope import ProjectorScope
from otc_projector.infrastructure.signal.nats_update_signal_publisher import (
    NatsUpdateSignalPublisher,
)

pytestmark = pytest.mark.integration

OPENAPI = Path(__file__).resolve().parents[4] / "specs" / "shared" / "openapi.yaml"
BARRIER = b"__barrier__"
BOUND_SECONDS = 20


def handler_for(read_model: Any, connection: Any) -> ProjectFactHandler:
    return ProjectFactHandler(
        ProjectorScope(read_model=read_model.writer, signals=NatsUpdateSignalPublisher(connection))
    )


async def until(claim: str, condition: Any) -> None:
    """Wait on monotonic evidence, bounded, with a message naming the claim."""
    deadline = asyncio.get_running_loop().time() + BOUND_SECONDS
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            pytest.fail(f"{claim}: not observed within {BOUND_SECONDS} s")
        await asyncio.sleep(0.01)


async def barrier(connection: Any, order_id: str, *watchers: Any) -> None:
    """Publish a barrier on both order subjects and wait until every watcher has seen its own."""
    targets = [
        (w, w.barriers + (2 if w.subject == "readmodel.>" else 1))  # the whole stream sees both
        for w in watchers
    ]
    for subject in (
        f"readmodel.order.updated.{order_id}",
        f"readmodel.timeline.appended.{order_id}",
    ):
        await connection.publish(subject, BARRIER)
    await connection.flush()
    for watcher, target in targets:
        await until(
            f"the barrier on {watcher.subject}",
            lambda w=watcher, t=target: w.barriers >= t,
        )


async def test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery(  # noqa: E501
    read_model: Any, nats_connection: Any, frames_factory: Any, facts: Any
) -> None:
    order = uuid.UUID("0a0b0c0d-2222-4000-8000-0000000000bb")
    whole = await frames_factory("readmodel.>")
    updated = await frames_factory(f"readmodel.order.updated.{order}")
    appended = await frames_factory(f"readmodel.timeline.appended.{order}")
    handler = handler_for(read_model, nats_connection)
    placed = facts.build("order.placed.v1", correlation_id=order)
    confirmed = facts.build("order.confirmed.v1", correlation_id=order)

    first = await handler.handle(ProjectFactCommand(event=placed))
    second = await handler.handle(ProjectFactCommand(event=confirmed))
    await nats_connection.flush()
    await until("two pairs of frames", lambda: len(whole.received) >= 4)

    redelivery = await handler.handle(ProjectFactCommand(event=placed))
    await barrier(nats_connection, str(order), whole, updated, appended)

    assert (first, second) == (ProjectionOutcome.PROCESSED, ProjectionOutcome.PROCESSED)
    assert redelivery is ProjectionOutcome.DUPLICATE
    assert len(updated.received) == 2, f"order.updated frames: {len(updated.received)}"
    assert len(appended.received) == 2, f"timeline.appended frames: {len(appended.received)}"
    assert len(whole.received) == 4, f"whole-stream frames: {len(whole.received)}"
    assert [f["eventId"] for _, f in updated.frames()] == [
        str(placed.event_id),
        str(confirmed.event_id),
    ]
    assert [f["eventId"] for _, f in appended.frames()] == [
        str(placed.event_id),
        str(confirmed.event_id),
    ]


def required_fields(schema: str) -> list[str]:
    document = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    required: list[str] = document["components"]["schemas"][schema]["required"]
    return required


async def test_pr17_both_payloads_carry_openapis_required_fields_read_from_the_contract(
    read_model: Any, nats_connection: Any, frames_factory: Any, facts: Any
) -> None:
    order = uuid.UUID("0a0b0c0d-3333-4000-8000-0000000000cc")
    updated = await frames_factory(f"readmodel.order.updated.{order}")
    appended = await frames_factory(f"readmodel.timeline.appended.{order}")
    handler = handler_for(read_model, nats_connection)
    placed = facts.build(
        "order.placed.v1", correlation_id=order, payload={"retailer_code": "Café-Zürich"}
    )
    await handler.handle(ProjectFactCommand(event=placed))
    await until("one pair of frames", lambda: updated.received and appended.received)
    ((_, update),) = updated.frames()
    ((_, entry),) = appended.frames()
    for field in required_fields("OrderStreamUpdate"):
        assert field in update, f"OrderStreamUpdate requires {field}: absent from {sorted(update)}"
    for field in required_fields("TimelineStreamEntry"):
        assert field in entry, f"TimelineStreamEntry requires {field}: absent from {sorted(entry)}"
    # non-ASCII arrives raw: the wire text carries the character, not a \u escape
    raw = appended.received[0]
    assert "Zürich".encode() in raw
    assert b"\\u00" not in raw
    assert "Café-Zürich" in entry["summary"]


async def test_pr33_the_timeline_appended_payload_carries_causation_id(
    read_model: Any, nats_connection: Any, frames_factory: Any, facts: Any
) -> None:
    order = uuid.UUID("0a0b0c0d-4444-4000-8000-0000000000dd")
    appended = await frames_factory(f"readmodel.timeline.appended.{order}")
    sentinel = uuid.UUID("99999999-9999-4999-8999-999999999999")
    event = facts.build("order.confirmed.v1", correlation_id=order, causation_id=sentinel)
    await handler_for(read_model, nats_connection).handle(ProjectFactCommand(event=event))
    await until("the timeline.appended frame", lambda: appended.received)
    ((_, entry),) = appended.frames()
    assert entry["causationId"] == str(sentinel)
    assert entry["eventId"] == str(event.event_id)


async def test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references(
    read_model: Any, nats_connection: Any, frames_factory: Any, facts: Any
) -> None:
    order = uuid.UUID("0a0b0c0d-5555-4000-8000-0000000000ee")
    updated = await frames_factory(f"readmodel.order.updated.{order}")
    handler = handler_for(read_model, nats_connection)
    confirmed = facts.build("order.confirmed.v1", correlation_id=order)
    despatched = facts.build(
        "order.despatched.v1",
        correlation_id=order,
        payload={"despatch_reference": "DES-717171"},
    )
    await handler.handle(ProjectFactCommand(event=confirmed))
    await handler.handle(ProjectFactCommand(event=despatched))
    await until("two order.updated frames", lambda: len(updated.received) >= 2)
    first, second = (frame for _, frame in updated.frames())
    assert first["status"] == "confirmed", (
        f"the signal carries the PRE-apply status {first['status']!r} (return_document default)"
    )
    assert second["status"] == "despatched", (
        f"the signal carries the PRE-apply status {second['status']!r}"
    )
    assert second["references"]["despatchReference"] == "DES-717171", (
        "the signal carries the pre-apply references"
    )
    assert first["references"]["despatchReference"] is None, "a reference appeared too early"
