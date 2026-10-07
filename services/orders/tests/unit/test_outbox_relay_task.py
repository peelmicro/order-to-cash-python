"""The relay loop (feature 14, 5.2-5.5; OI6, L8, L18-L20): no broker, no database.

The fake `run_once` is controllable. Intervals are tens of milliseconds and every wait is on an
`asyncio.Event` or a bounded `wait_for`, never on a bare sleep that the assertion depends on to be
long enough. Loop scope: default (function); every task is awaited or cancelled-and-awaited here.
"""

import asyncio
import logging

import pytest

from otc_orders.infrastructure.outbox.relay import RelayResult
from otc_orders.infrastructure.outbox.relay_task import OutboxRelayTask

POLL = 0.01
NOTHING = RelayResult(claimed=0, published=0, poisoned=None)


class BlockingRelay:
    """`run_once` blocks until released; counts entries and whether a cycle was ever cancelled."""

    def __init__(self) -> None:
        self.entered = 0
        self.cancelled = False
        self.in_cycle = asyncio.Event()
        self.release = asyncio.Event()

    async def run_once(self) -> RelayResult:
        self.entered += 1
        self.in_cycle.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return NOTHING


async def test_oi6_never_starts_a_second_cycle_while_one_is_in_progress() -> None:
    relay = BlockingRelay()
    stop = asyncio.Event()
    task = asyncio.create_task(OutboxRelayTask(relay, poll_interval=POLL, enabled=True).run(stop))
    await asyncio.wait_for(relay.in_cycle.wait(), timeout=2)
    await asyncio.sleep(POLL * 10)  # well over three poll intervals pass while the cycle blocks
    assert relay.entered == 1, "a second cycle started while the first was still running"
    stop.set()
    relay.release.set()
    await asyncio.wait_for(task, timeout=2)
    assert relay.entered == 1


async def test_oi6_stop_waits_for_the_in_flight_cycle() -> None:
    relay = BlockingRelay()
    stop = asyncio.Event()
    task = asyncio.create_task(OutboxRelayTask(relay, poll_interval=POLL, enabled=True).run(stop))
    await asyncio.wait_for(relay.in_cycle.wait(), timeout=2)
    stop.set()
    await asyncio.sleep(POLL * 10)
    assert not task.done(), "stop() must wait for the in-flight cycle"
    assert not relay.cancelled, "a normal stop must not cancel a cycle mid-publish"
    relay.release.set()
    await asyncio.wait_for(task, timeout=2)
    assert task.done()
    assert not relay.cancelled


class FailsOnce:
    def __init__(self) -> None:
        self.calls = 0
        self.second_call = asyncio.Event()

    async def run_once(self) -> RelayResult:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("the first cycle fails")
        self.second_call.set()
        return NOTHING


async def test_relay_task_survives_a_failed_cycle_and_runs_the_next(
    caplog: pytest.LogCaptureFixture,
) -> None:
    relay = FailsOnce()
    stop = asyncio.Event()
    with caplog.at_level(logging.ERROR):
        task = asyncio.create_task(
            OutboxRelayTask(relay, poll_interval=POLL, enabled=True).run(stop)
        )
        await asyncio.wait_for(relay.second_call.wait(), timeout=2)
        stop.set()
        await asyncio.wait_for(task, timeout=2)
    assert relay.calls >= 2
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None
    assert errors[0].exc_info[0] is RuntimeError


async def test_relay_task_propagates_cancellation() -> None:
    relay = BlockingRelay()
    stop = asyncio.Event()
    task = asyncio.create_task(OutboxRelayTask(relay, poll_interval=POLL, enabled=True).run(stop))
    await asyncio.wait_for(relay.in_cycle.wait(), timeout=2)
    try:
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        assert task in done, "the cancellation was swallowed: the loop is still running"
        assert task.cancelled() is True
        assert relay.cancelled, "the cancellation reached the in-flight cycle"
    finally:  # never leave the loop running when the assertion above fails
        stop.set()
        relay.release.set()
        await asyncio.wait({task}, timeout=2)


class Instant:
    """A non-blocking `run_once`: returns at once, counts entries."""

    def __init__(self) -> None:
        self.entered = 0
        self.first = asyncio.Event()

    async def run_once(self) -> RelayResult:
        self.entered += 1
        self.first.set()
        return NOTHING


async def test_relay_task_propagates_a_cancellation_that_arrives_during_the_inter_cycle_sleep() -> (
    None
):
    relay = Instant()
    stop = asyncio.Event()
    task = asyncio.create_task(OutboxRelayTask(relay, poll_interval=10, enabled=True).run(stop))
    try:
        await asyncio.wait_for(relay.first.wait(), timeout=2)
        await asyncio.sleep(0.05)  # the loop is now parked in the 10 s inter-cycle wait
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        assert task in done, "the cancellation was swallowed during the sleep: the loop polls on"
        assert task.cancelled() is True
        assert relay.entered == 1
    finally:
        stop.set()
        await asyncio.wait({task}, timeout=2)


async def test_relay_task_waits_the_poll_interval_between_cycles_and_stop_cuts_the_wait_short() -> (
    None
):
    relay = Instant()
    stop = asyncio.Event()
    task = asyncio.create_task(OutboxRelayTask(relay, poll_interval=10, enabled=True).run(stop))
    try:
        await asyncio.wait_for(relay.first.wait(), timeout=2)
        await asyncio.sleep(0.2)
        assert relay.entered == 1, "a second cycle ran inside the poll interval: no pacing"
        stop.set()
        done, _ = await asyncio.wait({task}, timeout=2)
        assert task in done, "stop did not end the wait: the sleep is not interruptible"
        assert relay.entered == 1
    finally:
        stop.set()
        await asyncio.wait({task}, timeout=2)


async def test_a_disabled_relay_task_returns_without_calling_run_once() -> None:
    relay = BlockingRelay()
    await asyncio.wait_for(
        OutboxRelayTask(relay, poll_interval=POLL, enabled=False).run(asyncio.Event()), timeout=2
    )
    assert relay.entered == 0
