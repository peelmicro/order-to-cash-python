"""The `orders.create` responder's task: delivery, concurrency and SHUTDOWN (#8 id 50).

No broker: a fake connection captures nats-py's callback and a fake message records its reply (the
real subscribe/unsubscribe/respond path is driven against real NATS in the integration tests).
Every await below is on an `asyncio.Event` or a bounded `wait_for`.

#8 id 50: a faulted in-flight request must not propagate out of shutdown, and the drain still waits
for every in-flight request.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_orders.presentation.orders_create_responder import OrdersCreateResponder

NOW = datetime(2026, 10, 6, 9, 0, 0, tzinfo=UTC)


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeMessage:
    def __init__(self, data: bytes, *, reply: str = "_INBOX.x", fail_reply: bool = False) -> None:
        self.data = data
        self.reply = reply
        self._fail_reply = fail_reply
        self.replies: list[bytes] = []

    async def respond(self, data: bytes) -> None:
        if self._fail_reply:
            raise ConnectionError("the reply could not be published")
        self.replies.append(data)


class FakeSubscription:
    def __init__(self) -> None:
        self.unsubscribed = 0
        self.while_closing: Callable[[], Awaitable[None]] | None = None

    async def unsubscribe(self) -> None:
        self.unsubscribed += 1
        if self.while_closing is not None:
            await self.while_closing()  # a message the server had already sent


class FakeConnection:
    def __init__(self) -> None:
        self.callback: Callable[[Any], Awaitable[None]] | None = None
        self.subscription = FakeSubscription()

    async def subscribe(
        self, subject: str, queue: str, cb: Callable[[Any], Awaitable[None]]
    ) -> FakeSubscription:
        assert (subject, queue) == ("orders.create", "otc-orders")
        self.callback = cb
        return self.subscription


class GatedDispatcher:
    """`send` blocks until its request's gate opens; the command is the raw request body."""

    def __init__(self) -> None:
        self.gates: dict[str, asyncio.Event] = {}
        self.started: dict[str, asyncio.Event] = {}

    def gate(self, name: str) -> asyncio.Event:
        return self.gates.setdefault(name, asyncio.Event())

    def entered(self, name: str) -> asyncio.Event:
        return self.started.setdefault(name, asyncio.Event())

    async def send(self, command: Any, scope: Any) -> Any:
        name = command.notes
        self.entered(name).set()
        await self.gate(name).wait()
        raise RuntimeError(f"{name} refused")  # every request ends as an error reply: simplest


def request(name: str) -> bytes:
    return (
        b'{"retailerCode":"R","companyCode":"C","currency":"EUR",'
        b'"lines":[{"productCode":"P","quantity":1}],"notes":"' + name.encode() + b'"}'
    )


class Rig:
    def __init__(self) -> None:
        self.connection = FakeConnection()
        self.dispatcher = GatedDispatcher()
        self.stop = asyncio.Event()
        self.responder = OrdersCreateResponder(
            connection=self.connection,  # type: ignore[arg-type]
            dispatcher=self.dispatcher,  # type: ignore[arg-type]
            scope_factory=lambda: None,  # type: ignore[arg-type, return-value]
            clock=FakeClock(),
        )
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self.responder.start()
        self.task = asyncio.create_task(self.responder.run(self.stop))

    async def deliver(self, message: FakeMessage) -> None:
        assert self.connection.callback is not None
        await self.connection.callback(message)


@pytest.fixture
async def rig() -> Rig:
    return Rig()


async def test_run_before_start_is_refused(rig: Rig) -> None:
    with pytest.raises(RuntimeError, match="before start"):
        await rig.responder.run(rig.stop)


async def test_a_request_without_a_reply_subject_is_dropped_and_the_loop_survives(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    await rig.start()
    caplog.set_level(logging.WARNING)
    await rig.deliver(FakeMessage(request("nobody"), reply=""))
    healthy = FakeMessage(request("b"))
    await rig.deliver(healthy)
    rig.dispatcher.gate("b").set()
    await asyncio.wait_for(rig.dispatcher.entered("b").wait(), timeout=5)
    rig.stop.set()
    assert rig.task is not None
    await asyncio.wait_for(rig.task, timeout=5)

    assert len(healthy.replies) == 1
    assert "no reply subject" in caplog.text
    assert not rig.dispatcher.started.get("nobody", asyncio.Event()).is_set()


async def test_shutdown_with_one_faulted_and_one_healthy_request_in_flight_completes_and_waits(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR)
    await rig.start()
    faulted = FakeMessage(request("faulted"), fail_reply=True)  # its REPLY will raise
    healthy = FakeMessage(request("healthy"))
    await rig.deliver(faulted)
    await rig.deliver(healthy)
    await asyncio.wait_for(rig.dispatcher.entered("faulted").wait(), timeout=5)
    await asyncio.wait_for(rig.dispatcher.entered("healthy").wait(), timeout=5)

    # both are mid-request when shutdown begins
    rig.stop.set()
    assert rig.task is not None
    await asyncio.sleep(0.05)
    assert not rig.task.done(), "the drain must wait for the requests still running"
    rig.dispatcher.gate("faulted").set()  # its reply raises ConnectionError
    await asyncio.sleep(0.05)
    assert not rig.task.done(), "one request finishing (badly) must not end the drain early"
    rig.dispatcher.gate("healthy").set()
    await asyncio.wait_for(rig.task, timeout=5)  # returns normally: the fault is not re-raised

    assert rig.task.exception() is None
    assert len(healthy.replies) == 1, "the healthy request was answered during the drain"
    assert faulted.replies == []
    assert "could not be answered" in caplog.text, "the fault is logged, not lost"
    assert rig.connection.subscription.unsubscribed == 1


async def test_a_request_that_arrives_while_the_subscription_is_closing_is_still_served(
    rig: Rig,
) -> None:
    late = FakeMessage(request("late"))

    async def arrives() -> None:
        await rig.deliver(late)

    await rig.start()
    rig.connection.subscription.while_closing = arrives
    rig.dispatcher.gate("late").set()
    rig.stop.set()
    assert rig.task is not None
    await asyncio.wait_for(rig.task, timeout=5)

    assert len(late.replies) == 1, "a delivered request is answered, never dropped by shutdown"


async def test_requests_are_served_concurrently_a_slow_one_does_not_hold_the_next(rig: Rig) -> None:
    await rig.start()
    slow, quick = FakeMessage(request("slow")), FakeMessage(request("quick"))
    await rig.deliver(slow)
    await rig.deliver(quick)
    rig.dispatcher.gate("quick").set()
    await asyncio.wait_for(rig.dispatcher.entered("quick").wait(), timeout=5)
    for _ in range(100):
        if quick.replies:
            break
        await asyncio.sleep(0.01)

    assert len(quick.replies) == 1
    assert slow.replies == []
    rig.dispatcher.gate("slow").set()
    rig.stop.set()
    assert rig.task is not None
    await asyncio.wait_for(rig.task, timeout=5)
    assert len(slow.replies) == 1


async def test_cancelling_the_task_propagates_and_cancels_its_requests(rig: Rig) -> None:
    await rig.start()
    pending = FakeMessage(request("pending"))
    await rig.deliver(pending)
    await asyncio.wait_for(rig.dispatcher.entered("pending").wait(), timeout=5)
    assert rig.task is not None

    rig.task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await rig.task
    assert pending.replies == [], "a cancelled request is not answered as if it had finished"
