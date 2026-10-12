"""`LoginThrottle`: the fixed-window limit on `POST /auth/login` (R63).

R63 fixes what a client observes when it trips the limit and nothing else: the attempt count, the
window and the tracking key are per-assessment (`requirements.md` section 8.1). #9's choices, #7's
(`apps/gateway/src/infrastructure/auth/login-throttle.config.ts:63-76`): a FIXED window of
`window_ms`
that admits `limit` attempts per CLIENT ADDRESS, counted on every attempt whatever the credentials
were, so the refusal says nothing about them. The state is per process.

`check` returns `0` when the attempt is admitted, or the whole number of SECONDS to wait (rounded
up,
at least 1) when it is refused. Time is an integer millisecond count from the caller. A refused
attempt is not counted again: the window is not extended by a client that keeps knocking.
"""

from collections.abc import Callable
from dataclasses import dataclass

# More distinct keys than this and the table drops every expired window before it admits a new one.
_PRUNE_ABOVE = 4096


@dataclass(slots=True)
class _Window:
    started_ms: int
    attempts: int


class LoginThrottle:
    def __init__(self, now_ms: Callable[[], int], *, limit: int, window_ms: int) -> None:
        if limit < 1:
            raise ValueError(f"LoginThrottle: limit must be at least 1, got {limit}")
        if window_ms < 1:
            raise ValueError(f"LoginThrottle: window_ms must be at least 1, got {window_ms}")
        self._now_ms = now_ms
        self._limit = limit
        self._window_ms = window_ms
        self._windows: dict[str, _Window] = {}

    def check(self, key: str) -> int:
        now = self._now_ms()
        if len(self._windows) > _PRUNE_ABOVE:
            self._windows = {
                k: w for k, w in self._windows.items() if now - w.started_ms < self._window_ms
            }
        window = self._windows.get(key)
        if window is None or now - window.started_ms >= self._window_ms:
            self._windows[key] = _Window(started_ms=now, attempts=1)
            return 0
        if window.attempts < self._limit:
            window.attempts += 1
            return 0
        remaining_ms = self._window_ms - (now - window.started_ms)
        return max(1, -(-remaining_ms // 1000))  # ceil without a true division
