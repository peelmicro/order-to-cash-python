"""The clocks: wall time for instants on the wire, a monotonic millisecond count for the windows."""

import time
from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def monotonic_ms() -> int:
    """Whole milliseconds on the monotonic clock: what `IssuedOrderWindow` and `LoginThrottle` take.
    Never goes backwards, so a wall-clock step cannot reopen a closed login window."""
    return time.monotonic_ns() // 1_000_000
