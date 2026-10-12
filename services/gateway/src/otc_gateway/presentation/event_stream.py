"""`EventStreamResponse`: the SSE response of `GET /orders/stream`, written against the ASGI
protocol directly.

Why not `StreamingResponse` with an async generator (#7 bypassed Nest's `@Sse()`, #8 wrote the body
by hand, both for the same reason: exact control of the headers and the frame): a generator's
`finally` runs only when the generator is closed, and `StreamingResponse` cancels the task that is
iterating it, which is deterministic ONLY while that task is parked inside the generator. Cancelled
inside `send` (a client that stopped reading) the generator stays suspended and its `finally` waits
for the garbage collector. Here the subscription is taken and released in `__call__` itself, in one
`try`/`finally` that no suspension point can step around.

THE TEARDOWN IS HAND-BUILT (#8 D1). #7's was Express's engine-supplied `res.on('close')`
(`stream.controller.ts:80-83`); #8's was `RequestAborted` + `finally { Unsubscribe }`. Here three
things must hold, each armed in `tests/unit/test_gateway_sse_teardown.py`: the disconnect is WATCHED
(`receive` is read for `http.disconnect` in a sibling task, the only way an idle connection learns
its client left, without waiting for a ping to hit a dead socket), the watcher ENDS the pump (it is
cancelled and awaited), and the unsubscribe is in a `finally` on the SAME hub the publisher uses.

`ping` and `stream.ready` carry no `id:` line (`openapi.yaml`, "Frame format"): a heartbeat id would
become the client's resume point and every reconnect would answer `resumed: false`.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from otc_contracts import to_wire_json
from otc_contracts.generated import openapi
from otc_gateway.application.stream.hub import StreamFrame, StreamHub, Subscription

EVENT_STREAM_HEADERS: list[tuple[bytes, bytes]] = [
    (b"content-type", b"text/event-stream"),
    (b"cache-control", b"no-cache"),
    (b"connection", b"keep-alive"),
]


def frame_bytes(frame_id: str | None, event: str, data: str) -> bytes:
    lines = [] if frame_id is None else [f"id: {frame_id}\n"]
    lines.append(f"event: {event}\n")
    lines.append(f"data: {data}\n\n")
    return "".join(lines).encode("utf-8")


class EventStreamResponse(Response):
    def __init__(
        self,
        hub: StreamHub,
        *,
        order_id: UUID | None,
        last_event_id: str | None,
        ping_interval_seconds: float,
        now: Callable[[], datetime],
    ) -> None:
        super().__init__(status_code=200)
        self._hub = hub
        self._order_id = order_id
        self._last_event_id = last_event_id or None
        self._ping_interval = ping_interval_seconds
        self._now = now

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Subscribed BEFORE the replay snapshot is read (#8's order, closing the race #7's
        # controller has): a frame published in between is then delivered twice at worst (live
        # and replayed), which the contract allows (at-least-once), never lost.
        subscription = self._hub.subscribe()
        try:
            pump = asyncio.create_task(self._pump(subscription, send), name="sse-pump")
            watcher = asyncio.create_task(self._watch_disconnect(receive), name="sse-disconnect")
            try:
                await asyncio.wait({pump, watcher}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in (pump, watcher):
                    task.cancel()
                await asyncio.wait({pump, watcher})
        finally:
            self._hub.unsubscribe(subscription)
        if pump.done() and not pump.cancelled() and (error := pump.exception()) is not None:
            raise error

    @staticmethod
    async def _watch_disconnect(receive: Receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return

    def _matches(self, frame: StreamFrame) -> bool:
        return self._order_id is None or frame.order_id == self._order_id

    async def _write(self, send: Send, chunk: bytes) -> None:
        await send({"type": "http.response.body", "body": chunk, "more_body": True})

    async def _pump(self, subscription: Subscription, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": EVENT_STREAM_HEADERS})
        replay = self._hub.replay_after(self._last_event_id)
        ready_cursor = self._last_event_id or self._hub.mint_cursor()
        ready = openapi.StreamReady(
            cursor=ready_cursor, resumed=replay.resumed, order_id=self._order_id
        )
        await self._write(send, frame_bytes(None, "stream.ready", to_wire_json(ready)))
        for missed in replay.missed:
            if self._matches(missed):
                await self._write(
                    send, frame_bytes(missed.cursor, missed.event_type, missed.data_json)
                )

        loop = asyncio.get_running_loop()
        next_ping = loop.time() + self._ping_interval
        while True:
            try:
                async with asyncio.timeout_at(next_ping):
                    frame = await subscription.get()
            except TimeoutError:
                self._hub.mint_cursor()  # consumed for its side effect on the cursor sequence only
                ping = openapi.StreamPing(at=self._now())
                await self._write(send, frame_bytes(None, "ping", to_wire_json(ping)))
                next_ping = max(next_ping + self._ping_interval, loop.time())
                continue
            if frame is None:
                # the subscription overflowed: end the response, the client resumes from its cursor
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                return
            if self._matches(frame):
                await self._write(
                    send, frame_bytes(frame.cursor, frame.event_type, frame.data_json)
                )


__all__ = ["EventStreamResponse", "frame_bytes"]
