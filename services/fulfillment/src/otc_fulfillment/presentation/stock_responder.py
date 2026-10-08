"""The `fulfillment.*` NATS responder: ONE asyncio task for six subscriptions (the five
`fulfillment.stock.*` subjects and, from feature 18, `fulfillment.despatch.create`).

Orders' `OrdersCreateResponder` generalised to a subject table (`ROUTES`: one entry per subject).

* `start()` subscribes the six subjects (queue group `otc-fulfillment`, so replicas answer once)
  with ONE callback that only enqueues `(subject, message)`, then AWAITS `connection.flush()` after
  the last `subscribe`: the host is reachable when startup returns (FS27, #8 id 95).
* `run(stop)` is the task body the lifespan creates, owns and awaits: the loop takes messages in
  order and serves each in its own task tracked in `in_flight`; on `stop` the subscriptions are
  unsubscribed, the requests already queued are still served, and `_drain` awaits EVERY in-flight
  task with `return_exceptions=True` (FS26, #8 id 50). Cancelling `run` cancels the request tasks
  and re-raises.
* A request waits for a slot of `asyncio.Semaphore(max_concurrent_requests)` BEFORE its unit of
  work opens a session (FS18, L7): the engine's pool is sized from the same setting, so an admitted
  request never waits for a connection and a request blocked on a row lock degrades into waiting.
* One `FulfillmentScope` per request. Every failure of the request path is answered with an
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

from otc_contracts.generated.asyncapi import Code
from otc_cqrs import Dispatcher
from otc_fulfillment.application.ports.clock import Clock
from otc_fulfillment.application.scope import FulfillmentScope
from otc_fulfillment.infrastructure.messaging.subjects import (
    DESPATCH_CREATE_SUBJECT,
    FULFILLMENT_QUEUE_GROUP,
    STOCK_CHECK_SUBJECT,
    STOCK_LIST_SUBJECT,
    STOCK_RELEASE_SUBJECT,
    STOCK_REPLENISH_SUBJECT,
    STOCK_RESERVE_SUBJECT,
)
from otc_fulfillment.presentation import stock_wire
from otc_fulfillment.presentation.stock_headers import optional_correlation_id, required_correlation
from otc_fulfillment.presentation.stock_rpc_errors import map_error

log = logging.getLogger("otc_fulfillment.presentation.stock_responder")

type Route = Callable[
    [bytes, Mapping[str, str] | None, Dispatcher[FulfillmentScope], FulfillmentScope],
    Awaitable[bytes],
]


async def _check(
    body: bytes,
    headers: Mapping[str, str] | None,
    dispatcher: Dispatcher[FulfillmentScope],
    scope: FulfillmentScope,
) -> bytes:
    result = await dispatcher.ask(stock_wire.decode_check(body), scope)
    return stock_wire.encode(stock_wire.check_reply(result))


async def _list(
    body: bytes,
    headers: Mapping[str, str] | None,
    dispatcher: Dispatcher[FulfillmentScope],
    scope: FulfillmentScope,
) -> bytes:
    result = await dispatcher.ask(stock_wire.decode_list(body), scope)
    return stock_wire.encode(stock_wire.list_reply(result))


async def _reserve(
    body: bytes,
    headers: Mapping[str, str] | None,
    dispatcher: Dispatcher[FulfillmentScope],
    scope: FulfillmentScope,
) -> bytes:
    correlation = required_correlation(headers)  # FS3: headers first, nothing dispatched on failure
    result = await dispatcher.send(stock_wire.decode_reserve(body, correlation), scope)
    return stock_wire.encode(stock_wire.reserve_reply(result))


async def _release(
    body: bytes,
    headers: Mapping[str, str] | None,
    dispatcher: Dispatcher[FulfillmentScope],
    scope: FulfillmentScope,
) -> bytes:
    correlation = required_correlation(headers)
    result = await dispatcher.send(stock_wire.decode_release(body, correlation), scope)
    return stock_wire.encode(stock_wire.release_reply(result))


async def _replenish(
    body: bytes,
    headers: Mapping[str, str] | None,
    dispatcher: Dispatcher[FulfillmentScope],
    scope: FulfillmentScope,
) -> bytes:
    result = await dispatcher.send(stock_wire.decode_replenish(body), scope)
    return stock_wire.encode(stock_wire.replenish_reply(result))


async def _despatch(
    body: bytes,
    headers: Mapping[str, str] | None,
    dispatcher: Dispatcher[FulfillmentScope],
    scope: FulfillmentScope,
) -> bytes:
    correlation = required_correlation(headers)  # the fact's correlationId / causationId (R12)
    result = await dispatcher.send(stock_wire.decode_despatch(body, correlation), scope)
    return stock_wire.encode(stock_wire.despatch_reply(result))


ROUTES: Final[dict[str, Route]] = {
    STOCK_CHECK_SUBJECT: _check,
    STOCK_RESERVE_SUBJECT: _reserve,
    STOCK_RELEASE_SUBJECT: _release,
    STOCK_LIST_SUBJECT: _list,
    STOCK_REPLENISH_SUBJECT: _replenish,
    DESPATCH_CREATE_SUBJECT: _despatch,
}


class StockResponder:
    def __init__(
        self,
        *,
        connection: Client,
        dispatcher: Dispatcher[FulfillmentScope],
        scope_factory: Callable[[], FulfillmentScope],
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
                    queue=FULFILLMENT_QUEUE_GROUP,
                    cb=functools.partial(self._enqueue, subject),
                )
            )
        # The server must have PROCESSED every SUB before startup returns (FS27).
        await self._connection.flush()

    async def _enqueue(self, subject: str, message: Msg) -> None:
        self._inbox.put_nowait((subject, message))

    async def run(self, stop: asyncio.Event) -> None:
        if not self._subscriptions:
            raise RuntimeError("StockResponder.run() before start()")
        in_flight: set[asyncio.Task[None]] = set()
        waiter = asyncio.create_task(self._end_inbox_on(stop), name="stock responder stop waiter")
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
                    raise stock_wire.InvalidStockRequestError(
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
                reply = stock_wire.encode(rpc_error)
        await message.respond(reply)


def _log_fault(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (error := task.exception()) is not None:
        log.error("a fulfillment.stock request could not be answered", exc_info=error)
