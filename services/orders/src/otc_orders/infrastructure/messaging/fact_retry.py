"""`FactRetry`: retry a fact's processing, then dead-letter it (`R16`, `OR1`, `OR8`).

Canonical in Orders; copied to the Projector and Notifications (`OR2`,
`tests/architecture/test_observability_copy_parity.py` fails on any difference after this
docstring, so edit here and copy). Design: `specs/observability_reliability/design.md` 5.3.

`process(message, event_type, work)` runs `work()` up to `policy.max_attempts` times, waiting
`backoff_ms`, then twice that, then four times... between attempts. The first success returns. When
the last attempt fails, the record is handed to the dead-letter publisher and the call RETURNS, so
the subscriber commits the offset and the partition moves on.

* `x-attempts` is the loop's own count and the policy is read once, before the loop, so a policy
  that changes under the loop cannot change an answer already given (#8 L19).
* `first_failed_at` is read inside the first `except`, never at entry (`SA-3`; #7 stamped the entry
  instant and #8 id 75 inherited the mistake), and `failed_at` is the final failure's own reading,
  taken in the `except` too, not after the loop.
* `asyncio.CancelledError` is a `BaseException`, so `except Exception` never catches it: a shutdown
  during `work()` or during the back-off propagates, is never counted as an attempt and never
  dead-lettered. There is no `except BaseException` and no bare `except:` here, on purpose.
* A SHUTDOWN during a back-off ends the wait: the composition hands `sleep` the consumer's stop
  signal (`stop_aware_sleep`), which raises `FactRetryStopped` when the signal ends the wait. That
  is not an attempt, not a dead letter and not a handler failure: nothing is committed, the
  exception leaves `process` untouched and the subscriber (which names it) ends the loop, so the
  record is redelivered after the restart for a fresh round of attempts. A `CancelledError` is not
  converted: it propagates as before.
* If the dead-letter publication raises, the exception PROPAGATES (`OR8`): the subscriber does not
  commit, seeks back and delivers the record again, and the record gets another full round of
  attempts. A dead letter that is not durable is therefore never a lost record.
* The latency (`FactLatency`, milliseconds as a float exact to the microsecond) is measured with
  the injected clock, on success and on the dead-letter path, from the entry instant to the end.

The module names only ports (a clock, a publisher, a latency recorder) and imports no Kafka client,
so the presentation task may hold it (the `fact-producer-confinement` contract).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from otc_orders.application.ports.fact_stream import FactMessage

log = logging.getLogger("otc_orders.messaging.fact_retry")


class FactRetryStopped(Exception):
    """The consumer's stop signal ended a back-off wait. NOT a handler failure: the record was
    neither committed nor dead-lettered, and it is redelivered after the restart."""


def stop_aware_sleep(stop: asyncio.Event) -> Callable[[float], Awaitable[None]]:
    """A back-off wait the stop signal ends: returns after `seconds`, or raises `FactRetryStopped`
    as soon as `stop` is set (also when it already was). An external cancellation is not caught."""

    async def sleep(seconds: float) -> None:
        try:
            async with asyncio.timeout(seconds):
                await stop.wait()
        except TimeoutError:
            return
        raise FactRetryStopped

    return sleep


@dataclass(frozen=True, slots=True)
class FactRetryPolicy:
    max_attempts: int
    backoff_ms: int


@dataclass(frozen=True, slots=True)
class DeadLetter:
    """Everything a dead-letter record carries besides the trace: the ORIGINAL bytes are `value`,
    never a re-serialised envelope."""

    source_topic: str
    key: bytes | None
    value: bytes
    consumer: str
    attempts: int
    error: str
    first_failed_at: datetime
    failed_at: datetime
    event_type: str


class FactClock(Protocol):
    def now(self) -> datetime: ...


class DeadLetterPublisher(Protocol):
    async def publish(self, letter: DeadLetter) -> None:
        """Return only once the broker has acknowledged the record; raise otherwise."""
        ...


class FactLatency(Protocol):
    def record(self, milliseconds: float, consumer: str) -> None: ...


class NoFactLatency:
    """The recorder of a runtime that exports no latency."""

    def record(self, milliseconds: float, consumer: str) -> None:
        return None


class FactRetry:
    def __init__(
        self,
        *,
        consumer: str,
        policy: FactRetryPolicy,
        clock: FactClock,
        sleep: Callable[[float], Awaitable[None]],
        dead_letters: DeadLetterPublisher,
        latency: FactLatency,
    ) -> None:
        self._consumer = consumer
        self._policy = policy
        self._clock = clock
        self._sleep = sleep
        self._dead_letters = dead_letters
        self._latency = latency

    async def process(
        self, message: FactMessage, event_type: str, work: Callable[[], Awaitable[None]]
    ) -> None:
        max_attempts = self._policy.max_attempts
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")
        entered = self._clock.now()
        first_failed_at: datetime | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                await work()
            except Exception as error:
                failed_at = self._clock.now()
                if first_failed_at is None:
                    first_failed_at = failed_at
                log.warning(
                    "fact processing attempt failed",
                    extra={
                        "attempt": attempt,
                        "maxAttempts": max_attempts,
                        "eventType": event_type,
                        "error": f"{type(error).__name__}: {error}",
                    },
                )
                if attempt < max_attempts:
                    await self._sleep(self._policy.backoff_ms * (1 << (attempt - 1)) / 1000)
                    continue
                await self._dead_letters.publish(
                    DeadLetter(
                        source_topic=message.topic,
                        key=message.key,
                        value=message.value,
                        consumer=self._consumer,
                        attempts=attempt,
                        error=f"{type(error).__name__}: {error}",
                        first_failed_at=first_failed_at,
                        failed_at=failed_at,
                        event_type=event_type,
                    )
                )
                log.error(
                    "fact dead-lettered after exhausting its attempts",
                    extra={
                        "topic": message.topic,
                        "partition": message.partition,
                        "offset": message.offset,
                        "eventType": event_type,
                        "attempts": attempt,
                    },
                )
                self._record_latency(entered)
                return
            self._record_latency(entered)
            return

    def _record_latency(self, entered: datetime) -> None:
        self._latency.record(
            (self._clock.now() - entered) / timedelta(milliseconds=1), self._consumer
        )
