"""The credit responder's task: headers (BC1), the bound and the scope per request (BC21),
shutdown (BC22), the subscription flush and the loop's branches (tasks E5, E7, E8). No broker: a
fake connection captures nats-py's callbacks and a fake message records its reply (the real
subscribe/respond path is driven against real NATS in the integration tests). Every await is on an
`asyncio.Event` or a bounded `wait_for`.

Loop scope: function (pytest-asyncio default); nothing outlives the test.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_billing.application.messages import (
    CreditPage,
    HoldOutcomeKind,
    HoldResult,
    InvoiceIssueResult,
    InvoicePage,
    InvoiceSummary,
)
from otc_billing.application.ports.credit_store import StoreUnavailableError
from otc_billing.domain.invoice_state import InvoiceStatus
from otc_billing.presentation.credit_responder import ROUTES, CreditResponder
from otc_contracts import from_wire_json
from otc_contracts.generated.asyncapi import Code, RpcError
from otc_shared_kernel import UniqueId

NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)
CORRELATION = str(uuid.UUID(int=0xC0))
REQUEST = str(uuid.UUID(int=0xCA))
HEADERS = {"x-correlation-id": CORRELATION, "x-request-id": REQUEST}
HOLD = "billing.credit.hold"
RELEASE = "billing.credit.release"
LIST = "billing.credit.list"
INVOICE_ISSUE = "billing.invoice.issue"
INVOICE_LIST = "billing.invoice.list"


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
    """`ask` blocks until the request's gate opens; the request is told apart by the retailer code
    of the list query, and every call records its message and scope."""

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
        name = getattr(query, "retailer_code", None) or "anon"
        self.entered(name).set()
        await self.gate(name).wait()
        if self.error is not None:
            raise self.error
        return self.result if self.result is not None else CreditPage((), 1, 25, 0)

    async def send(self, command: Any, scope: Any) -> Any:
        self.commands.append(command)
        self.scopes.append(scope)
        if self.error is not None:
            raise self.error
        return self.result


def list_body(name: str) -> bytes:
    return json.dumps({"retailerCode": name}).encode()


HOLD_BODY = json.dumps(
    {
        "orderReference": "ORD-000101",
        "retailerCode": "RETAIL-77",
        "companyCode": "SUPPLY-CO",
        "amount": {"amount": 250, "currency": "EUR"},
    }
).encode()
RELEASE_BODY = json.dumps(
    {"orderReference": "ORD-000101", "retailerCode": "RETAIL-77", "companyCode": "SUPPLY-CO"}
).encode()
LIST_BODY = b"{}"
ISSUE_BODY = json.dumps(
    {
        "orderReference": "ORD-000101",
        "retailerCode": "RETAIL-77",
        "companyCode": "SUPPLY-CO",
        "currency": "EUR",
        "lines": [
            {"productCode": "PRD-ZZ", "units": 3, "unitPrice": 1999},
            {"productCode": "PRD-AA", "units": 2, "unitPrice": 1234},
        ],
        "discount": 350,
    }
).encode()


class Rig:
    def __init__(self, bound: int = 8) -> None:
        self.connection = FakeConnection()
        self.dispatcher = GatedDispatcher()
        self.stop = asyncio.Event()
        self.scopes_made = 0

        def scope_factory() -> object:
            self.scopes_made += 1
            return object()

        self.responder = CreditResponder(
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

    async def serve(self, subject: str, message: FakeMessage) -> bytes:
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


def error_of(reply: bytes) -> RpcError:
    return from_wire_json(RpcError, reply)


# ------------------------------------------------------------------------------------- BC1

# each header on its own, missing and malformed (#8 review D4: the malformed x-request-id case)
HEADER_FAULTS: dict[str, dict[str, str] | None] = {
    "correlation missing": {"x-request-id": REQUEST},
    "correlation malformed": {"x-correlation-id": "not-a-uuid", "x-request-id": REQUEST},
    "request missing": {"x-correlation-id": CORRELATION},
    "request malformed": {"x-correlation-id": CORRELATION, "x-request-id": "1234"},
}


@pytest.mark.parametrize(
    ("subject", "body"), [(HOLD, HOLD_BODY), (RELEASE, RELEASE_BODY)], ids=["hold", "release"]
)
@pytest.mark.parametrize("fault", sorted(HEADER_FAULTS))
async def test_bc1_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_or_malformed(  # noqa: E501
    rig: Rig, subject: str, body: bytes, fault: str
) -> None:
    reply = await rig.serve(subject, FakeMessage(body, headers=HEADER_FAULTS[fault]))

    assert error_of(reply).code is Code.validation_failed, f"{subject}: {fault}"
    assert rig.dispatcher.commands == [], f"{subject}: {fault} was dispatched"


@pytest.mark.parametrize(
    "headers",
    [None, {}, {"x-correlation-id": str(uuid.UUID(int=0)), "x-request-id": REQUEST}],
    ids=["no headers", "empty headers", "the nil correlation id"],
)
async def test_bc1_hold_and_release_refuse_the_remaining_header_faults(
    headers: dict[str, str] | None,
) -> None:
    for subject, body in ((HOLD, HOLD_BODY), (RELEASE, RELEASE_BODY)):
        rig = Rig()
        reply = await rig.serve(subject, FakeMessage(body, headers=headers))
        assert error_of(reply).code is Code.validation_failed
        assert rig.dispatcher.commands == []


async def test_bc1_list_succeeds_with_no_header_at_all() -> None:
    # the control for the negatives above: the same absence is fine where no header is required
    rig = Rig()
    rig.dispatcher.result = CreditPage((), 1, 25, 0)
    rig.dispatcher.gate("anon").set()
    reply = await rig.serve(LIST, FakeMessage(LIST_BODY, headers=None))
    assert "code" not in json.loads(reply)
    assert len(rig.dispatcher.commands) == 1


async def test_bc1_the_command_carries_the_correlation_and_request_ids_from_the_headers() -> None:
    rig = Rig()
    rig.dispatcher.result = HoldResult(
        HoldOutcomeKind.APPROVED, "ORD-000101", "CR-000321", "EUR", 250, 450, None
    )
    await rig.serve(HOLD, FakeMessage(HOLD_BODY, headers=HEADERS))
    [command] = rig.dispatcher.commands
    assert str(command.correlation_id) == CORRELATION
    assert str(command.request_id) == REQUEST
    assert CORRELATION != REQUEST


async def test_the_rpc_error_carries_the_correlation_id_of_the_request_when_present() -> None:
    rig = Rig()
    rig.dispatcher.error = StoreUnavailableError("40P01")
    error = error_of(await rig.serve(HOLD, FakeMessage(HOLD_BODY, headers=HEADERS)))
    assert error.code is Code.unavailable
    assert str(error.correlation_id) == CORRELATION


# ------------------------------------------------------------------------------------- BC21


async def test_bc21_at_most_the_configured_number_of_requests_are_handled_at_once_and_the_next_starts_when_one_ends() -> (  # noqa: E501
    None
):
    rig = Rig(bound=2)
    await rig.start()
    for name in ("one", "two", "three"):
        await rig.deliver(LIST, FakeMessage(list_body(name)))
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


async def test_bc21_builds_a_distinct_scope_per_request() -> None:
    rig = Rig(bound=4)
    await rig.start()
    for name in ("one", "two"):
        await rig.deliver(LIST, FakeMessage(list_body(name)))
    await asyncio.wait_for(rig.dispatcher.entered("one").wait(), timeout=5)
    await asyncio.wait_for(rig.dispatcher.entered("two").wait(), timeout=5)

    first, second = rig.dispatcher.scopes
    assert first is not second, "BC21: two concurrent requests observe the same scope"
    assert rig.scopes_made == 2
    for name in ("one", "two"):
        rig.dispatcher.gate(name).set()
    await rig.finish()


async def test_the_bound_is_acquired_before_the_unit_of_work_opens() -> None:
    rig = Rig(bound=1)
    await rig.start()
    await rig.deliver(LIST, FakeMessage(list_body("holder")))
    await asyncio.wait_for(rig.dispatcher.entered("holder").wait(), timeout=5)
    await rig.deliver(LIST, FakeMessage(list_body("waiter")))
    await asyncio.sleep(0.05)

    assert rig.scopes_made == 1, (
        f"BC21: {rig.scopes_made} scopes exist while one request holds the only slot: a waiting "
        "request opened its unit of work before it was admitted"
    )
    rig.dispatcher.gate("holder").set()
    await asyncio.wait_for(rig.dispatcher.entered("waiter").wait(), timeout=5)
    assert rig.scopes_made == 2
    rig.dispatcher.gate("waiter").set()
    await rig.finish()


# ------------------------------------------------------------------------------------- BC22


async def test_bc22_shutdown_waits_for_every_in_flight_request_when_one_faults_and_one_succeeds(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR)
    await rig.start()
    faulted = FakeMessage(list_body("faulted"), fail_reply=True)  # its REPLY will raise
    healthy = FakeMessage(list_body("healthy"))
    await rig.deliver(LIST, faulted)
    await rig.deliver(LIST, healthy)
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
    assert len(healthy.replies) == 1, (
        "the healthy request's reply was not sent before stop returned"
    )
    assert faulted.replies == []
    assert "could not be answered" in caplog.text, "the fault is logged, not lost"
    assert [s.unsubscribed for s in rig.connection.subscriptions] == [1] * len(ROUTES)


async def test_bc22_cancelling_the_task_propagates_and_cancels_its_requests(rig: Rig) -> None:
    await rig.start()
    pending = FakeMessage(list_body("pending"))
    await rig.deliver(LIST, pending)
    await asyncio.wait_for(rig.dispatcher.entered("pending").wait(), timeout=5)
    assert rig.task is not None

    rig.task.cancel()

    try:
        await rig.task
    except asyncio.CancelledError:
        pass
    else:
        pytest.fail("BC22: cancelling `run` did not re-raise the cancellation (it was swallowed)")
    assert pending.replies == [], "a cancelled request is not answered as if it had finished"


# ------------------------------------------------------------------------- the subscription flush


async def test_start_flushes_after_the_last_subscription(rig: Rig) -> None:
    await rig.responder.start()

    subscribes = [c for c in rig.connection.calls if c[0] == "subscribe"]
    assert len(ROUTES) == 6
    assert len(subscribes) == len(ROUTES)
    assert {c[1] for c in subscribes} == set(ROUTES)
    assert {c[2] for c in subscribes} == {"otc-billing"}, "every subscription is queue-grouped"
    assert rig.connection.calls[-1] == ("flush",)
    assert rig.connection.calls.index(("flush",)) == len(ROUTES), (
        "the flush follows the LAST subscribe"
    )


# ----------------------------------------------------------------------------------- the loop


async def test_run_before_start_is_refused(rig: Rig) -> None:
    with pytest.raises(RuntimeError, match="before start"):
        await rig.responder.run(rig.stop)


async def test_a_request_without_a_reply_subject_is_dropped_and_the_loop_survives(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    await rig.start()
    caplog.set_level(logging.WARNING)
    await rig.deliver(LIST, FakeMessage(list_body("nobody"), reply=""))
    healthy = FakeMessage(list_body("b"))
    await rig.deliver(LIST, healthy)
    rig.dispatcher.gate("b").set()
    await asyncio.wait_for(rig.dispatcher.entered("b").wait(), timeout=5)
    await rig.finish()

    assert len(healthy.replies) == 1
    assert "no reply subject" in caplog.text
    assert not rig.dispatcher.started.get("nobody", asyncio.Event()).is_set()


async def test_a_request_that_arrives_while_the_subscriptions_are_closing_is_still_served(
    rig: Rig,
) -> None:
    late = FakeMessage(list_body("late"))

    async def arrives() -> None:
        await rig.deliver(LIST, late)

    await rig.start()
    rig.connection.subscriptions[0].while_closing = arrives
    rig.dispatcher.gate("late").set()
    await rig.finish()

    assert len(late.replies) == 1, "a delivered request is answered, never dropped by shutdown"


async def test_requests_are_served_concurrently_a_slow_one_does_not_hold_the_next(rig: Rig) -> None:
    await rig.start()
    slow, quick = FakeMessage(list_body("slow")), FakeMessage(list_body("quick"))
    await rig.deliver(LIST, slow)
    await rig.deliver(LIST, quick)
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
    reply = await rig.serve(LIST, FakeMessage(b""))
    assert error_of(reply).code is Code.validation_failed
    assert rig.dispatcher.commands == []


async def test_a_mapped_error_is_answered_with_its_code_and_an_unmapped_one_as_internal_error(
    rig: Rig,
) -> None:
    rig.dispatcher.error = StoreUnavailableError("40P01")
    unavailable = error_of(await rig.serve(HOLD, FakeMessage(HOLD_BODY, headers=HEADERS)))
    assert unavailable.code is Code.unavailable

    other = Rig()
    other.dispatcher.error = RuntimeError("secret sql text")
    internal = error_of(await other.serve(HOLD, FakeMessage(HOLD_BODY, headers=HEADERS)))
    assert internal.code is Code.internal_error
    assert "secret" not in internal.message


# ------------------------------------------------------------- feature 21 (E5): the invoice routes


@pytest.mark.parametrize("fault", sorted(HEADER_FAULTS))
async def test_bi2_billing_invoice_issue_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_or_malformed(  # noqa: E501
    rig: Rig, fault: str
) -> None:
    reply = await rig.serve(INVOICE_ISSUE, FakeMessage(ISSUE_BODY, headers=HEADER_FAULTS[fault]))

    assert error_of(reply).code is Code.validation_failed, f"{INVOICE_ISSUE}: {fault}"
    assert rig.dispatcher.commands == [], f"{INVOICE_ISSUE}: {fault} was dispatched"


async def test_bi2_billing_invoice_issue_dispatches_a_command_carrying_the_header_ids() -> None:
    rig = Rig()
    rig.dispatcher.result = InvoiceIssueResult(
        True,
        InvoiceSummary(
            invoice_id=UniqueId(uuid.UUID(int=0x5001)),
            invoice_reference="INV-000042",
            invoice_date=NOW,
            order_reference="ORD-000101",
            currency="EUR",
            total_amount=8115,
            status=InvoiceStatus.ISSUED,
        ),
    )

    reply = await rig.serve(INVOICE_ISSUE, FakeMessage(ISSUE_BODY, headers=HEADERS))

    assert json.loads(reply)["created"] is True
    [command] = rig.dispatcher.commands
    assert str(command.correlation_id) == CORRELATION
    assert str(command.request_id) == REQUEST
    assert CORRELATION != REQUEST
    assert command.discount == 350


async def test_bi31_billing_invoice_list_succeeds_with_no_header_at_all() -> None:
    rig = Rig()
    rig.dispatcher.result = InvoicePage((), 1, 25, 0)
    rig.dispatcher.gate("anon").set()
    reply = await rig.serve(INVOICE_LIST, FakeMessage(LIST_BODY, headers=None))
    assert "code" not in json.loads(reply)
    assert json.loads(reply)["page"]["total"] == 0
    assert len(rig.dispatcher.commands) == 1


# ------------------------------------------------ feature 22: the payment route (R47 - R49)

PAYMENT_REGISTER = "billing.payment.register"
PAYMENT_BODY = json.dumps(
    {
        "invoiceReference": "INV-000042",
        "paymentReference": "BANK-REF-7731",
        "amount": {"amount": 8115, "currency": "EUR"},
        "valueDate": "2026-10-09T00:00:00.000Z",
        "source": "robot",
    }
).encode()


@pytest.mark.parametrize("fault", sorted(HEADER_FAULTS))
async def test_r47_billing_payment_register_replies_validation_failed_and_dispatches_nothing_when_a_header_is_missing_or_malformed(  # noqa: E501
    rig: Rig, fault: str
) -> None:
    reply = await rig.serve(
        PAYMENT_REGISTER, FakeMessage(PAYMENT_BODY, headers=HEADER_FAULTS[fault])
    )

    assert error_of(reply).code is Code.validation_failed, f"{PAYMENT_REGISTER}: {fault}"
    assert rig.dispatcher.commands == [], f"{PAYMENT_REGISTER}: {fault} was dispatched"


async def test_r47_billing_payment_register_dispatches_a_command_carrying_the_header_ids() -> None:
    from otc_billing.application.messages import PaymentOutcome, PaymentRegisterResult

    rig = Rig()
    rig.dispatcher.result = PaymentRegisterResult(
        outcome=PaymentOutcome.ACCEPTED,
        payment_reference="BANK-REF-7731",
        invoice_reference="INV-000042",
        order_reference="ORD-000101",
        invoice_status=InvoiceStatus.PAID,
        paid_at=NOW,
    )

    reply = await rig.serve(PAYMENT_REGISTER, FakeMessage(PAYMENT_BODY, headers=HEADERS))

    replied = json.loads(reply)
    assert replied.get("outcome") == "accepted", f"R47: the payment route answered {replied}"
    [command] = rig.dispatcher.commands
    assert str(command.correlation_id) == CORRELATION
    assert str(command.request_id) == REQUEST
    assert CORRELATION != REQUEST
    assert command.payment_reference == "BANK-REF-7731"
    assert command.amount.amount == 8115


async def test_r49_an_invalid_payment_request_is_validation_failed_and_dispatches_nothing() -> None:
    reply = await Rig().serve(
        PAYMENT_REGISTER, FakeMessage(b'{"paymentReference":"X"}', headers=HEADERS)
    )

    assert error_of(reply).code is Code.validation_failed
