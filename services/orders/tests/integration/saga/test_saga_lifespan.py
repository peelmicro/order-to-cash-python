# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""The three saga tasks the lifespan owns: they start, a dead one takes readiness down (named), and
shutdown cancels a blocked dispatch, leaves its row leased and leaves nothing unawaited (12.4).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]
SAGA_TASKS = ("saga-fast-path", "saga-sweeper", "saga-consumer")


async def readiness(app: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health/ready")


async def test_the_three_saga_tasks_start_beside_the_responder_and_the_relay(
    saga_harness: Any,
) -> None:
    async with saga_harness() as saga:
        tasks = dict(saga.runtime.tasks)

        assert set(tasks) == {"nats-responder", "outbox-relay", *SAGA_TASKS}
        assert all(not task.done() for task in tasks.values())
        response = await readiness(saga.app)
        assert (response.status_code, response.json()) == (200, {"status": "ready"})
    assert all(task.done() and not task.cancelled() for task in tasks.values()), (
        "the lifespan awaited every task it created"
    )
    assert [task.exception() for task in tasks.values()] == [None] * len(tasks)


@pytest.mark.parametrize("task_name", SAGA_TASKS)
async def test_a_saga_task_that_ends_unexpectedly_takes_readiness_down_and_names_it(
    saga_harness: Any, task_name: str
) -> None:
    async with saga_harness() as saga:
        assert (await readiness(saga.app)).status_code == 200
        victim = saga.runtime.tasks[task_name]
        survivors = [t for name, t in saga.runtime.tasks.items() if name != task_name]

        victim.cancel()
        await asyncio.wait({victim}, timeout=10)

        response = await readiness(saga.app)
        assert response.status_code == 503
        assert response.json() == {
            "status": "unready",
            "reasons": [f"transport task {task_name} is not running"],
        }
        assert all(not t.done() for t in survivors), "only the dead task is named"


async def test_a_sweeper_disabled_process_has_no_sweeper_task_and_still_issues_commands(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness(SAGA_SWEEPER_ENABLED="false") as saga:
        assert "saga-sweeper" not in saga.runtime.tasks
        await saga.publish_fact(
            "order.placed.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RESERVE)
            return row is not None and row["status"] == "sent"

        await waits(sent, "the fast path issues the command with no sweeper running")


async def test_a_consumer_disabled_process_runs_the_fast_path_and_the_sweeper_but_consumes_no_facts(
    saga_harness: Any, broker: Any, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        async with saga_harness(SAGA_CONSUMER_ENABLED="false") as saga:
            assert set(saga.runtime.tasks) == {
                "nats-responder",
                "outbox-relay",
                "saga-fast-path",
                "saga-sweeper",
            }
            assert (await readiness(saga.app)).status_code == 200
    assert any("SAGA_CONSUMER_ENABLED=false" in r.getMessage() for r in caplog.records), (
        "the boot logs a WARNING naming the setting"
    )


async def test_shutdown_with_a_dispatch_blocked_in_a_stand_in_completes_within_the_bound_and_leaves_the_row_leased(
    saga_harness: Any,
    order_at: OrderAt,
    waits: Waits,
    caplog: pytest.LogCaptureFixture,
) -> None:
    order = await order_at(OrderStatus.PLACED)
    with caplog.at_level(logging.WARNING):
        context = saga_harness(
            SAGA_COMMAND_TIMEOUT_MS="5000",
            SAGA_COMMAND_LEASE_MS="60000",
            SAGA_SWEEPER_ENABLED="false",
        )
        saga = await context.__aenter__()
        stand_in = saga.stand_in(SagaCommandKind.STOCK_RESERVE)
        stand_in.behaviour = saga.behaviours["silent"]
        await saga.publish_fact(
            "order.placed.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def in_flight() -> bool:
            return bool(stand_in.requests_for(order.id.value))

        await waits(in_flight, "the dispatch is blocked inside the stand-in (it never answers)")

        started = time.monotonic()
        await context.__aexit__(None, None, None)
        elapsed = time.monotonic() - started

    assert elapsed < 4, f"shutdown took {elapsed:.1f}s with a 5 s attempt in flight: it waited"
    [row] = await saga.db.command_rows(order.id)
    assert row["status"] == "pending", "neither sent nor parked: the dispatch was cancelled"
    assert row["next_attempt_at"] is not None, (
        "the row is still leased: the sweeper re-issues it later"
    )
    assert row["attempts"] == 0
    assert [r for r in caplog.records if r.name.endswith("command_dispatcher")] == [], (
        "a dispatch cancelled by a clean shutdown must not fail an attempt: the NATS client was "
        "closed under it, before the fast path was awaited"
    )
    assert [r for r in caplog.records if "was destroyed" in r.getMessage()] == []
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == [], [
        r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR
    ]


async def test_the_nats_client_is_closed_only_after_every_task_was_awaited(
    saga_harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every task uses NATS or the engine; the lifespan awaits them all BEFORE closing either."""
    from nats.aio.client import Client

    observed: list[tuple[str, list[str]]] = []
    holder: dict[str, Any] = {}

    def spy(name: str) -> Callable[..., Awaitable[None]]:
        original = getattr(Client, name)

        async def wrapper(self: Client, *args: Any, **kwargs: Any) -> None:
            if "tasks" in holder:
                running = [n for n, t in holder["tasks"].items() if not t.done()]
                observed.append((name, running))
            await original(self, *args, **kwargs)

        return wrapper

    monkeypatch.setattr(Client, "close", spy("close"))
    monkeypatch.setattr(Client, "drain", spy("drain"))
    async with saga_harness() as saga:
        holder["tasks"] = dict(saga.runtime.tasks)

    assert observed, "the client was closed or drained at shutdown"
    for call, still_running in observed:
        assert still_running == [], (
            f"NATS was {call}ed while tasks {still_running} were still running: close came first"
        )
