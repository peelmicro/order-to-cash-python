"""The Billing NATS responder: ONE asyncio task for six subscriptions (`billing.credit.hold`,
`.release`, `.list`, `billing.invoice.issue` and `.list`, and `billing.payment.register`; `BI31`).

Fulfillment's `StockResponder` with Billing's route table (`ROUTES`: one entry per subject, so
feature 22 adds its own as an entry; feature 21 added the two invoice entries WITHOUT renaming the
class, as feature 18 added `despatch.create` to `StockResponder`'s table).

* `start()` subscribes the subjects (queue group `otc-billing`, so replicas answer once) with ONE
  callback that only enqueues `(subject, message)`, then AWAITS `connection.flush()` after the last
  `subscribe`: the host is reachable when startup returns (#8 id 63 / 95).
* `run(stop)` is the task body the lifespan creates, owns and awaits: the loop takes messages in
  order and serves each in its own task tracked in `in_flight`; on `stop` the subscriptions are
  unsubscribed, the requests already queued are still served, and `_drain` awaits EVERY in-flight
  task with `return_exceptions=True` (BC22, #8 id 50). Cancelling `run` cancels the request tasks
  and re-raises.
* A request waits for a slot of `asyncio.Semaphore(max_concurrent_requests)` BEFORE its unit of
  work opens a session (BC21): the engine's pool is sized from the same setting, so an admitted
  request never waits for a connection and a request blocked on a row lock degrades into waiting.
* One `BillingScope` per request (BC21). Every failure of the request path is answered with an
  `RpcError`; only a failure to REPLY escapes the request task (and is logged).
"""

import asyncio
import contextlib
import functools
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Final

import nats.errors
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.aio.subscription import Subscription

from otc_billing.application.ports.clock import Clock
from otc_billing.application.scope import BillingScope
from otc_billing.infrastructure.messaging.subjects import (
    BILLING_QUEUE_GROUP,
    CREDIT_HOLD_SUBJECT,
    CREDIT_LIST_SUBJECT,
    CREDIT_RELEASE_SUBJECT,
    INVOICE_ISSUE_SUBJECT,
    INVOICE_LIST_SUBJECT,
    PAYMENT_REGISTER_SUBJECT,
)
from otc_billing.presentation import credit_wire, invoice_wire, payment_wire
from otc_billing.presentation.credit_headers import optional_correlation_id, required_correlation
from otc_billing.presentation.credit_rpc_errors import map_error
from otc_contracts.generated.asyncapi import Code
from otc_cqrs import Dispatcher

log = logging.getLogger("otc_billing.presentation.credit_responder")

type Route = Callable[
    [bytes, Mapping[str, str] | None, Dispatcher[BillingScope], BillingScope],
    Awaitable[bytes],
]


async def _hold(
    body: bytes,
    headers: Mapping[str, str] | None,
    dispatcher: Dispatcher[BillingScope],
    scope: BillingScope,
) -> bytes:
    correlation = required_correlation(headers)  # BC1: headers first, nothing dispatched on failure
    result = await dispatcher.send(credit_wire.decode_hold(body, correlation), scope)
    return credit_wire.encode(credit_wire.hold_reply(result))


async def _release(
    body: bytes,
    headers: Mapping[str, str] | None,
    dispatcher: Dispatcher[BillingScope],
    scope: BillingScope,
) -> bytes:
    correlation = required_correlation(headers)
    result = await dispatcher.send(credit_wire.decode_release(body, correlation), scope)
    return credit_wire.encode(credit_wire.release_reply(result))


async def _list(
    body: bytes,
    headers: Mapping[str, str] | None,
    dispatcher: Dispatcher[BillingScope],
    scope: BillingScope,
) -> bytes:
    result = await dispatcher.ask(credit_wire.decode_list(body), scope)
    return credit_wire.encode(credit_wire.list_reply(result))


async def _invoice_issue(
    body: bytes,
    headers: Mapping[str, str] | None,
    dispatcher: Dispatcher[BillingScope],
    scope: BillingScope,
) -> bytes:
    correlation = required_correlation(headers)  # BI2: headers first, nothing dispatched on failure
    result = await dispatcher.send(invoice_wire.decode_issue(body, correlation), scope)
    return invoice_wire.encode(invoice_wire.issue_reply(result))


async def _invoice_list(
    body: bytes,
    headers: Mapping[str, str] | None,
    dispatcher: Dispatcher[BillingScope],
    scope: BillingScope,
) -> bytes:
    result = await dispatcher.ask(invoice_wire.decode_list(body), scope)
    return invoice_wire.encode(invoice_wire.list_reply(result))


async def _payment_register(
    body: bytes,
    headers: Mapping[str, str] | None,
    dispatcher: Dispatcher[BillingScope],
    scope: BillingScope,
) -> bytes:
    correlation = required_correlation(headers)  # headers first, nothing dispatched on failure
    result = await dispatcher.send(payment_wire.decode_register(body, correlation), scope)
    return payment_wire.encode(payment_wire.register_reply(result))


ROUTES: Final[dict[str, Route]] = {
    CREDIT_HOLD_SUBJECT: _hold,
    CREDIT_RELEASE_SUBJECT: _release,
    CREDIT_LIST_SUBJECT: _list,
    INVOICE_ISSUE_SUBJECT: _invoice_issue,
    INVOICE_LIST_SUBJECT: _invoice_list,
    PAYMENT_REGISTER_SUBJECT: _payment_register,
}


class CreditResponder:
    def __init__(
        self,
        *,
        connection: Client,
        dispatcher: Dispatcher[BillingScope],
        scope_factory: Callable[[], BillingScope],
        clock: Clock,
        max_concurrent_requests: int,
    ) -> None:
        self._connection = connection
        self._dispatcher = dispatcher
        self._scope_factory = scope_factory
        self._clock = clock
        self._bound = asyncio.Semaphore(max_concurrent_requests)
        self._inbox: asyncio.Queue[tuple[str, Msg] | None] = asyncio.Queue()
        self._subscriptions: list[Subscription] = []

    async def start(self) -> None:
        for subject in ROUTES:
            self._subscriptions.append(
                await self._connection.subscribe(
                    subject,
                    queue=BILLING_QUEUE_GROUP,
                    cb=functools.partial(self._enqueue, subject),
                )
            )
        # The server must have PROCESSED every SUB before startup returns (FS27).
        await self._connection.flush()

    async def _enqueue(self, subject: str, message: Msg) -> None:
        self._inbox.put_nowait((subject, message))

    async def run(self, stop: asyncio.Event) -> None:
        if not self._subscriptions:
            raise RuntimeError("CreditResponder.run() before start()")
        in_flight: set[asyncio.Task[None]] = set()
        waiter = asyncio.create_task(self._end_inbox_on(stop), name="credit responder stop waiter")
        try:
            while (item := await self._inbox.get()) is not None:
                self._serve_in_task(*item, in_flight)
            # stop was set: no new request is accepted, the ones already delivered are served
            for subscription in self._subscriptions:
                with contextlib.suppress(nats.errors.Error):
                    await subscription.unsubscribe()
            while not self._inbox.empty():
                if (queued := self._inbox.get_nowait()) is not None:
                    self._serve_in_task(*queued, in_flight)
        except asyncio.CancelledError:
            # Cancelled from outside (not a stop): the requests are cancelled with it, then the
            # cancellation continues.
            for task in in_flight:
                task.cancel()
            raise
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
            await self._drain(in_flight)

    async def _end_inbox_on(self, stop: asyncio.Event) -> None:
        await stop.wait()
        self._inbox.put_nowait(None)

    def _serve_in_task(
        self, subject: str, message: Msg, in_flight: set[asyncio.Task[None]]
    ) -> None:
        task = asyncio.create_task(self._serve(subject, message), name=f"{subject} request")
        in_flight.add(task)
        task.add_done_callback(in_flight.discard)
        task.add_done_callback(_log_fault)

    @staticmethod
    async def _drain(in_flight: set[asyncio.Task[None]]) -> None:
        # Waits for EVERY request; `return_exceptions` keeps one faulted request from leaving the
        # drain with the others still running (each fault was logged by `_log_fault`).
        await asyncio.gather(*tuple(in_flight), return_exceptions=True)

    async def _serve(self, subject: str, message: Msg) -> None:
        if not message.reply:
            log.warning("%s request carried no reply subject; dropped", subject)
            return
        async with self._bound:
            try:
                if not message.data:
                    raise credit_wire.InvalidCreditRequestError(
                        f"{subject} request carried no payload."
                    )
                reply = await ROUTES[subject](
                    message.data, message.headers, self._dispatcher, self._scope_factory()
                )
            except Exception as error:
                rpc_error = map_error(
                    error, self._clock.now(), optional_correlation_id(message.headers)
                )
                if rpc_error.code is Code.internal_error:
                    log.exception("%s failed", subject)
                else:
                    log.warning(
                        "%s refused: %s %s", subject, rpc_error.code.value, rpc_error.message
                    )
                reply = credit_wire.encode(rpc_error)
        await message.respond(reply)


def _log_fault(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (error := task.exception()) is not None:
        log.error("a billing.credit request could not be answered", exc_info=error)
