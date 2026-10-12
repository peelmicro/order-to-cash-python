"""`GET /orders/stream` (R55, feature 26): the frames, the headers, the filter and the reconnect.

The app is the REAL application (routes, middlewares, bearer auth, hub) driven through ASGI directly
(`asgi_stream`, tests/conftest.py): `httpx.ASGITransport` buffers a whole response and a stream
never
completes. Frames are parsed by the test's own SSE grammar, and every `data:` is validated against
the
generated models AND against the property lists read from `specs/shared/openapi.yaml`, both ways.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml

from otc_contracts import to_wire_json
from otc_contracts.generated import openapi

REPO_ROOT = Path(__file__).resolve().parents[4]
ORDER_A = UUID("0a0b0c0d-aaaa-4000-8000-0000000000a1")
ORDER_B = UUID("0a0b0c0d-bbbb-4000-8000-0000000000b2")
AT = "2026-08-18T10:15:02.100Z"


def schemas() -> dict[str, Any]:
    document = yaml.safe_load((REPO_ROOT / "specs/shared/openapi.yaml").read_text("utf-8"))
    found: dict[str, Any] = document["components"]["schemas"]
    return found


def update_json(order: UUID, status: str = "stock_reserved", n: int = 1) -> str:
    return to_wire_json(
        openapi.OrderStreamUpdate.model_validate_json(
            f'{{"eventId":"5b7a0f1e-1f22-4c1f-9f2a-8c1a1f2b{n:04d}","orderId":"{order}",'
            f'"status":"{status}","occurredAt":"{AT}"}}'
        )
    )


def timeline_json(order: UUID, n: int = 1) -> str:
    return to_wire_json(
        openapi.TimelineStreamEntry.model_validate_json(
            f'{{"eventId":"7d8e9f0a-1b2c-4d3e-8f4a-5b6c7d8e{n:04d}","orderId":"{order}",'
            f'"eventType":"credit.rejected.v1","occurredAt":"{AT}","summary":"Rechazado - café"}}'
        )
    )


# ------------------------------------------------------------------ the response and the auth


async def test_r55_the_stream_is_protected_and_answers_401_without_a_token(harness: Any) -> None:
    response = await harness.client.get("/orders/stream")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_r55_the_stream_is_in_the_protected_set_the_sweep_derives(harness: Any) -> None:
    from otc_gateway.presentation.public_routes import PUBLIC_OPERATIONS

    assert ("GET", "/orders/stream") not in PUBLIC_OPERATIONS


async def test_r55_the_response_is_an_event_stream_with_the_two_headers_the_contract_fixes(
    harness: Any, asgi_stream: Any
) -> None:
    stream = asgi_stream(harness.app, "/orders/stream", dict(harness.bearer()))
    await stream.frames(1, "the stream opening")

    assert stream.status == 200
    assert stream.headers["content-type"] == "text/event-stream"  # exactly: no charset parameter
    assert stream.headers["cache-control"] == "no-cache"  # the contract's `const`
    assert stream.headers["connection"] == "keep-alive"  # the contract's `const`


async def test_r55_get_orders_stream_is_never_read_as_the_order_by_id_route(
    harness: Any, asgi_stream: Any
) -> None:
    """`/orders/{id}` would answer a 400 Problem for the id `stream`; FastAPI's router matches in
    registration order, so `routes_stream` is included first (a guard, not a framework promise)."""
    stream = asgi_stream(harness.app, "/orders/stream", dict(harness.bearer()))
    (first,) = await stream.frames(
        1, "GET /orders/stream answered by the stream route, not by /orders/{id}"
    )

    assert stream.status == 200
    assert first.event == "stream.ready"


async def test_r55_a_malformed_order_id_is_a_400_problem_not_an_empty_stream(
    harness: Any,
) -> None:
    """`openapi.yaml` declares no 400 on this operation: an undeclared status, answered like every
    other route's malformed parameter (backlog 215 enumerates it)."""
    response = await harness.client.get(
        "/orders/stream?orderId=not-a-uuid", headers=harness.bearer()
    )

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"


# ----------------------------------------------------------------------------------- the frames


async def test_r55_stream_ready_is_the_first_frame_carries_no_id_and_validates_against_its_schema(
    harness: Any, asgi_stream: Any
) -> None:
    stream = asgi_stream(harness.app, f"/orders/stream?orderId={ORDER_A}", dict(harness.bearer()))
    (ready,) = await stream.frames(1, "stream.ready")

    assert ready.event == "stream.ready"
    assert ready.id is None, (
        "stream.ready carries no id: its cursor must never become a resume point"
    )
    body = ready.json()
    parsed = openapi.StreamReady.model_validate_json(ready.data)
    assert parsed.resumed is False
    assert parsed.order_id == ORDER_A
    assert body["orderId"] == str(ORDER_A)
    spec = schemas()["StreamReady"]
    assert set(body) <= set(spec["properties"]), "a key the schema does not declare"
    assert set(spec.get("required", [])) <= set(body), "a key the schema requires is missing"


async def test_r55_a_fresh_connection_replays_nothing_and_says_resumed_false(
    harness: Any, asgi_stream: Any
) -> None:
    harness.hub.publish("order.updated", ORDER_A, update_json(ORDER_A))
    stream = asgi_stream(harness.app, "/orders/stream", dict(harness.bearer()))
    (ready,) = await stream.frames(1, "stream.ready")

    assert ready.json()["resumed"] is False
    assert ready.json()["orderId"] is None  # whole stream: explicit null, as #7 and #8 send it
    assert ready.json()["cursor"], "a fresh connection gets a minted cursor"


async def test_r55_live_frames_carry_their_cursor_event_name_and_the_projectors_exact_data(
    harness: Any, asgi_stream: Any
) -> None:
    stream = asgi_stream(harness.app, "/orders/stream", dict(harness.bearer()))
    await stream.frames(1, "stream.ready")
    updated = update_json(ORDER_A)
    appended = timeline_json(ORDER_A)

    first = harness.hub.publish("order.updated", ORDER_A, updated)
    second = harness.hub.publish("timeline.appended", ORDER_A, appended)
    frames = await stream.frames(2, "the two live frames")

    assert [(f.id, f.event, f.data) for f in frames] == [
        (first.cursor, "order.updated", updated),
        (second.cursor, "timeline.appended", appended),
    ]
    # validated by the generated models (strict) and against the contract's own property lists
    openapi.OrderStreamUpdate.model_validate_json(frames[0].data)
    openapi.TimelineStreamEntry.model_validate_json(frames[1].data)
    for frame, name in ((frames[0], "OrderStreamUpdate"), (frames[1], "TimelineStreamEntry")):
        spec = schemas()[name]
        assert set(frame.json()) <= set(spec["properties"]), f"{name}: a key the schema lacks"
        assert set(spec.get("required", [])) <= set(frame.json()), f"{name}: a required key missing"
    assert frames[1].json()["summary"] == "Rechazado - café"  # non-ASCII raw, untouched
    assert {f.event for f in frames} <= {"order.updated", "timeline.appended"}


async def test_r55_ping_carries_no_id_and_validates_against_its_schema(
    harness: Any, asgi_stream: Any
) -> None:
    """The openapi `ping`-carries-no-`id` rule: a heartbeat id would become the client's resume
    point
    and every reconnect would answer `resumed: false`."""
    harness.with_stream(ping_interval_seconds=0.05)
    stream = asgi_stream(harness.app, "/orders/stream", dict(harness.bearer()))
    frames = await stream.frames(4, "stream.ready and three pings")

    pings = frames[1:]
    assert [f.event for f in pings] == ["ping", "ping", "ping"]
    assert all(f.id is None for f in frames), "a frame other than content carries an id: line"
    for ping in pings:
        parsed = openapi.StreamPing.model_validate_json(ping.data)
        assert parsed.at.tzinfo is not None
        spec = schemas()["StreamPing"]
        assert set(ping.json()) == set(spec["properties"])
    assert [f.event for f in frames].count("ping") == 3


async def test_r55_a_ping_never_enters_the_replay_buffer_so_it_is_never_a_resume_point(
    harness: Any, asgi_stream: Any
) -> None:
    hub = harness.with_stream(ping_interval_seconds=0.05)
    published = hub.publish("order.updated", ORDER_A, update_json(ORDER_A))
    size_before = len(hub._buffer)
    stream = asgi_stream(harness.app, "/orders/stream", dict(harness.bearer()))
    await stream.frames(3, "stream.ready and two pings")

    assert len(hub._buffer) == size_before == 1
    assert hub.replay_after(published.cursor).resumed is True


async def test_r55_pings_do_not_stop_content_from_arriving_between_them(
    harness: Any, asgi_stream: Any
) -> None:
    harness.with_stream(ping_interval_seconds=0.05)
    stream = asgi_stream(harness.app, "/orders/stream", dict(harness.bearer()))
    await stream.frames(2, "stream.ready and a ping")
    sent = harness.hub.publish("order.updated", ORDER_A, update_json(ORDER_A))

    frames = await stream.frames(3, "frames after the first ping")

    assert sent.cursor in [f.id for f in frames]


# ------------------------------------------------------------------------- the order filter


def interleaved(harness: Any) -> list[Any]:
    """A1 B1 A2 B2 A3: two orders whose frames alternate (a wrong filter shows in the middle)."""
    plan = [
        ("order.updated", ORDER_A, update_json(ORDER_A, "confirmed", 1)),
        ("order.updated", ORDER_B, update_json(ORDER_B, "stock_reserved", 2)),
        ("timeline.appended", ORDER_A, timeline_json(ORDER_A, 3)),
        ("timeline.appended", ORDER_B, timeline_json(ORDER_B, 4)),
        ("order.updated", ORDER_A, update_json(ORDER_A, "completed", 5)),
    ]
    return [harness.hub.publish(*entry) for entry in plan]


async def test_r55_order_id_restricts_the_live_stream_to_one_order(
    harness: Any, asgi_stream: Any
) -> None:
    stream = asgi_stream(harness.app, f"/orders/stream?orderId={ORDER_A}", dict(harness.bearer()))
    await stream.frames(1, "stream.ready")

    published = interleaved(harness)
    wanted = [published[0], published[2], published[4]]
    frames = await stream.frames(3, "the three frames of order A")

    assert [f.id for f in frames] == [p.cursor for p in wanted], (
        "?orderId= did not restrict the live stream to the one order"
    )
    assert all(f.json()["orderId"] == str(ORDER_A) for f in frames), "an order B frame leaked"
    # and nothing else arrives: a barrier frame for A comes next, not B's frames waiting behind
    barrier = harness.hub.publish("order.updated", ORDER_A, update_json(ORDER_A, "invoiced", 6))
    (after,) = await stream.frames(1, "the frame after the three")
    assert after.id == barrier.cursor


async def test_r55_order_id_restricts_the_replayed_frames_too(
    harness: Any, asgi_stream: Any
) -> None:
    published = interleaved(harness)
    anchor = harness.hub.publish("order.updated", ORDER_B, update_json(ORDER_B, "confirmed", 7))
    harness.hub.publish("order.updated", ORDER_A, update_json(ORDER_A, "invoiced", 8))
    stream = asgi_stream(
        harness.app,
        f"/orders/stream?orderId={ORDER_B}",
        {**harness.bearer(), "Last-Event-ID": published[0].cursor},
    )

    frames = await stream.frames(4, "ready and the replayed frames of order B")

    assert frames[0].json()["resumed"] is True
    assert [f.id for f in frames[1:]] == [
        published[1].cursor,
        published[3].cursor,
        anchor.cursor,
    ], "?orderId= did not restrict the replayed frames to the one order"


# ------------------------------------------------------------------------------- reconnecting


def twelve(harness: Any) -> list[Any]:
    return [
        harness.hub.publish("order.updated", ORDER_A, update_json(ORDER_A, "confirmed", n))
        for n in range(1, 13)
    ]


async def test_r55_a_reconnect_resumes_strictly_after_the_last_event_id_without_duplicates(
    harness: Any, asgi_stream: Any
) -> None:
    frames = twelve(harness)  # sequences 1..12: '...-10' sorts before '...-9' as a string
    last_seen = frames[8]  # sequence 9, in the MIDDLE of the buffer

    stream = asgi_stream(
        harness.app, "/orders/stream", {**harness.bearer(), "Last-Event-ID": last_seen.cursor}
    )
    received = await stream.frames(4, "ready and the three missed frames")

    ready, replayed = received[0], received[1:]
    assert ready.json()["resumed"] is True
    assert ready.json()["cursor"] == last_seen.cursor, (
        "stream.ready names the cursor it resumed from"
    )
    assert ready.id is None
    assert [f.id for f in replayed] == [f.cursor for f in frames[9:]], (
        "the reconnect did not replay exactly the frames after Last-Event-ID (10, 11, 12)"
    )
    assert last_seen.cursor not in [f.id for f in replayed], "the last seen frame was sent again"
    # a frame published after the reconnect follows the replay exactly once
    live = harness.hub.publish("order.updated", ORDER_A, update_json(ORDER_A, "invoiced", 13))
    (after,) = await stream.frames(1, "the live frame after the replay")
    assert after.id == live.cursor


async def test_r55_an_unknown_last_event_id_is_resumed_false_and_replays_nothing(
    harness: Any, asgi_stream: Any
) -> None:
    twelve(harness)
    stream = asgi_stream(
        harness.app, "/orders/stream", {**harness.bearer(), "Last-Event-ID": "1-999999"}
    )
    (ready,) = await stream.frames(1, "stream.ready")
    live = harness.hub.publish("order.updated", ORDER_A, update_json(ORDER_A, "invoiced", 13))
    (after,) = await stream.frames(1, "the first frame after stream.ready")

    assert ready.json()["resumed"] is False, "an unknown Last-Event-ID was reported as a resume"
    assert ready.json()["cursor"] == "1-999999"
    assert after.id == live.cursor, "a buffer miss replayed stale frames"


async def test_r55_an_evicted_last_event_id_is_resumed_false(
    harness: Any, asgi_stream: Any
) -> None:
    from otc_gateway.application.stream.hub import StreamHub

    hub = harness.with_stream(hub=StreamHub(lambda: 5, replay_capacity=5, subscriber_capacity=5))
    frames = [hub.publish("order.updated", ORDER_A, update_json(ORDER_A, n=n)) for n in range(1, 9)]
    stream = asgi_stream(
        harness.app, "/orders/stream", {**harness.bearer(), "Last-Event-ID": frames[0].cursor}
    )
    (ready,) = await stream.frames(1, "stream.ready")

    assert ready.json()["resumed"] is False


async def test_r55_a_client_that_falls_behind_is_disconnected_and_resumes_without_a_gap(
    harness: Any, asgi_stream: Any
) -> None:
    """The overflow policy (`StreamHub`): drop-oldest would let the client's cursor step over frames
    it never received. The client here READS k = 2 frames, then a burst overflows its queue and the
    stream ENDS; it reconnects with the id of the last frame it actually received, and what it
    received plus what the replay returns is exactly what was published: no gap, no duplicate."""
    from otc_gateway.application.stream.hub import StreamHub

    hub = harness.with_stream(hub=StreamHub(lambda: 5, replay_capacity=50, subscriber_capacity=3))
    slow = asgi_stream(harness.app, "/orders/stream", dict(harness.bearer()))
    await slow.frames(1, "stream.ready")
    early = [hub.publish("order.updated", ORDER_A, update_json(ORDER_A, n=n)) for n in (1, 2)]
    got = await slow.frames(len(early), "the k frames the slow client reads before it stalls")
    # no await between the publishes: the pump cannot run, so the queue (3) overflows on the 4th
    burst = [hub.publish("order.updated", ORDER_A, update_json(ORDER_A, n=n)) for n in range(3, 11)]
    published = early + burst
    received = got + await slow.leftovers("an overflowed stream")

    assert slow.error is None
    assert hub.subscriber_count == 0
    assert len(received) >= 1, "the slow client received nothing: it proves no cursor of its own"
    last_received = received[-1].id
    assert last_received is not None
    assert last_received in [p.cursor for p in published]
    position = [p.cursor for p in published].index(last_received) + 1
    resumed = asgi_stream(
        harness.app, "/orders/stream", {**harness.bearer(), "Last-Event-ID": last_received}
    )
    replayed = await resumed.frames(1 + len(published) - position, "ready and the unseen frames")

    assert replayed[0].json()["resumed"] is True
    assert [f.id for f in received] + [f.id for f in replayed[1:]] == [
        p.cursor for p in published
    ], "received + replayed is not exactly what was published: a gap or a duplicate"


# ------------------------------------------- no frame lost between the snapshot and the first read


def publish_when(harness: Any, window: str, published: list[Any], n: int) -> Any:
    """An `on_send` hook that publishes one frame while the app is inside the named write:
    `start` = `http.response.start` (after the subscription, before the snapshot) or `ready` =
    the `stream.ready` body (after the snapshot, before the first live read)."""
    fired: list[bool] = []

    def hook(message: dict[str, Any]) -> None:
        is_start = message["type"] == "http.response.start"
        is_ready = message.get("body", b"").startswith(b"event: stream.ready")
        if fired or not (is_start if window == "start" else is_ready):
            return
        fired.append(True)
        published.append(harness.hub.publish("order.updated", ORDER_A, update_json(ORDER_A, n=n)))

    return hook


@pytest.mark.parametrize("window", ["start", "ready"])
async def test_r55_a_frame_published_between_the_snapshot_and_the_first_live_read_is_delivered_on_a_fresh_connection(  # noqa: E501
    harness: Any, asgi_stream: Any, window: str
) -> None:
    published: list[Any] = []
    stream = asgi_stream(
        harness.app,
        "/orders/stream",
        dict(harness.bearer()),
        publish_when(harness, window, published, 1),
    )
    frames = await stream.frames(
        2, f"stream.ready and the frame published in the {window} write", within=3
    )

    assert frames[0].event == "stream.ready"
    assert frames[1].id == published[0].cursor, f"the {window}-window frame was lost"


async def test_r55_a_frame_published_between_the_snapshot_and_the_first_live_read_is_delivered_on_a_resumed_connection(  # noqa: E501
    harness: Any, asgi_stream: Any
) -> None:
    earlier = [
        harness.hub.publish("order.updated", ORDER_A, update_json(ORDER_A, n=n)) for n in (1, 2, 3)
    ]
    published: list[Any] = []
    stream = asgi_stream(
        harness.app,
        "/orders/stream",
        {**harness.bearer(), "Last-Event-ID": earlier[0].cursor},
        publish_when(harness, "ready", published, 4),
    )
    frames = await stream.frames(
        4, "ready, the two replayed frames and the frame published mid-write", within=3
    )

    ids = [f.id for f in frames[1:]]
    assert frames[0].json()["resumed"] is True
    assert ids[:2] == [earlier[1].cursor, earlier[2].cursor]
    assert published[0].cursor in ids, "the frame published while stream.ready was written was lost"
