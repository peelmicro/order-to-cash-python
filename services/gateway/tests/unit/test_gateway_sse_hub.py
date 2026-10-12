"""`StreamHub` (R55): the replay buffer fed in cursor order, the fan-out, and the overflow policy.

Ported from #7 `stream-hub.spec.ts` (3 cases) and #8 `StreamHubTests.cs`. The overflow policy is the
one deliberate difference from #8 (see `otc_gateway.application.stream.hub`).
"""

import asyncio
import inspect
from uuid import UUID

import pytest

from otc_gateway.application.stream.hub import StreamHub

A = UUID(int=0xA)
B = UUID(int=0xB)


def hub_of(*, replay: int = 50, subscriber: int = 10) -> StreamHub:
    return StreamHub(
        lambda: 1_755_511_234_567, replay_capacity=replay, subscriber_capacity=subscriber
    )


async def drain(subscription: object, count: int) -> list[str]:
    from otc_gateway.application.stream.hub import Subscription

    assert isinstance(subscription, Subscription)
    found = []
    async with asyncio.timeout(5):
        for _ in range(count):
            frame = await subscription.get()
            assert frame is not None
            found.append(frame.cursor)
    return found


async def test_r55_publish_gives_every_live_subscriber_the_frame_with_one_fresh_cursor() -> None:
    hub = hub_of()
    first, second = hub.subscribe(), hub.subscribe()

    frame = hub.publish("order.updated", A, '{"x":1}')

    assert await drain(first, 1) == [frame.cursor]
    assert await drain(second, 1) == [frame.cursor]
    assert frame.event_type == "order.updated"
    assert frame.order_id == A
    assert frame.data_json == '{"x":1}'


async def test_r55_replay_after_resumes_from_the_buffer_strictly_after_the_cursor() -> None:
    hub = hub_of()
    frames = [hub.publish("order.updated", A, str(n)) for n in range(1, 13)]

    result = hub.replay_after(frames[8].cursor)

    assert result.resumed is True
    assert [f.data_json for f in result.missed] == ["10", "11", "12"]


async def test_r55_replay_after_nothing_is_a_fresh_connection() -> None:
    hub = hub_of()
    hub.publish("order.updated", A, "{}")

    assert hub.replay_after(None).resumed is False


async def test_r55_stream_ready_and_ping_cursors_are_minted_but_never_buffered() -> None:
    hub = hub_of(replay=3)
    frame = hub.publish("order.updated", A, "{}")

    minted = hub.mint_cursor()
    for _ in range(10):
        hub.mint_cursor()

    assert minted != frame.cursor
    assert hub.replay_after(minted).resumed is False  # a heartbeat id is never a resume point
    assert hub.replay_after(frame.cursor).resumed is True  # and minting evicted nothing


async def test_r55_the_buffer_order_is_the_cursor_order_under_interleaved_publishers() -> None:
    """`publish` is one uninterruptible step (no `await`): the cursor is minted, buffered and fanned
    out together. Held two ways: it is not a coroutine function, and 300 tasks that yield between
    publishes still leave the buffer in cursor order, the subscriber in the same order."""
    assert not inspect.iscoroutinefunction(StreamHub.publish), (
        "StreamHub.publish became a coroutine function: a suspension between minting the "
        "cursor and buffering the frame would let the buffer order differ from the cursor order"
    )
    hub = hub_of(replay=1000, subscriber=1000)
    anchor = hub.publish("order.updated", A, "anchor")
    subscription = hub.subscribe()

    async def publisher(n: int) -> None:
        for step in range(3):
            await asyncio.sleep(0)
            hub.publish("order.updated", A, f"{n}-{step}")

    async with asyncio.TaskGroup() as group:
        for n in range(100):
            group.create_task(publisher(n))

    live = await drain(subscription, 300)
    buffered = [f.cursor for f in hub.replay_after(anchor.cursor).missed]
    sequences = [int(c.rsplit("-", 1)[1]) for c in live]
    assert sequences == list(range(2, 302))
    assert buffered == live, "the replay buffer's order is not the order the cursors were minted in"


async def test_r55_unsubscribe_stops_delivery_and_the_count_returns_to_zero() -> None:
    hub = hub_of()
    kept, gone = hub.subscribe(), hub.subscribe()
    assert hub.subscriber_count == 2

    hub.unsubscribe(gone)
    frame = hub.publish("order.updated", A, "{}")

    assert hub.subscriber_count == 1
    assert await drain(kept, 1) == [frame.cursor]
    hub.unsubscribe(gone)  # idempotent
    assert hub.subscriber_count == 1


async def test_r55_a_slow_subscriber_overflows_without_blocking_the_publisher_or_a_neighbour() -> (
    None
):
    hub = hub_of(replay=100, subscriber=3)
    slow, quick = hub.subscribe(), hub.subscribe()

    async with asyncio.timeout(2):  # a publisher that waited on `slow` would never get here
        frames = []
        for n in range(8):
            frames.append(hub.publish("order.updated", A, str(n)))
            assert await quick.get() is not None  # the neighbour keeps up with every frame

    assert slow.overflowed is True, "a full client queue was not marked overflowed"
    assert await slow.get() is None  # the stream ends; the client resumes from its cursor
    assert quick.overflowed is False
    # nothing is lost: the buffer holds every frame, so a resume from a cursor the client DID
    # process (here the first frame, taken as already processed) is complete. The slow client's
    # own queue was cleared on overflow; the route test proves the end-to-end resume.
    processed_by_slow = frames[0]
    assert [f.data_json for f in hub.replay_after(processed_by_slow.cursor).missed] == [
        str(n) for n in range(1, 8)
    ]


async def test_r55_a_waiting_reader_is_woken_by_a_publish_and_by_an_overflow() -> None:
    hub = hub_of(subscriber=1)
    subscription = hub.subscribe()
    reader = asyncio.create_task(subscription.get())
    await asyncio.sleep(0)

    first = hub.publish("order.updated", A, "1")
    async with asyncio.timeout(2):
        got = await reader
    assert got is not None
    assert got.cursor == first.cursor

    hub.publish("order.updated", A, "2")
    hub.publish("order.updated", A, "3")  # capacity 1: this overflows
    async with asyncio.timeout(2):
        assert await subscription.get() is None
    assert subscription.overflowed is True


def test_r55_a_non_positive_subscriber_capacity_is_refused() -> None:
    with pytest.raises(ValueError, match="subscriber_capacity"):
        hub_of(subscriber=0)
