"""`SagaCommandSweeper.run_once` and `SagaCommandSweeperTask.run` (8.7, 8.9, 8.11; L8, L12, L30).

A fake dispatcher whose `dispatch_claimed` is gated per row proves the batch is dispatched
CONCURRENTLY and that one row's failure does not cancel the rest.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

import pytest

from otc_orders.application.ports.saga_command_store import ClaimedCommand
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.infrastructure.saga.command_dispatcher import DispatchOutcome
from otc_orders.infrastructure.saga.sweeper import SagaCommandSweeper, SweepResult
from otc_orders.infrastructure.saga.sweeper_task import SagaCommandSweeperTask
from otc_shared_kernel import UniqueId


def make_row(n: int) -> ClaimedCommand:
    return ClaimedCommand(
        id=uuid.UUID(int=n + 100),
        order_id=UniqueId(uuid.UUID(int=n + 1)),
        order_reference=f"ORD-{n:06d}",
        kind=SagaCommandKind.STOCK_RESERVE,
        payload="{}",
        attempts=0,
        triggering_event_id=UniqueId(uuid.UUID(int=n + 200)),
    )


@dataclass
class FakeLedger:
    due: list[ClaimedCommand]
    batch_limits: list[int] = field(default_factory=list)

    async def claim_due(self, batch_limit: int) -> list[ClaimedCommand]:
        self.batch_limits.append(batch_limit)
        return self.due

    async def try_claim(self, *_args: object) -> ClaimedCommand | None:
        raise AssertionError("the sweeper never re-claims a row it already holds")


@dataclass
class FakeDispatcher:
    gates: dict[uuid.UUID, asyncio.Event] = field(default_factory=dict)
    failing: set[uuid.UUID] = field(default_factory=set)
    outcomes: dict[uuid.UUID, DispatchOutcome] = field(default_factory=dict)
    started: list[uuid.UUID] = field(default_factory=list)
    completed: list[uuid.UUID] = field(default_factory=list)

    async def dispatch_claimed(self, row: ClaimedCommand) -> DispatchOutcome:
        self.started.append(row.id)
        if row.id in self.gates:
            await self.gates[row.id].wait()
        if row.id in self.failing:
            raise RuntimeError(f"row {row.id} explodes")
        self.completed.append(row.id)
        return self.outcomes.get(row.id, DispatchOutcome.SENT)

    async def dispatch(self, *_args: object) -> DispatchOutcome:
        raise AssertionError("the sweeper must dispatch_claimed(row), never dispatch(order, kind)")


async def test_a_sweep_dispatches_its_claimed_rows_concurrently() -> None:
    a, b = make_row(1), make_row(2)
    dispatcher = FakeDispatcher(gates={a.id: asyncio.Event()})
    sweeper = SagaCommandSweeper(ledger=FakeLedger([a, b]), dispatcher=dispatcher, batch_limit=20)

    sweep = asyncio.create_task(sweeper.run_once())
    for _ in range(50):
        await asyncio.sleep(0)
        if b.id in dispatcher.completed:
            break

    assert b.id in dispatcher.completed, "row B finished while row A is still blocked"
    assert not sweep.done(), "run_once returns only after both rows finished"
    dispatcher.gates[a.id].set()
    result = await asyncio.wait_for(sweep, timeout=1)
    assert result == SweepResult(claimed=2, sent=2, parked=0, failed=0)
    assert set(dispatcher.completed) == {a.id, b.id}


async def test_the_sweeper_claims_with_its_batch_limit_and_reports_each_outcome() -> None:
    rows = [make_row(1), make_row(2), make_row(3)]
    ledger = FakeLedger(rows)
    dispatcher = FakeDispatcher(outcomes={rows[1].id: DispatchOutcome.PARKED})
    dispatcher.failing.add(rows[2].id)

    result = await SagaCommandSweeper(
        ledger=ledger, dispatcher=dispatcher, batch_limit=7
    ).run_once()

    assert ledger.batch_limits == [7]
    assert result == SweepResult(claimed=3, sent=1, parked=1, failed=1)


async def test_feature_42_a_rejected_dispatch_is_counted_as_rejected_only() -> None:
    rows = [make_row(1), make_row(2), make_row(3)]
    dispatcher = FakeDispatcher(
        outcomes={rows[0].id: DispatchOutcome.REJECTED, rows[1].id: DispatchOutcome.REJECTED}
    )

    result = await SagaCommandSweeper(
        ledger=FakeLedger(rows), dispatcher=dispatcher, batch_limit=7
    ).run_once()

    assert result == SweepResult(claimed=3, sent=1, parked=0, failed=0, rejected=2)


async def test_an_empty_sweep_dispatches_nothing() -> None:
    dispatcher = FakeDispatcher()

    result = await SagaCommandSweeper(
        ledger=FakeLedger([]), dispatcher=dispatcher, batch_limit=20
    ).run_once()

    assert result == SweepResult(0, 0, 0, 0)
    assert dispatcher.started == []


async def test_one_rows_failure_does_not_cancel_the_rest_of_the_sweep(
    caplog: pytest.LogCaptureFixture,
) -> None:
    a, b = make_row(1), make_row(2)
    release_b = asyncio.Event()
    dispatcher = FakeDispatcher(failing={a.id}, gates={b.id: release_b})
    sweeper = SagaCommandSweeper(ledger=FakeLedger([a, b]), dispatcher=dispatcher, batch_limit=20)

    with caplog.at_level(logging.ERROR):
        sweep = asyncio.create_task(sweeper.run_once())
        await asyncio.sleep(0.02)
        release_b.set()
        try:
            result = await asyncio.wait_for(sweep, timeout=1)
        except BaseException as escaped:
            pytest.fail(
                "row A's failure escaped the sweep and cancelled row B "
                f"(completed={dispatcher.completed}): {type(escaped).__name__}"
            )

    assert dispatcher.completed == [b.id], "row B reached its end although row A raised"
    assert result == SweepResult(claimed=2, sent=1, parked=0, failed=1)
    [error] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error.correlationId == str(a.order_id)  # type: ignore[attr-defined]
    assert error.command == "stock.reserve"  # type: ignore[attr-defined]


async def test_cancelling_a_sweep_cancels_its_rows_and_propagates() -> None:
    a = make_row(1)
    dispatcher = FakeDispatcher(gates={a.id: asyncio.Event()})
    sweep = asyncio.create_task(
        SagaCommandSweeper(ledger=FakeLedger([a]), dispatcher=dispatcher, batch_limit=1).run_once()
    )
    await asyncio.sleep(0.01)

    sweep.cancel()

    with pytest.raises(asyncio.CancelledError):
        await sweep


# ------------------------------------------------------------------------- the loop (8.9)

POLL = 0.01


class BlockingSweeper:
    def __init__(self) -> None:
        self.entered = 0
        self.in_cycle = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False

    async def run_once(self) -> object:
        self.entered += 1
        self.in_cycle.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return None


async def test_the_sweeper_task_never_starts_a_second_cycle_while_one_is_in_progress() -> None:
    sweeper = BlockingSweeper()
    stop = asyncio.Event()
    task = asyncio.create_task(
        SagaCommandSweeperTask(sweeper, interval=POLL, enabled=True).run(stop)
    )
    await asyncio.wait_for(sweeper.in_cycle.wait(), timeout=2)
    await asyncio.sleep(POLL * 10)  # well over three intervals pass while the cycle blocks

    assert sweeper.entered == 1, "a second cycle started while the first was still running"

    stop.set()
    sweeper.release.set()
    await asyncio.wait_for(task, timeout=2)
    assert sweeper.entered == 1


async def test_the_sweeper_task_stop_waits_for_the_in_flight_cycle_and_does_not_cancel_it() -> None:
    sweeper = BlockingSweeper()
    stop = asyncio.Event()
    task = asyncio.create_task(
        SagaCommandSweeperTask(sweeper, interval=POLL, enabled=True).run(stop)
    )
    await asyncio.wait_for(sweeper.in_cycle.wait(), timeout=2)

    stop.set()
    await asyncio.sleep(POLL * 10)
    assert not task.done(), "stop must wait for the in-flight cycle"
    assert not sweeper.cancelled

    sweeper.release.set()
    await asyncio.wait_for(task, timeout=2)
    assert not sweeper.cancelled


async def test_the_sweeper_task_survives_a_failed_cycle_and_runs_the_next(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailsOnce:
        def __init__(self) -> None:
            self.calls = 0
            self.second = asyncio.Event()

        async def run_once(self) -> object:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("the first cycle fails")
            self.second.set()
            return None

    sweeper = FailsOnce()
    stop = asyncio.Event()
    with caplog.at_level(logging.ERROR):
        task = asyncio.create_task(
            SagaCommandSweeperTask(sweeper, interval=POLL, enabled=True).run(stop)
        )
        try:
            await asyncio.wait_for(sweeper.second.wait(), timeout=2)
        except TimeoutError:
            pytest.fail(
                f"the loop ran no second cycle after the first failed (task done: {task.done()})"
            )
        stop.set()
        await asyncio.wait_for(task, timeout=2)

    assert sweeper.calls >= 2
    [error] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error.exc_info is not None


async def test_the_sweeper_task_propagates_cancellation() -> None:
    sweeper = BlockingSweeper()
    stop = asyncio.Event()
    task = asyncio.create_task(
        SagaCommandSweeperTask(sweeper, interval=POLL, enabled=True).run(stop)
    )
    await asyncio.wait_for(sweeper.in_cycle.wait(), timeout=2)

    try:
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        assert done, "cancellation was swallowed: the sweeper task is still running"
        with pytest.raises(asyncio.CancelledError):
            task.result()
        assert sweeper.cancelled
    finally:
        stop.set()  # lets a task that swallowed the cancellation end, so a failure cannot hang


async def test_a_disabled_sweeper_task_returns_at_once_without_a_cycle() -> None:
    sweeper = BlockingSweeper()

    await asyncio.wait_for(
        SagaCommandSweeperTask(sweeper, interval=POLL, enabled=False).run(asyncio.Event()),
        timeout=1,
    )

    assert sweeper.entered == 0
