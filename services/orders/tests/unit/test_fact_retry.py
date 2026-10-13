# ruff: noqa: E501 - test names are claims, spelled out in full
"""`FactRetry` (`R16`, `OR1`, `OR8`): the retry loop, the dead-letter hand-off and what it must NOT do.

Pure: a fake clock that ADVANCES at every reading (so two readings are never equal and a value taken
from the wrong reading cannot hide), a recording `sleep`, a recording dead-letter publisher and a
work callable that fails on demand. No broker, no event loop beyond pytest-asyncio's.

Fixture discipline: the five instants that matter (entry, first failure, final failure, the
envelope's `occurredAt`, and the end) are pairwise distinct, so `x-first-failed-at` cannot be the
entry instant (#7 `fact-retry-dispatcher.ts:135-136`) or the final one without a test failing.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest

from otc_orders.application.ports.fact_stream import FactMessage
from otc_orders.infrastructure.messaging.fact_retry import (
    DeadLetter,
    FactRetry,
    FactRetryPolicy,
    FactRetryStopped,
    stop_aware_sleep,
)

CONSUMER = "orders.saga"
TOPIC = "otc.billing.facts.v1"
EVENT_TYPE = "credit.approved.v1"
START = datetime(2026, 10, 12, 9, 0, 0, 0, tzinfo=UTC)
STEP = timedelta(milliseconds=137, microseconds=500)
# The envelope's own `occurredAt`: before everything the clock will say, and not on its grid.
OCCURRED_AT = START - timedelta(minutes=3, milliseconds=41)


class AdvancingClock:
    """Every `now()` returns START + n * STEP, n counting readings from 0."""

    def __init__(self) -> None:
        self.readings: list[datetime] = []

    def now(self) -> datetime:
        reading = START + len(self.readings) * STEP
        self.readings.append(reading)
        return reading


class Sleeps:
    def __init__(self, fail_with: BaseException | None = None) -> None:
        self.seconds: list[float] = []
        self._fail_with = fail_with

    async def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)
        if self._fail_with is not None:
            raise self._fail_with


class Publisher:
    def __init__(self, fail_with: Exception | None = None) -> None:
        self.letters: list[DeadLetter] = []
        self._fail_with = fail_with

    async def publish(self, letter: DeadLetter) -> None:
        if self._fail_with is not None:
            raise self._fail_with
        self.letters.append(letter)


class Latencies:
    def __init__(self) -> None:
        self.recorded: list[tuple[float, str]] = []

    def record(self, milliseconds: float, consumer: str) -> None:
        self.recorded.append((milliseconds, consumer))


class Work:
    """A work callable that fails `failures` times (then succeeds), or always when `failures` is
    None; counts its calls."""

    def __init__(
        self, failures: int | None = None, on_call: Callable[[int], None] | None = None
    ) -> None:
        self.calls = 0
        self._failures = failures
        self._on_call = on_call

    async def __call__(self) -> None:
        self.calls += 1
        if self._on_call is not None:
            self._on_call(self.calls)
        if self._failures is None or self.calls <= self._failures:
            raise ValueError(f"poison on attempt {self.calls}")


def message(value: bytes = b'{"eventId":"original bytes"}') -> FactMessage:
    return FactMessage(
        topic=TOPIC, partition=4, offset=88, key=b"correlation-key", value=value, headers=()
    )


def retry_over(
    *,
    policy: FactRetryPolicy | None = None,
    clock: AdvancingClock | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    publisher: Publisher | None = None,
    latencies: Latencies | None = None,
) -> FactRetry:
    return FactRetry(
        consumer=CONSUMER,
        policy=FactRetryPolicy(max_attempts=3, backoff_ms=500) if policy is None else policy,
        clock=AdvancingClock() if clock is None else clock,
        sleep=Sleeps() if sleep is None else sleep,
        dead_letters=Publisher() if publisher is None else publisher,
        latency=Latencies() if latencies is None else latencies,
    )


async def test_or1_retries_to_the_maximum_with_doubling_backoff_then_dead_letters_and_returns() -> (
    None
):
    sleeps, publisher, work = Sleeps(), Publisher(), Work()

    # it RETURNED (no exception), so the subscriber commits the offset and the partition moves on
    await retry_over(sleep=sleeps, publisher=publisher).process(message(), EVENT_TYPE, work)

    assert work.calls == 3
    assert sleeps.seconds == [0.5, 1.0], "doubling, and no wait after the last attempt"
    [letter] = publisher.letters
    assert (letter.attempts, letter.consumer, letter.event_type) == (3, CONSUMER, EVENT_TYPE)
    assert (letter.source_topic, letter.key) == (TOPIC, b"correlation-key")
    assert letter.value == b'{"eventId":"original bytes"}'
    assert letter.error == "ValueError: poison on attempt 3", "the error of the FINAL attempt"


async def test_or1_the_backoff_doubles_each_time_it_neither_adds_the_base_nor_repeats_it() -> None:
    """Three attempts cannot tell doubling from adding the base (0.5, 1.0 either way): five can."""
    sleeps, work = Sleeps(), Work()

    await retry_over(policy=FactRetryPolicy(max_attempts=5, backoff_ms=500), sleep=sleeps).process(
        message(), EVENT_TYPE, work
    )

    assert work.calls == 5
    assert sleeps.seconds == [0.5, 1.0, 2.0, 4.0]


async def test_or1_a_retry_that_succeeds_publishes_no_dead_letter() -> None:
    sleeps, publisher, work = Sleeps(), Publisher(), Work(failures=1)

    await retry_over(sleep=sleeps, publisher=publisher).process(message(), EVENT_TYPE, work)

    assert work.calls == 2, "the first success returns; no third attempt"
    assert sleeps.seconds == [0.5]
    assert publisher.letters == []


async def test_or1_a_first_attempt_success_sleeps_never_and_publishes_nothing() -> None:
    sleeps, publisher, work = Sleeps(), Publisher(), Work(failures=0)

    await retry_over(sleep=sleeps, publisher=publisher).process(message(), EVENT_TYPE, work)

    assert work.calls == 1
    assert sleeps.seconds == []
    assert publisher.letters == []


async def test_or1_a_cancellation_during_work_is_neither_an_attempt_nor_a_dead_letter() -> None:
    sleeps, publisher = Sleeps(), Publisher()
    calls = 0

    async def cancelled_work() -> None:
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await retry_over(sleep=sleeps, publisher=publisher).process(
            message(), EVENT_TYPE, cancelled_work
        )

    assert calls == 1, "a cancelled attempt is not retried"
    assert sleeps.seconds == []
    assert publisher.letters == [], "a shutdown must never dead-letter a record"


async def test_or1_a_cancellation_during_the_backoff_is_neither_an_attempt_nor_a_dead_letter() -> (
    None
):
    sleeps, publisher, work = Sleeps(fail_with=asyncio.CancelledError()), Publisher(), Work()

    with pytest.raises(asyncio.CancelledError):
        await retry_over(sleep=sleeps, publisher=publisher).process(message(), EVENT_TYPE, work)

    assert work.calls == 1, "the cancelled back-off ended the loop: no second attempt"
    assert sleeps.seconds == [0.5]
    assert publisher.letters == []


async def test_or1_x_attempts_is_the_loops_own_count() -> None:
    """The policy is mutated while the loop runs (a stand-in for a settings reload): the answer is
    what the loop counted, never `policy.max_attempts` read at the end."""
    policy = FactRetryPolicy(max_attempts=3, backoff_ms=500)
    publisher = Publisher()

    def mutate(call: int) -> None:
        if call == 1:
            object.__setattr__(policy, "max_attempts", 9)

    work = Work(on_call=mutate)

    await retry_over(policy=policy, publisher=publisher).process(message(), EVENT_TYPE, work)

    assert policy.max_attempts == 9, "the fixture really changed the policy mid-loop"
    assert work.calls == 3
    [letter] = publisher.letters
    assert letter.attempts == 3


async def test_or1_the_header_instants_are_the_first_and_the_final_failure() -> None:
    clock, publisher = AdvancingClock(), Publisher()

    await retry_over(clock=clock, publisher=publisher).process(message(), EVENT_TYPE, Work())

    assert len(clock.readings) == 5, (
        "five readings: entry, one per failed attempt (3) and the end; the final failure's instant "
        f"is the reading taken in its own `except`, not one taken later: {clock.readings}"
    )
    entered, first_failure, second_failure, final_failure, _end = clock.readings
    [letter] = publisher.letters
    assert letter.first_failed_at == first_failure, "the FIRST attempt's failure, not the entry"
    assert letter.failed_at == final_failure, "the FINAL attempt's failure, not a later reading"
    distinct = {entered, first_failure, second_failure, final_failure, OCCURRED_AT}
    assert len(distinct) == 5, "the fixture's instants must be pairwise distinct"
    assert letter.first_failed_at != entered
    assert letter.first_failed_at != OCCURRED_AT
    assert letter.failed_at != letter.first_failed_at


async def test_or1_one_attempt_makes_the_two_instants_equal() -> None:
    clock, publisher, sleeps = AdvancingClock(), Publisher(), Sleeps()

    await retry_over(
        policy=FactRetryPolicy(max_attempts=1, backoff_ms=500),
        clock=clock,
        publisher=publisher,
        sleep=sleeps,
    ).process(message(), EVENT_TYPE, Work())

    assert len(clock.readings) == 3, (
        f"three readings: entry, the one failure, the end; the two instants are ONE reading "
        f"({clock.readings})"
    )
    entered, failure, _end = clock.readings
    [letter] = publisher.letters
    assert letter.attempts == 1
    assert letter.first_failed_at == letter.failed_at == failure != entered
    assert sleeps.seconds == [], "no wait after the only attempt"


async def test_or8_a_publication_that_raises_propagates() -> None:
    publisher = Publisher(fail_with=ConnectionError("the broker did not acknowledge"))
    work = Work()

    with pytest.raises(ConnectionError, match="the broker did not acknowledge") as raised:
        await retry_over(publisher=publisher).process(message(), EVENT_TYPE, work)

    assert work.calls == 3, "the attempts were all made before the publication was tried"
    assert isinstance(raised.value.__context__, ValueError), "the failure that led to it is chained"


async def test_or1_a_zero_attempt_policy_is_refused_not_silently_acknowledged() -> None:
    work = Work(failures=0)

    with pytest.raises(ValueError, match="max_attempts must be at least 1"):
        await retry_over(policy=FactRetryPolicy(max_attempts=0, backoff_ms=0)).process(
            message(), EVENT_TYPE, work
        )

    assert work.calls == 0


async def test_or1_a_zero_backoff_waits_zero_seconds_between_attempts() -> None:
    sleeps = Sleeps()

    await retry_over(policy=FactRetryPolicy(max_attempts=3, backoff_ms=0), sleep=sleeps).process(
        message(), EVENT_TYPE, Work()
    )

    assert sleeps.seconds == [0.0, 0.0]


async def test_f1_a_stop_that_ends_the_backoff_raises_stopped_and_is_neither_an_attempt_a_dead_letter_nor_a_latency() -> (
    None
):
    """The sleep raises `FactRetryStopped` (what `stop_aware_sleep` does when the signal ends the
    wait): `process` lets it out untouched, after ONE attempt, with nothing published."""
    publisher, latencies, work = Publisher(), Latencies(), Work()
    sleeps = Sleeps(fail_with=FactRetryStopped())

    with pytest.raises(FactRetryStopped):
        await retry_over(sleep=sleeps, publisher=publisher, latencies=latencies).process(
            message(), EVENT_TYPE, work
        )

    assert work.calls == 1, "the stop arrived during the first back-off: no second attempt"
    assert sleeps.seconds == [0.5]
    assert publisher.letters == [], "not dead-lettered"
    assert latencies.recorded == [], "not a processed record"


async def test_f1_stop_aware_sleep_waits_the_whole_time_when_nothing_stops_it() -> None:
    stop = asyncio.Event()

    started = asyncio.get_running_loop().time()
    await stop_aware_sleep(stop)(0.05)

    assert asyncio.get_running_loop().time() - started >= 0.045
    assert not stop.is_set()


async def test_f1_stop_aware_sleep_returns_within_a_small_bound_when_stop_is_set_during_a_long_wait() -> (
    None
):
    stop = asyncio.Event()
    sleeping = asyncio.ensure_future(stop_aware_sleep(stop)(30.0))
    await asyncio.sleep(0.05)  # it is waiting: not finished
    assert not sleeping.done()

    started = asyncio.get_running_loop().time()
    stop.set()
    with pytest.raises(FactRetryStopped):
        await asyncio.wait_for(sleeping, timeout=2.0)

    assert asyncio.get_running_loop().time() - started < 1.0, "ended by the signal, not the 30 s"


async def test_f1_stop_aware_sleep_with_the_signal_already_set_raises_at_once() -> None:
    stop = asyncio.Event()
    stop.set()

    with pytest.raises(FactRetryStopped):
        await asyncio.wait_for(stop_aware_sleep(stop)(30.0), timeout=1.0)


async def test_f1_an_external_cancellation_of_the_stop_aware_sleep_propagates_as_cancelled_error() -> (
    None
):
    """A `CancelledError` is not converted into `FactRetryStopped`: the task is cancelled, not
    asked to stop (ledger L10)."""
    sleeping = asyncio.ensure_future(stop_aware_sleep(asyncio.Event())(30.0))
    await asyncio.sleep(0.05)

    sleeping.cancel()

    with pytest.raises(asyncio.CancelledError):
        await sleeping
