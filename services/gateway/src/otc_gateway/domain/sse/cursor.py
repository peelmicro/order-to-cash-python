"""The SSE frame `id:` cursor: `<epoch milliseconds>-<sequence>` (`openapi.yaml` `/orders/stream`,
"Frame format": opaque and monotonically increasing).

Ported from #7 `apps/gateway/src/domain/sse/cursor.ts` (a plain `this.sequence += 1`, safe because
Node's event loop is single-threaded) and #8 `Domain/Sse/CursorGenerator.cs`
(`Interlocked.Increment`,
needed because two NATS loops ran on the thread pool). #9 runs on ONE event loop and `next` is a
plain
synchronous method: there is no `await` between reading the sequence and writing it, so two tasks
cannot interleave inside it. That is a property of this method being synchronous, which
`tests/unit/test_gateway_sse_domain.py` holds (it must not become a coroutine function) together
with
a many-task uniqueness run. The cursor is NOT safe to call from a second thread, and nothing does.
"""

from collections.abc import Callable


class CursorGenerator:
    def __init__(self, now_ms: Callable[[], int]) -> None:
        self._now_ms = now_ms
        self._sequence = 0

    def next(self) -> str:
        self._sequence += 1
        return f"{self._now_ms()}-{self._sequence}"
