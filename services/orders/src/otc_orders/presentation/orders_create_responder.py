"""The Orders NATS responder: ONE asyncio task for the service's three subscriptions
(`orders.create`, `catalog.reference.list` (feature 40) and `orders.cancel` (feature 41)).

`ROUTES` is the table, one entry per subject (the pattern of Billing's `CreditResponder` and
Fulfillment's `StockResponder`: a subject is added as an entry, the class is not renamed and no
second task is started). Both subjects join the queue group `otc-orders`, so a replica set answers
each request once.

`start()` subscribes (so a subscription failure is a boot failure) and AWAITS `flush()`, so the
server has processed every SUB before startup returns and a request sent right after boot finds a
responder; `run(stop)` is the task body the lifespan creates, owns and awaits.

* nats-py hands each message to a callback that only enqueues it; the loop in `run` takes messages
  in order and serves each in its own task (concurrent requests do not queue behind a slow one),
  every task tracked in `in_flight` and never left unowned.
* One `OrdersScope` per request (`scope_factory`), the dispatcher resolved against it.
* Every failure of the request path is answered with an `RpcError` (never a silent drop); only a
  failure to REPLY escapes the request task.
* Shutdown (#8 id 50): `stop` ends the loop; the subscription is closed; the requests already
  queued or running are served to the end (the drain WAITS for every one), and a request whose
  reply failed is logged and does not propagate out of the drain. Cancellation of `run` itself is
  never swallowed.
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
from opentelemetry.trace import SpanKind, Tracer
from structlog.contextvars import bound_contextvars

from otc_contracts.generated.asyncapi import Code
from otc_cqrs import Dispatcher
from otc_orders.application.ports.clock import Clock
from otc_orders.application.scope import OrdersScope
from otc_orders.infrastructure.messaging.subjects import (
    CATALOG_REFERENCE_LIST_SUBJECT,
    ORDERS_CANCEL_SUBJECT,
    ORDERS_CREATE_SUBJECT,
    ORDERS_QUEUE_GROUP,
)
from otc_orders.infrastructure.observability.trace_context import NO_TRACER, extract_nats
from otc_orders.presentation import catalog_reference_list, orders_cancel
from otc_orders.presentation.orders_create import (
    InvalidOrdersCreateRequestError,
    decode_request,
    encode,
    map_error,
    to_command,
    to_reply,
)
from otc_shared_kernel import InvalidUniqueIdError, UniqueId

log = logging.getLogger("otc_orders.presentation.orders_create_responder")

CORRELATION_HEADER: Final = "x-correlation-id"

type Route = Callable[[bytes, Dispatcher[OrdersScope], OrdersScope], Awaitable[bytes]]


async def _orders_create(
    body: bytes, dispatcher: Dispatcher[OrdersScope], scope: OrdersScope
) -> bytes:
    if not body:
        raise InvalidOrdersCreateRequestError("orders.create request carried no payload.")
    result = await dispatcher.send(to_command(decode_request(body)), scope)
    return encode(to_reply(result))


async def _catalog_reference_list(
    body: bytes, dispatcher: Dispatcher[OrdersScope], scope: OrdersScope
) -> bytes:
    request = catalog_reference_list.decode_request(body)
    listing = await dispatcher.ask(catalog_reference_list.to_query(request), scope)
    return catalog_reference_list.encode(catalog_reference_list.to_reply(listing))


async def _orders_cancel(
    body: bytes, dispatcher: Dispatcher[OrdersScope], scope: OrdersScope
) -> bytes:
    result = await dispatcher.send(
        orders_cancel.to_command(orders_cancel.decode_request(body)), scope
    )
    return orders_cancel.encode(orders_cancel.to_reply(result))


ROUTES: Final[dict[str, Route]] = {
    ORDERS_CREATE_SUBJECT: _orders_create,
    CATALOG_REFERENCE_LIST_SUBJECT: _catalog_reference_list,
    ORDERS_CANCEL_SUBJECT: _orders_cancel,
}


class OrdersCreateResponder:
    def __init__(
        self,
        *,
        connection: Client,
        dispatcher: Dispatcher[OrdersScope],
        scope_factory: Callable[[], OrdersScope],
        clock: Clock,
        tracer: Tracer = NO_TRACER,
    ) -> None:
        self._tracer = tracer
        self._connection = connection
        self._dispatcher = dispatcher
        self._scope_factory = scope_factory
        self._clock = clock
        self._inbox: asyncio.Queue[tuple[str, Msg] | None] = asyncio.Queue()
        self._subscriptions: list[Subscription] = []

    async def start(self) -> None:
        for subject in ROUTES:
            self._subscriptions.append(
                await self._connection.subscribe(
                    subject,
                    queue=ORDERS_QUEUE_GROUP,
                    cb=functools.partial(self._enqueue, subject),
                )
            )
        # The server must have PROCESSED every SUB before startup returns.
        await self._connection.flush()

    async def _enqueue(self, subject: str, message: Msg) -> None:
        self._inbox.put_nowait((subject, message))

    async def run(self, stop: asyncio.Event) -> None:
        if not self._subscriptions:
            raise RuntimeError("OrdersCreateResponder.run() before start()")
        in_flight: set[asyncio.Task[None]] = set()
        waiter = asyncio.create_task(self._end_inbox_on(stop), name="orders responder stop waiter")
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
        """One request is one unit of work: its lines carry the caller's `x-correlation-id` when it
        parses as a UUID, and no `correlationId` at all otherwise (never a fabricated one). It is
        also one `SERVER` span, a child of the caller's span when the request carries a valid
        `traceparent` and a root otherwise (`R56`; the single extraction site of this class: every
        subject passes through here)."""
        with self._tracer.start_as_current_span(
            f"{subject} serve",
            context=extract_nats(message.headers),
            kind=SpanKind.SERVER,
            attributes={"messaging.system": "nats", "messaging.destination.name": subject},
        ):
            correlation_id = _correlation_of(message.headers)
            if correlation_id is None:
                await self._answer(subject, message)
                return
            with bound_contextvars(correlationId=str(correlation_id)):
                await self._answer(subject, message)

    async def _answer(self, subject: str, message: Msg) -> None:
        if not message.reply:
            log.warning("%s request carried no reply subject; dropped", subject)
            return
        try:
            reply = await ROUTES[subject](message.data, self._dispatcher, self._scope_factory())
        except Exception as error:
            rpc_error = map_error(error, self._clock.now())
            if rpc_error.code is Code.internal_error:
                log.exception("%s failed", subject)
            else:
                log.warning("%s refused: %s %s", subject, rpc_error.code.value, rpc_error.message)
            reply = encode(rpc_error)
        await message.respond(reply)


def _correlation_of(headers: Mapping[str, str] | None) -> UniqueId | None:
    value = None if headers is None else headers.get(CORRELATION_HEADER)
    if value is None:
        return None
    try:
        return UniqueId.parse(value)
    except InvalidUniqueIdError:
        return None


def _log_fault(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (error := task.exception()) is not None:
        log.error("an Orders RPC request could not be answered", exc_info=error)
