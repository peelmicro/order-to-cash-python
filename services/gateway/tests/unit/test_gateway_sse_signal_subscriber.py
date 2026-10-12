"""The Gateway's subscriber of the Projector's update signal (R55, subscriber leg): the parsing, the
relay into the hub, and the task's lifecycle, over a fake connection. The real broker is in
`tests/integration/test_gateway_sse_signals.py`.

Ports of #8 `NatsStreamSignalSubscriberTests.cs` (subject parsing) and the malformed-frame cases of
#7 `nats-stream-signal.adapter.spec.ts`.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest

from otc_gateway.application.stream.hub import StreamHub
from otc_gateway.infrastructure.stream_signal_subscriber import (
    ORDER_UPDATED_EVENT,
    ORDER_UPDATED_SUBJECT,
    TIMELINE_APPENDED_EVENT,
    TIMELINE_APPENDED_SUBJECT,
    order_id_of,
    relay,
    signal_text,
    start_stream_subscriber,
)

ORDER = UUID("0a0b0c0d-2222-4000-8000-0000000000bb")
OTHER = UUID("0a0b0c0d-3333-4000-8000-0000000000cc")


def hub() -> StreamHub:
    return StreamHub(lambda: 1, replay_capacity=50, subscriber_capacity=50)


# ----------------------------------------------------------------------------- the parsing


def test_r55_the_order_id_is_the_trailing_token_of_the_event_types_own_subject() -> None:
    assert order_id_of(ORDER_UPDATED_EVENT, f"readmodel.order.updated.{ORDER}") == ORDER
    assert order_id_of(TIMELINE_APPENDED_EVENT, f"readmodel.timeline.appended.{OTHER}") == OTHER


@pytest.mark.parametrize(
    ("event", "subject"),
    [
        (ORDER_UPDATED_EVENT, f"readmodel.timeline.appended.{ORDER}"),  # the sibling's subject
        (TIMELINE_APPENDED_EVENT, f"readmodel.order.updated.{ORDER}"),  # and the other way
        (ORDER_UPDATED_EVENT, "readmodel.order.updated."),  # no token
        (ORDER_UPDATED_EVENT, "readmodel.order.updated.not-a-uuid"),
        (ORDER_UPDATED_EVENT, f"readmodel.order.updated.{ORDER}.extra"),
    ],
)
def test_r55_a_subject_that_does_not_name_an_order_of_that_event_is_refused(
    event: str, subject: str
) -> None:
    with pytest.raises(ValueError, match=r"subject|UUID|uuid|badly formed"):
        order_id_of(event, subject)


def test_r55_the_payload_is_forwarded_as_the_exact_text_it_arrived_as() -> None:
    text = '{"summary":"Crédito rechazado - café","orderId":"x"}'

    assert signal_text(text.encode("utf-8")) == text  # non-ASCII raw, not re-encoded


@pytest.mark.parametrize(
    "payload",
    [b"__barrier__", b"", b"\xff\xfe", b'{"a":1}\n{"b":2}', b'{\n"a": 1\n}', b'{"a":1}\r'],
)
def test_r55_a_payload_that_is_not_one_line_of_json_is_refused(payload: bytes) -> None:
    """A newline inside `data:` would end the SSE frame early and let the rest be read as fields."""
    with pytest.raises(ValueError, match=r"line|JSON|Expecting|decode|codec"):
        signal_text(payload)


def test_r55_a_malformed_signal_is_skipped_and_the_next_one_still_reaches_the_hub() -> None:
    target = hub()

    assert relay(target, ORDER_UPDATED_EVENT, f"readmodel.order.updated.{ORDER}", b"nope") is False
    assert relay(target, ORDER_UPDATED_EVENT, "readmodel.order.updated.zzz", b"{}") is False
    assert relay(target, ORDER_UPDATED_EVENT, f"readmodel.order.updated.{ORDER}", b'{"ok":1}')

    assert len(target._buffer) == 1  # exactly the one well-formed signal was buffered


# ------------------------------------------------------------------------------ the lifecycle


@dataclass
class FakeSubscription:
    queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)

    @property
    def messages(self) -> AsyncIterator[Any]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        while True:
            item = await self.queue.get()
            if item is None:
                return  # the iterator ends: the subscription died
            yield item


@dataclass
class Message:
    subject: str
    data: bytes


@dataclass
class FakeConnection:
    subscriptions: dict[str, FakeSubscription] = field(default_factory=dict)
    flushed: int = 0
    hang_on_subscribe: bool = False

    async def subscribe(self, subject: str) -> FakeSubscription:
        if self.hang_on_subscribe:
            await asyncio.Event().wait()
        self.subscriptions[subject] = FakeSubscription()
        return self.subscriptions[subject]

    async def flush(self) -> None:
        self.flushed += 1


async def test_r55_both_subjects_are_subscribed_flushed_and_each_feeds_its_own_event_type() -> None:
    connection = FakeConnection()
    target = hub()
    subscription = target.subscribe()

    handle = await start_stream_subscriber(connection, target, subscribe_seconds=5)  # type: ignore[arg-type]
    try:
        assert set(connection.subscriptions) == {ORDER_UPDATED_SUBJECT, TIMELINE_APPENDED_SUBJECT}
        assert connection.flushed == 1, (
            "the server was not told the subscriptions before boot ended"
        )
        connection.subscriptions[TIMELINE_APPENDED_SUBJECT].queue.put_nowait(
            Message(f"readmodel.timeline.appended.{ORDER}", b'{"t":1}')
        )
        connection.subscriptions[ORDER_UPDATED_SUBJECT].queue.put_nowait(
            Message(f"readmodel.order.updated.{OTHER}", b'{"o":1}')
        )
        frames = []
        try:
            async with asyncio.timeout(5):
                frames.append(await subscription.get())
                frames.append(await subscription.get())
        except TimeoutError:
            pytest.fail(
                f"each subject feeds its own event type: {len(frames)} of 2 signals reached the hub"
            )
    finally:
        await handle.stop()

    by_event = {f.event_type: f for f in frames if f is not None}
    assert by_event[TIMELINE_APPENDED_EVENT].order_id == ORDER
    assert by_event[TIMELINE_APPENDED_EVENT].data_json == '{"t":1}'
    assert by_event[ORDER_UPDATED_EVENT].order_id == OTHER
    assert by_event[ORDER_UPDATED_EVENT].data_json == '{"o":1}'


async def test_r55_a_dead_subscription_takes_readiness_down_and_the_task_ends() -> None:
    connection = FakeConnection()
    handle = await start_stream_subscriber(connection, hub(), subscribe_seconds=5)  # type: ignore[arg-type]
    try:
        assert handle.unready_reason() is None

        connection.subscriptions[ORDER_UPDATED_SUBJECT].queue.put_nowait(None)  # its iterator ends
        try:
            async with asyncio.timeout(5):
                while handle.unready_reason() is None:  # noqa: ASYNC110 - paced poll of a task state
                    await asyncio.sleep(0.01)
        except TimeoutError:
            pytest.fail("a subscription that ended did not take the subscriber's readiness down")
    finally:
        await handle.stop()

    assert "died" in (handle.unready_reason() or "")


async def test_r55_stop_cancels_and_awaits_the_task() -> None:
    connection = FakeConnection()
    handle = await start_stream_subscriber(connection, hub(), subscribe_seconds=5)  # type: ignore[arg-type]
    task = handle._task

    await handle.stop()

    assert task.done()
    assert task.cancelled()
    assert "cancelled" in (handle.unready_reason() or "")


async def test_r55_a_subscribe_that_never_completes_fails_the_boot_and_leaves_no_task() -> None:
    before = {t for t in asyncio.all_tasks() if t is not asyncio.current_task()}
    connection = FakeConnection(hang_on_subscribe=True)

    with pytest.raises(TimeoutError):
        await start_stream_subscriber(connection, hub(), subscribe_seconds=0.2)  # type: ignore[arg-type]

    leftover = {t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()}
    assert leftover == before, "the failed start left a task behind"


async def test_r55_a_subscriber_that_fails_while_subscribing_raises_its_own_error() -> None:
    class Broken(FakeConnection):
        async def subscribe(self, subject: str) -> FakeSubscription:
            raise ConnectionError("no route to the broker")

    with pytest.raises(ConnectionError, match="no route"):
        await start_stream_subscriber(Broken(), hub(), subscribe_seconds=5)  # type: ignore[arg-type]
