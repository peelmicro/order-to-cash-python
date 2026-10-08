"""The stock responder's task: headers (FS3), the bound (FS18), shutdown (FS26), the subscription
flush (FS27) and the loop's branches (F5, F9). No broker: a fake connection captures nats-py's
callbacks and a fake message records its reply (the real subscribe/respond path is driven against
real NATS in the integration tests). Every await is on an `asyncio.Event` or a bounded `wait_for`.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_contracts import from_wire_json
from otc_contracts.generated.asyncapi import Code, RpcError
from otc_fulfillment.application.messages import (
    ReplenishResult,
    ReserveOutcomeKind,
    ReserveResult,
    StockAvailability,
    StockPage,
)
from otc_fulfillment.application.ports.stock_store import StoreUnavailableError
from otc_fulfillment.presentation.stock_responder import ROUTES, StockResponder

NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)
CORRELATION = str(uuid.UUID(int=0xC0))
REQUEST = str(uuid.UUID(int=0xCA))
HEADERS = {"x-correlation-id": CORRELATION, "x-request-id": REQUEST}
CHECK = "fulfillment.stock.check"
RESERVE = "fulfillment.stock.reserve"
RELEASE = "fulfillment.stock.release"
LIST = "fulfillment.stock.list"
REPLENISH = "fulfillment.stock.replenish"


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeMessage:
    def __init__(
        self,
        data: bytes,
        *,
        reply: str = "_INBOX.x",
        fail_reply: bool = False,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.data = data
        self.reply = reply
        self.headers = headers
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
        self.calls: list[tuple[str, ...]] = []
        self.callbacks: dict[str, Callable[[Any], Awaitable[None]]] = {}
        self.subscriptions: list[FakeSubscription] = []

    async def subscribe(
        self, subject: str, queue: str, cb: Callable[[Any], Awaitable[None]]
    ) -> FakeSubscription:
        self.calls.append(("subscribe", subject, queue))
        self.callbacks[subject] = cb
        subscription = FakeSubscription()
        self.subscriptions.append(subscription)
        return subscription

    async def flush(self) -> None:
        self.calls.append(("flush",))


class GatedDispatcher:
    """`ask`/`send` block until the request's gate opens; the request is told apart by the
    company code (`check`), and every call records its command and scope."""

    def __init__(self) -> None:
        self.gates: dict[str, asyncio.Event] = {}
        self.started: dict[str, asyncio.Event] = {}
        self.commands: list[Any] = []
        self.scopes: list[Any] = []
        self.result: Any = None
        self.error: Exception | None = None

    def gate(self, name: str) -> asyncio.Event:
        return self.gates.setdefault(name, asyncio.Event())

    def entered(self, name: str) -> asyncio.Event:
        return self.started.setdefault(name, asyncio.Event())

    async def ask(self, query: Any, scope: Any) -> Any:
        self.commands.append(query)
        self.scopes.append(scope)
        name = getattr(query, "company_code", None) or "anon"
        self.entered(name).set()
        await self.gate(name).wait()
        if self.error is not None:
            raise self.error
        return self.result if self.result is not None else StockAvailability(True, ())

    async def send(self, command: Any, scope: Any) -> Any:
        self.commands.append(command)
        self.scopes.append(scope)
        if self.error is not None:
            raise self.error
        return self.result


def check_body(name: str) -> bytes:
    return json.dumps(
        {"companyCode": name, "lines": [{"productCode": "PRD-A1", "quantity": 1}]}
    ).encode()


RESERVE_BODY = json.dumps(
    {
        "orderReference": "ORD-000042",
        "retailerCode": "RET-9",
        "companyCode": "ACME-CO",
        "lines": [{"productCode": "PRD-A1", "units": 3}],
    }
).encode()
RELEASE_BODY = json.dumps({"orderReference": "ORD-000042", "reason": "order_cancelled"}).encode()
REPLENISH_BODY = json.dumps(
    {"companyCode": "ACME-CO", "lines": [{"productCode": "PRD-A1", "units": 3}]}
).encode()
LIST_BODY = b"{}"


class Rig:
    def __init__(self, bound: int = 8) -> None:
        self.connection = FakeConnection()
        self.dispatcher = GatedDispatcher()
        self.stop = asyncio.Event()
        self.scopes_made = 0

        def scope_factory() -> object:
            self.scopes_made += 1
            return object()

        self.responder = StockResponder(
            connection=self.connection,  # type: ignore[arg-type]
            dispatcher=self.dispatcher,  # type: ignore[arg-type]
            scope_factory=scope_factory,  # type: ignore[arg-type]
            clock=FakeClock(),
            max_concurrent_requests=bound,
        )
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self.responder.start()
        self.task = asyncio.create_task(self.responder.run(self.stop))

    async def deliver(self, subject: str, message: FakeMessage) -> None:
        await self.connection.callbacks[subject](message)

    async def finish(self) -> None:
        self.stop.set()
        assert self.task is not None
        await asyncio.wait_for(self.task, timeout=5)

    async def serve(self, subject: str, message: FakeMessage) -> RpcError | bytes:
        await self.start()
        await self.deliver(subject, message)
        for _ in range(200):
            if message.replies:
                break
            await asyncio.sleep(0.01)
        await self.finish()
        [reply] = message.replies
        return reply


@pytest.fixture
async def rig() -> Rig:
    return Rig()


def error_of(reply: RpcError | bytes) -> RpcError:
    assert isinstance(reply, bytes)
    return from_wire_json(RpcError, reply)


# ------------------------------------------------------------------------------------- FS3

HEADER_FAULTS: dict[str, dict[str, str] | None] = {
    "no headers at all": None,
    "empty headers": {},
    "correlation missing": {"x-request-id": REQUEST},
    "request missing": {"x-correlation-id": CORRELATION},
    "correlation malformed": {"x-correlation-id": "not-a-uuid", "x-request-id": REQUEST},
    "request malformed": {"x-correlation-id": CORRELATION, "x-request-id": "1234"},
    "correlation the nil id": {"x-correlation-id": str(uuid.UUID(int=0)), "x-request-id": REQUEST},
}


@pytest.mark.parametrize(
    ("subject", "body"),
    [(RESERVE, RESERVE_BODY), (RELEASE, RELEASE_BODY)],
    ids=["reserve", "release"],
)
@pytest.mark.parametrize("fault", sorted(HEADER_FAULTS))
async def test_fs3_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_or_malformed(  # noqa: E501
    rig: Rig, subject: str, body: bytes, fault: str
) -> None:
    reply = await rig.serve(subject, FakeMessage(body, headers=HEADER_FAULTS[fault]))

    assert error_of(reply).code is Code.validation_failed
    assert rig.dispatcher.commands == [], "nothing was dispatched"


async def test_fs3_check_list_and_replenish_succeed_with_no_header_at_all() -> None:
    # the control for the negative above: the same absence is fine where no header is required
    for subject, body, result in (
        (CHECK, check_body("ACME-CO"), StockAvailability(True, ())),
        (LIST, LIST_BODY, StockPage((), 1, 25, 0)),
        (REPLENISH, REPLENISH_BODY, ReplenishResult(())),
    ):
        rig = Rig()
        rig.dispatcher.result = result
        rig.dispatcher.gate("ACME-CO").set()
        rig.dispatcher.gate("anon").set()
        reply = await rig.serve(subject, FakeMessage(body, headers=None))
        assert isinstance(reply, bytes)
        assert "code" not in json.loads(reply), subject
        assert len(rig.dispatcher.commands) == 1, subject


async def test_fs3_the_command_carries_the_correlation_and_request_ids_from_the_headers() -> None:
    rig = Rig()
    rig.dispatcher.result = ReserveResult(
        ReserveOutcomeKind.ACCEPTED, "ORD-000042", reservations=()
    )

    await rig.serve(RESERVE, FakeMessage(RESERVE_BODY, headers=HEADERS))

    [command] = rig.dispatcher.commands
    assert str(command.correlation_id) == CORRELATION
    assert str(command.request_id) == REQUEST
    assert CORRELATION != REQUEST


# ------------------------------------------------------------------------------------- FS18


async def test_fs18_at_most_the_configured_number_of_requests_are_handled_at_once_and_the_next_starts_when_one_ends() -> (  # noqa: E501
    None
):
    rig = Rig(bound=2)
    await rig.start()
    for name in ("one", "two", "three"):
        await rig.deliver(CHECK, FakeMessage(check_body(name)))
    await asyncio.wait_for(rig.dispatcher.entered("one").wait(), timeout=5)
    await asyncio.wait_for(rig.dispatcher.entered("two").wait(), timeout=5)
    await asyncio.sleep(0.05)

    assert {n for n, e in rig.dispatcher.started.items() if e.is_set()} == {"one", "two"}, (
        "exactly two requests entered; the third waits for a slot"
    )
    rig.dispatcher.gate("one").set()
    await asyncio.wait_for(rig.dispatcher.entered("three").wait(), timeout=5)
    for name in ("two", "three"):
        rig.dispatcher.gate(name).set()
    await rig.finish()


async def test_fs18_each_request_gets_its_own_unit_of_work() -> None:
    rig = Rig(bound=4)
    await rig.start()
    for name in ("one", "two"):
        await rig.deliver(CHECK, FakeMessage(check_body(name)))
    await asyncio.wait_for(rig.dispatcher.entered("one").wait(), timeout=5)
    await asyncio.wait_for(rig.dispatcher.entered("two").wait(), timeout=5)

    first, second = rig.dispatcher.scopes
    assert first is not second, "two concurrent requests observe two distinct scopes"
    assert rig.scopes_made == 2
    for name in ("one", "two"):
        rig.dispatcher.gate(name).set()
    await rig.finish()


# ------------------------------------------------------------------------------------- FS26


async def test_fs26_shutdown_with_one_faulted_and_one_healthy_request_in_flight_completes_and_waits(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR)
    await rig.start()
    faulted = FakeMessage(check_body("faulted"), fail_reply=True)  # its REPLY will raise
    healthy = FakeMessage(check_body("healthy"))
    await rig.deliver(CHECK, faulted)
    await rig.deliver(CHECK, healthy)
    await asyncio.wait_for(rig.dispatcher.entered("faulted").wait(), timeout=5)
    await asyncio.wait_for(rig.dispatcher.entered("healthy").wait(), timeout=5)

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
    assert [s.unsubscribed for s in rig.connection.subscriptions] == [1] * len(ROUTES)


# ------------------------------------------------------------------------------------- FS27


async def test_fs27_start_flushes_after_the_last_subscription(rig: Rig) -> None:
    await rig.responder.start()

    subscribes = [c for c in rig.connection.calls if c[0] == "subscribe"]
    assert len(ROUTES) == 6, "five stock subjects and, from feature 18, despatch.create"
    assert len(subscribes) == len(ROUTES)
    assert {c[1] for c in subscribes} == set(ROUTES)
    assert {c[2] for c in subscribes} == {"otc-fulfillment"}, "every subscription is queue-grouped"
    assert rig.connection.calls[-1] == ("flush",)
    assert rig.connection.calls.index(("flush",)) == len(ROUTES), (
        "the flush follows the LAST subscribe"
    )


# ------------------------------------------------------------------------------------- F9


async def test_run_before_start_is_refused(rig: Rig) -> None:
    with pytest.raises(RuntimeError, match="before start"):
        await rig.responder.run(rig.stop)


async def test_a_request_without_a_reply_subject_is_dropped_and_the_loop_survives(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    await rig.start()
    caplog.set_level(logging.WARNING)
    await rig.deliver(CHECK, FakeMessage(check_body("nobody"), reply=""))
    healthy = FakeMessage(check_body("b"))
    await rig.deliver(CHECK, healthy)
    rig.dispatcher.gate("b").set()
    await asyncio.wait_for(rig.dispatcher.entered("b").wait(), timeout=5)
    await rig.finish()

    assert len(healthy.replies) == 1
    assert "no reply subject" in caplog.text
    assert not rig.dispatcher.started.get("nobody", asyncio.Event()).is_set()


async def test_a_request_that_arrives_while_the_subscriptions_are_closing_is_still_served(
    rig: Rig,
) -> None:
    late = FakeMessage(check_body("late"))

    async def arrives() -> None:
        await rig.deliver(CHECK, late)

    await rig.start()
    rig.connection.subscriptions[0].while_closing = arrives
    rig.dispatcher.gate("late").set()
    await rig.finish()

    assert len(late.replies) == 1, "a delivered request is answered, never dropped by shutdown"


async def test_cancelling_the_task_propagates_and_cancels_its_requests(rig: Rig) -> None:
    await rig.start()
    pending = FakeMessage(check_body("pending"))
    await rig.deliver(CHECK, pending)
    await asyncio.wait_for(rig.dispatcher.entered("pending").wait(), timeout=5)
    assert rig.task is not None

    rig.task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await rig.task
    assert pending.replies == [], "a cancelled request is not answered as if it had finished"


# ------------------------------------------------------------------------------------- F5


async def test_requests_are_served_concurrently_a_slow_one_does_not_hold_the_next(rig: Rig) -> None:
    await rig.start()
    slow, quick = FakeMessage(check_body("slow")), FakeMessage(check_body("quick"))
    await rig.deliver(CHECK, slow)
    await rig.deliver(CHECK, quick)
    rig.dispatcher.gate("quick").set()
    for _ in range(200):
        if quick.replies:
            break
        await asyncio.sleep(0.01)

    assert len(quick.replies) == 1
    assert slow.replies == []
    rig.dispatcher.gate("slow").set()
    await rig.finish()
    assert len(slow.replies) == 1


async def test_an_empty_body_is_answered_validation_failed(rig: Rig) -> None:
    reply = await rig.serve(CHECK, FakeMessage(b""))

    assert error_of(reply).code is Code.validation_failed
    assert rig.dispatcher.commands == []


async def test_a_mapped_error_is_answered_with_its_code_and_an_unmapped_one_as_internal_error(
    rig: Rig,
) -> None:
    rig.dispatcher.error = StoreUnavailableError("40P01")
    unavailable = error_of(await rig.serve(REPLENISH, FakeMessage(REPLENISH_BODY)))
    assert unavailable.code is Code.unavailable

    other = Rig()
    other.dispatcher.error = RuntimeError("secret sql text")
    internal = error_of(await other.serve(REPLENISH, FakeMessage(REPLENISH_BODY)))
    assert internal.code is Code.internal_error
    assert "secret" not in internal.message


async def test_the_rpc_error_carries_the_correlation_id_of_the_request_when_present() -> None:
    rig = Rig()
    rig.dispatcher.error = StoreUnavailableError("40P01")

    error = error_of(await rig.serve(RESERVE, FakeMessage(RESERVE_BODY, headers=HEADERS)))

    assert str(error.correlation_id) == CORRELATION
