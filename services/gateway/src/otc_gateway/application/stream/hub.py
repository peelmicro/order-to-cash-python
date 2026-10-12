"""`StreamHub`: one process-wide bounded replay buffer plus a fan-out to every open SSE connection.

Fed by the NATS subscriber (infrastructure), read by `GET /orders/stream` (presentation). Not a
command or query handler: it answers no message (the same "neither" as #7 `stream-hub.ts` and #8
`StreamHub.cs`).

Ported idioms (the full ledger is `progress/impl_gateway_sse_push.md`):

* #7 fans out through one RxJS `Subject`; #8 keeps one bounded `Channel<T>` per connection; here
  each
  connection owns one `Subscription`, a bounded deque plus an `asyncio.Event`.
* THE OVERFLOW POLICY differs from #8 (`StreamHub.cs`, `BoundedChannelFullMode.DropOldest`, 256) and
  from #7 (an unbounded `Subject`, `res.write` ignoring back-pressure). Drop-oldest silently loses
  frames the client's `Last-Event-ID` then steps past, which breaks the contract's at-least-once
  ("A frame may repeat after a reconnect", never "may be missing"). Here a subscriber whose queue is
  full is marked `overflowed` and ITS connection is ended by the route: the browser's `EventSource`
  reconnects with its last processed id and the replay buffer returns exactly what it had not seen
  (complete while the frames the queue held plus the frames published during the reconnect are
  fewer than the buffer; otherwise the cursor was evicted, the reply says `resumed: false` and the
  client re-fetches, which the contract allows). `publish` never waits on a subscriber, so a slow
  client cannot block the fan-out.
* `publish` is a plain synchronous method with no `await`: the cursor is minted, the frame is
  buffered and every subscriber is fed in one uninterruptible step, so the buffer's order IS the
  cursor's order (the hand-built replacement for #8's `Interlocked`; held by
  `tests/unit/test_gateway_sse_hub.py`).
"""

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from otc_gateway.domain.sse.cursor import CursorGenerator
from otc_gateway.domain.sse.replay_buffer import ReplayBuffer, ReplayResult


@dataclass(frozen=True, slots=True)
class StreamFrame:
    """One `order.updated` / `timeline.appended` frame: `data_json` is the exact text the Projector
    published (never decoded and re-encoded), so it is what the Projector wrote."""

    cursor: str
    event_type: str
    order_id: UUID
    data_json: str


class Subscription:
    """One connection's inbox. Bounded; `overflowed` is set instead of ever blocking the
    publisher."""

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._frames: deque[StreamFrame] = deque()
        self._wake = asyncio.Event()
        self.overflowed = False

    def offer(self, frame: StreamFrame) -> None:
        if self.overflowed:
            return
        if len(self._frames) >= self._capacity:
            self.overflowed = True
            self._frames.clear()
        else:
            self._frames.append(frame)
        self._wake.set()

    async def get(self) -> StreamFrame | None:
        """The next frame, or None when the subscription overflowed (the caller ends the stream).
        Cancel-safe: nothing is removed before the call returns."""
        while not self._frames:
            if self.overflowed:
                return None
            self._wake.clear()
            await self._wake.wait()
        return self._frames.popleft()


class StreamHub:
    def __init__(
        self,
        now_ms: Callable[[], int],
        *,
        replay_capacity: int,
        subscriber_capacity: int,
    ) -> None:
        if subscriber_capacity < 1:
            raise ValueError(
                f"StreamHub: subscriber_capacity must be at least 1, got {subscriber_capacity}"
            )
        self._cursor = CursorGenerator(now_ms)
        self._buffer: ReplayBuffer[StreamFrame] = ReplayBuffer(replay_capacity)
        self._subscribers: set[Subscription] = set()
        self._subscriber_capacity = subscriber_capacity

    def publish(self, event_type: str, order_id: UUID, data_json: str) -> StreamFrame:
        frame = StreamFrame(self._cursor.next(), event_type, order_id, data_json)
        self._buffer.push(frame.cursor, frame)
        for subscription in tuple(self._subscribers):
            subscription.offer(frame)
        return frame

    def replay_after(self, cursor: str | None) -> ReplayResult[StreamFrame]:
        return self._buffer.replay_after(cursor)

    def mint_cursor(self) -> str:
        """A cursor NOT pushed to the buffer: `stream.ready` names a moment and has nothing to
        replay (and carries no `id:` line, `openapi.yaml`'s ping/ready rule)."""
        return self._cursor.next()

    def subscribe(self) -> Subscription:
        subscription = Subscription(self._subscriber_capacity)
        self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        self._subscribers.discard(subscription)

    @property
    def subscriber_count(self) -> int:
        """The number of live subscriptions: the teardown guard's observable."""
        return len(self._subscribers)
