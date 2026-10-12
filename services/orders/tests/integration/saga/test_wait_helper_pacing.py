"""The saga harness's wait helper is PACED (#8 id 63: unpaced retry loops).

`wait_then_assert` polls a predicate until it holds. Without a sleep between polls it would spin on
the event loop and hammer PostgreSQL. The pacing is proven by a change of KIND, not of probability:
a predicate that becomes true only after a fixed stretch of wall time is polled a number of times
that a paced loop cannot exceed and an unpaced one cannot stay under (a spin makes thousands of
calls in that stretch, a 50 ms pace at most a few dozen).
"""

import time
from collections.abc import Awaitable, Callable

STRETCH_SECONDS = 0.6


async def test_the_wait_helper_sleeps_between_polls(
    waits: Callable[..., Awaitable[None]],
) -> None:
    calls = 0
    started = time.monotonic()

    async def after_the_stretch() -> bool:
        nonlocal calls
        calls += 1
        return time.monotonic() - started >= STRETCH_SECONDS

    await waits(after_the_stretch, "the stretch has elapsed")

    assert 3 <= calls <= 40, f"{calls} polls in {STRETCH_SECONDS}s: the loop is not paced"
