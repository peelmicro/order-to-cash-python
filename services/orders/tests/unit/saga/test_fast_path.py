# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""`SagaFastPath`: one task per command, no head-of-line blocking, a bounded in-flight count (6.2-6.7, 6.10).

The dispatcher is a fake whose `dispatch` is gated per order, so "returns before the RPC completes",
"another order is not delayed" and "cancelled on stop" are observations of what the tasks DID, with
every wait on an `asyncio.Event` or a bounded `wait_for`.
"""

import asyncio
import contextvars
import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import pytest

from otc_orders.application.ports.saga_signal import SagaCommandRef
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.infrastructure.saga.command_dispatcher import DispatchOutcome
from otc_orders.infrastructure.saga.fast_path import SagaFastPath
from otc_shared_kernel import UniqueId

ORDER_A = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000a1"))
ORDER_B = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000b2"))
ORDER_C = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000c3"))
KIND = SagaCommandKind.STOCK_RESERVE


@dataclass
class FakeDispatcher:
    behaviour: Callable[[UniqueId, SagaCommandKind], Awaitable[DispatchOutcome]]
    started: list[UniqueId] = field(default_factory=list)
    completed: list[UniqueId] = field(default_factory=list)
    completions: asyncio.Queue[UniqueId] = field(default_factory=asyncio.Queue)

    async def dispatch(self, order_id: UniqueId, kind: SagaCommandKind) -> DispatchOutcome:
        self.started.append(order_id)
        outcome = await self.behaviour(order_id, kind)
        self.completed.append(order_id)
        self.completions.put_nowait(order_id)
        return outcome


async def finishes(_order: UniqueId, _kind: SagaCommandKind) -> DispatchOutcome:
    return DispatchOutcome.SENT


async def run_fast_path(fast_path: SagaFastPath) -> tuple[asyncio.Task[None], asyncio.Event]:
    stop = asyncio.Event()
    task = asyncio.create_task(fast_path.run(stop))
    await asyncio.sleep(0)  # the task reaches its `stop.wait()` with the group open
    return task, stop


async def next_completion(dispatcher: FakeDispatcher, claim: str) -> UniqueId:
    """The next dispatch to finish, or a failure that NAMES the claim being checked."""
    try:
        async with asyncio.timeout(1):
            return await dispatcher.completions.get()
    except TimeoutError:
        pytest.fail(
            f"{claim} (started={dispatcher.started}, completed={dispatcher.completed}, "
            "no dispatch finished within 1 s)"
        )


async def stop_and_await(task: asyncio.Task[None], stop: asyncio.Event) -> None:
    stop.set()
    await asyncio.wait_for(task, timeout=1)


async def test_so10_signalling_returns_before_the_rpc_issue_completes() -> None:
    gate = asyncio.Event()

    async def gated(_order: UniqueId, _kind: SagaCommandKind) -> DispatchOutcome:
        await gate.wait()
        return DispatchOutcome.SENT

    dispatcher = FakeDispatcher(gated)
    fast_path = SagaFastPath(dispatcher=dispatcher, max_in_flight=8)
    task, stop = await run_fast_path(fast_path)

    assert not inspect.iscoroutinefunction(fast_path.signal), (
        "signal must be a plain function: an awaited signal puts the RPC on the caller's path"
    )
    fast_path.signal(SagaCommandRef(ORDER_A, KIND))  # synchronous: no await

    assert dispatcher.completed == [], "signal returned while the gate is still closed"
    gate.set()
    await next_completion(dispatcher, "the gated dispatch did not complete once released (SO10)")
    assert dispatcher.completed == [ORDER_A]
    await stop_and_await(task, stop)


async def test_so13_a_dispatch_that_never_finishes_does_not_delay_another_orders_command() -> None:
    forever = asyncio.Event()

    async def a_never_finishes(order: UniqueId, _kind: SagaCommandKind) -> DispatchOutcome:
        if order == ORDER_A:
            await forever.wait()
        return DispatchOutcome.SENT

    dispatcher = FakeDispatcher(a_never_finishes)
    fast_path = SagaFastPath(dispatcher=dispatcher, max_in_flight=8)
    task, stop = await run_fast_path(fast_path)

    fast_path.signal(SagaCommandRef(ORDER_A, KIND))
    fast_path.signal(SagaCommandRef(ORDER_B, KIND))

    try:
        async with asyncio.timeout(0.1):
            await dispatcher.completions.get()
    except TimeoutError:
        pytest.fail(
            "order B's command was delayed behind order A's dispatch, which never finishes: "
            f"started={dispatcher.started}, completed={dispatcher.completed} (bound 100 ms)"
        )
    assert dispatcher.completed == [ORDER_B]
    assert fast_path.in_flight == 1, "only A is still in flight"
    await stop_and_await(task, stop)


async def test_so13_a_signal_beyond_the_in_flight_maximum_returns_at_once_and_leaves_the_row_to_the_sweeper(
    caplog: pytest.LogCaptureFixture,
) -> None:
    forever = asyncio.Event()

    async def blocks(_order: UniqueId, _kind: SagaCommandKind) -> DispatchOutcome:
        await forever.wait()
        return DispatchOutcome.SENT

    dispatcher = FakeDispatcher(blocks)
    fast_path = SagaFastPath(dispatcher=dispatcher, max_in_flight=1)
    task, stop = await run_fast_path(fast_path)
    fast_path.signal(SagaCommandRef(ORDER_A, KIND))
    await asyncio.sleep(0)
    assert fast_path.in_flight == 1

    with caplog.at_level(logging.WARNING):
        loop = asyncio.get_running_loop()
        before = loop.time()
        fast_path.signal(SagaCommandRef(ORDER_B, SagaCommandKind.CREDIT_HOLD))
        elapsed = loop.time() - before
        await asyncio.sleep(0.02)

    assert elapsed < 0.01, f"the overflowing signal waited {elapsed:.4f}s instead of returning"
    assert dispatcher.started == [ORDER_A], "B is never dispatched by the fast path"
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning.correlationId == str(ORDER_B)  # type: ignore[attr-defined]
    assert warning.command == "credit.hold"  # type: ignore[attr-defined]
    assert "sweeper" in warning.getMessage()
    await stop_and_await(task, stop)


async def test_a_slot_is_freed_when_a_dispatch_completes() -> None:
    fast_path = SagaFastPath(dispatcher=FakeDispatcher(finishes), max_in_flight=1)
    task, stop = await run_fast_path(fast_path)

    fast_path.signal(SagaCommandRef(ORDER_A, KIND))
    await asyncio.sleep(0.01)
    assert fast_path.in_flight == 0
    fast_path.signal(SagaCommandRef(ORDER_B, KIND))
    await asyncio.sleep(0.01)

    assert fast_path.in_flight == 0
    await stop_and_await(task, stop)


async def test_so14_the_dispatch_runs_in_the_context_of_the_fact_handling_that_owed_it() -> None:
    correlation: contextvars.ContextVar[str] = contextvars.ContextVar("correlation", default="none")
    seen: dict[str, str] = {}
    entered = asyncio.Event()

    async def reads_context(order: UniqueId, _kind: SagaCommandKind) -> DispatchOutcome:
        await asyncio.sleep(0.01)  # a value set AFTER signal() returned would be visible by now
        seen[str(order)] = correlation.get()
        entered.set()
        return DispatchOutcome.SENT

    fast_path = SagaFastPath(dispatcher=FakeDispatcher(reads_context), max_in_flight=8)
    task, stop = await run_fast_path(fast_path)

    correlation.set("set before signal")
    fast_path.signal(SagaCommandRef(ORDER_A, KIND))
    correlation.set("set after signal")
    await asyncio.wait_for(entered.wait(), timeout=1)

    assert seen == {str(ORDER_A): "set before signal"}
    await stop_and_await(task, stop)


async def test_a_dispatch_that_raises_neither_cancels_its_siblings_nor_stops_the_fast_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    release_b = asyncio.Event()

    async def behaviour(order: UniqueId, _kind: SagaCommandKind) -> DispatchOutcome:
        if order == ORDER_A:
            raise RuntimeError("dispatch A explodes")
        if order == ORDER_B:
            await release_b.wait()
        return DispatchOutcome.SENT

    dispatcher = FakeDispatcher(behaviour)
    fast_path = SagaFastPath(dispatcher=dispatcher, max_in_flight=8)
    task, stop = await run_fast_path(fast_path)
    fast_path.signal(SagaCommandRef(ORDER_B, KIND))  # in flight, blocked
    await asyncio.sleep(0)

    with caplog.at_level(logging.ERROR):
        fast_path.signal(SagaCommandRef(ORDER_A, KIND))  # raises
        await asyncio.sleep(0.02)
        release_b.set()
        await next_completion(
            dispatcher, "sibling B did not complete after A raised: A's failure cancelled it"
        )
        fast_path.signal(SagaCommandRef(ORDER_C, KIND))  # a later signal is still dispatched
        await next_completion(
            dispatcher, "a signal after A's failure was not dispatched: the fast path stopped"
        )

    assert dispatcher.completed == [ORDER_B, ORDER_C], "B survived A's failure and C ran after it"
    assert not task.done(), "the fast path is still running"
    [error] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error.correlationId == str(ORDER_A)  # type: ignore[attr-defined]
    assert error.exc_info is not None
    await stop_and_await(task, stop)


async def test_stopping_the_fast_path_cancels_in_flight_dispatches_and_run_returns() -> None:
    observed: list[str] = []
    entered = asyncio.Event()

    async def blocks(_order: UniqueId, _kind: SagaCommandKind) -> DispatchOutcome:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            observed.append("cancelled")
            raise
        return DispatchOutcome.SENT

    fast_path = SagaFastPath(dispatcher=FakeDispatcher(blocks), max_in_flight=8)
    task, stop = await run_fast_path(fast_path)
    fast_path.signal(SagaCommandRef(ORDER_A, KIND))
    await asyncio.wait_for(entered.wait(), timeout=1)
    [child] = [t for t in asyncio.all_tasks() if t.get_name().startswith("saga-fast-path ")]

    stop.set()
    await asyncio.wait_for(task, timeout=1)

    assert observed == ["cancelled"], "the dispatch observed CancelledError"
    assert child.cancelled(), (
        "the child ended CANCELLED: the cancellation was propagated, not swallowed"
    )
    assert task.exception() is None


async def test_a_signal_before_start_or_after_stop_is_dropped_and_never_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dispatcher = FakeDispatcher(finishes)
    fast_path = SagaFastPath(dispatcher=dispatcher, max_in_flight=8)

    with caplog.at_level(logging.WARNING):
        fast_path.signal(SagaCommandRef(ORDER_A, KIND))  # before run() started
        task, stop = await run_fast_path(fast_path)
        await stop_and_await(task, stop)
        fast_path.signal(SagaCommandRef(ORDER_B, KIND))  # after run() ended
        await asyncio.sleep(0.01)

    assert dispatcher.started == []
    assert [r.correlationId for r in caplog.records] == [str(ORDER_A), str(ORDER_B)]  # type: ignore[attr-defined]


async def test_cancelling_run_cancels_the_children_and_propagates() -> None:
    entered = asyncio.Event()
    cancelled: list[bool] = []

    async def blocks(_order: UniqueId, _kind: SagaCommandKind) -> DispatchOutcome:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        return DispatchOutcome.SENT

    fast_path = SagaFastPath(dispatcher=FakeDispatcher(blocks), max_in_flight=8)
    task, _stop = await run_fast_path(fast_path)
    fast_path.signal(SagaCommandRef(ORDER_A, KIND))
    await asyncio.wait_for(entered.wait(), timeout=1)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled == [True]
