"""The `orders.create` NATS responder: ONE asyncio task for the transport's one subscription.

`start()` subscribes (so a subscription failure is a boot failure and a request sent right after
boot finds a responder); `run(stop)` is the task body the lifespan creates, owns and awaits.

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
import logging
from collections.abc import Callable

import nats.errors
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.aio.subscription import Subscription

from otc_contracts.generated.asyncapi import Code
from otc_cqrs import Dispatcher
from otc_orders.application.ports.clock import Clock
from otc_orders.application.scope import OrdersScope
from otc_orders.infrastructure.messaging.subjects import ORDERS_CREATE_SUBJECT, ORDERS_QUEUE_GROUP
from otc_orders.presentation.orders_create import (
    InvalidOrdersCreateRequestError,
    decode_request,
    encode,
    map_error,
    to_command,
    to_reply,
)

log = logging.getLogger("otc_orders.presentation.orders_create_responder")


class OrdersCreateResponder:
    def __init__(
        self,
        *,
        connection: Client,
        dispatcher: Dispatcher[OrdersScope],
        scope_factory: Callable[[], OrdersScope],
        clock: Clock,
    ) -> None:
        self._connection = connection
        self._dispatcher = dispatcher
        self._scope_factory = scope_factory
        self._clock = clock
        self._inbox: asyncio.Queue[Msg | None] = asyncio.Queue()
        self._subscription: Subscription | None = None

    async def start(self) -> None:
        self._subscription = await self._connection.subscribe(
            ORDERS_CREATE_SUBJECT, queue=ORDERS_QUEUE_GROUP, cb=self._enqueue
        )

    async def _enqueue(self, message: Msg) -> None:
        self._inbox.put_nowait(message)

    async def run(self, stop: asyncio.Event) -> None:
        if self._subscription is None:
            raise RuntimeError("OrdersCreateResponder.run() before start()")
        in_flight: set[asyncio.Task[None]] = set()
        waiter = asyncio.create_task(self._end_inbox_on(stop), name="orders.create stop waiter")
        try:
            while (message := await self._inbox.get()) is not None:
                self._serve_in_task(message, in_flight)
            # stop was set: no new request is accepted, the ones already delivered are served
            with contextlib.suppress(nats.errors.Error):
                await self._subscription.unsubscribe()
            while not self._inbox.empty():
                if (queued := self._inbox.get_nowait()) is not None:
                    self._serve_in_task(queued, in_flight)
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

    def _serve_in_task(self, message: Msg, in_flight: set[asyncio.Task[None]]) -> None:
        task = asyncio.create_task(self._serve(message), name="orders.create request")
        in_flight.add(task)
        task.add_done_callback(in_flight.discard)
        task.add_done_callback(_log_fault)

    @staticmethod
    async def _drain(in_flight: set[asyncio.Task[None]]) -> None:
        # Waits for EVERY request; `return_exceptions` keeps one faulted request from leaving the
        # drain with the others still running (each fault was logged by `_log_fault`).
        await asyncio.gather(*tuple(in_flight), return_exceptions=True)

    async def _serve(self, message: Msg) -> None:
        if not message.reply:
            log.warning("orders.create request carried no reply subject; dropped")
            return
        try:
            if not message.data:
                raise InvalidOrdersCreateRequestError("orders.create request carried no payload.")
            command = to_command(decode_request(message.data))
            result = await self._dispatcher.send(command, self._scope_factory())
            reply = encode(to_reply(result))
        except Exception as error:
            rpc_error = map_error(error, self._clock.now())
            if rpc_error.code is Code.internal_error:
                log.exception("orders.create failed")
            else:
                log.warning("orders.create refused: %s %s", rpc_error.code.value, rpc_error.message)
            reply = encode(rpc_error)
        await message.respond(reply)


def _log_fault(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (error := task.exception()) is not None:
        log.error("an orders.create request could not be answered", exc_info=error)
