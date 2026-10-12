"""`IssuedOrderWindow`: the order ids THIS process handed out from `POST /orders` recently.

R55: "WHILE no read-model document yet exists for an order identifier that the caller has just been
given, THE SYSTEM SHALL respond with an explicit projection pending indication rather than a
not-found error". The Gateway is the component that hands the id out, so "just been given" is an id
this window remembers; any other id with no document is a genuine 404 (`openapi.yaml` `getOrder`).
Without the window every miss would answer 202 and the documented 404 would be unreachable (#7
review finding F3, ported by #8 as `IssuedOrderWindow.cs`).

The window is PER PROCESS (a replica that did not hand the id out answers 404 for it) and bounded in
both ways: a record older than `ttl_ms` is forgotten, and the oldest is evicted first beyond
`capacity`. Time is an integer millisecond count from the caller's monotonic clock.
"""

from collections import OrderedDict
from collections.abc import Callable
from uuid import UUID


class IssuedOrderWindow:
    def __init__(self, now_ms: Callable[[], int], *, ttl_ms: int, capacity: int) -> None:
        if ttl_ms < 1:
            raise ValueError(f"IssuedOrderWindow: ttl_ms must be at least 1, got {ttl_ms}")
        if capacity < 1:
            raise ValueError(f"IssuedOrderWindow: capacity must be at least 1, got {capacity}")
        self._now_ms = now_ms
        self._ttl_ms = ttl_ms
        self._capacity = capacity
        self._issued_at: OrderedDict[UUID, int] = OrderedDict()

    def record(self, order_id: UUID) -> None:
        self._issued_at.pop(order_id, None)  # a re-recorded id moves to the newest end
        self._issued_at[order_id] = self._now_ms()
        while len(self._issued_at) > self._capacity:
            self._issued_at.popitem(last=False)

    def is_recently_issued(self, order_id: UUID) -> bool:
        issued_at = self._issued_at.get(order_id)
        if issued_at is None:
            return False
        if self._now_ms() - issued_at > self._ttl_ms:
            del self._issued_at[order_id]  # an expired entry is evicted by the read that finds it
            return False
        return True

    def __len__(self) -> int:
        return len(self._issued_at)
