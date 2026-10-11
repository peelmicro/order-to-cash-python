"""H6 (PR45, PR50, PR51): the runtime against the real Mongo, Kafka and NATS.

Restart models (design 11.2): the two-loop case and `test_pr51_a_rebuilt_runtime...` are the
IN-PROCESS REBUILD (a new runtime: new clients, new consumer, same group and database); the process
restart is the live walkthrough. Every wait is bounded and its failure names the claim.
"""

import asyncio
import time
import uuid
from typing import Any

import httpx
import pytest
from testcontainers.core.container import DockerContainer

import otc_projector.application
from otc_cqrs import HandlerRegistry
from otc_projector.application.handlers import ProjectFactHandler
from otc_projector.application.messages import ProjectFactCommand
from otc_projector.application.outcome import ProjectionOutcome
from otc_projector.application.scope import ProjectorScope
from otc_projector.composition import Externals, Wiring
from otc_projector.presentation.app import create_app

pytestmark = pytest.mark.integration

NATS_IMAGE = "nats:2.14.5-alpine"  # the compose pin


def leftover_tasks() -> set[asyncio.Task[Any]]:
    return {t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()}


def test_the_runtime_starts_and_stops_in_two_successive_event_loops(endpoints: Any) -> None:
    """Ledger L29 / L49: the Mongo client, the NATS connection and the consumer are created in the
    loop that runs the lifespan and closed in it; a second `asyncio.run` builds them anew."""

    async def once(group: str) -> list[str]:
        runtime = await endpoints.start(group)
        try:
            reasons: list[str] = runtime.unready_reasons()
            return reasons
        finally:
            await runtime.stop()

    assert asyncio.run(once("two-loops-a")) == []
    assert asyncio.run(once("two-loops-b")) == []


async def test_pr45_an_unreachable_nats_fails_the_boot_within_the_bound(runtime_env: Any) -> None:
    # A Docker-held port with nothing listening behind it (the nats image, its entrypoint
    # replaced): the proxy accepts the connection and drops it, as an unreachable broker does.
    container = (
        DockerContainer(NATS_IMAGE)
        .with_exposed_ports(4222)
        .with_kwargs(entrypoint=["sleep", "120"])
    )
    with container:
        port = container.get_exposed_port(4222)
        host = container.get_container_host_ip()
        before = leftover_tasks()
        started = time.monotonic()

        async def boot() -> None:
            try:
                async with asyncio.timeout(20):
                    await runtime_env.start_with(
                        "unreachable-nats", nats=f"nats://{host}:{port}", nats_connect_seconds=2.0
                    )
            except TimeoutError:
                pytest.fail("PR45: the boot did not fail within 20 s against a 2 s bound")

        with pytest.raises(RuntimeError) as refused:
            await boot()
        elapsed = time.monotonic() - started
    assert elapsed < 5.0, f"the boot took {elapsed:.1f} s against a 2 s bound"
    assert "NATS_URL" in str(refused.value)
    assert leftover_tasks() == before, "a task was left behind by the failed boot"


async def test_pr50_readiness_drops_when_the_consumer_task_dies(runtime_env: Any) -> None:
    runtime = await runtime_env.start("readiness")
    app = create_app()
    app.state.runtime = runtime
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        before = await client.get("/health/ready")
        assert before.status_code == 200, before.text
        task = runtime.tasks["fact-consumer"]
        task.cancel()
        try:
            async with asyncio.timeout(10):
                await asyncio.gather(task, return_exceptions=True)
        except TimeoutError:
            pytest.fail("PR50: the cancelled consumer task did not end within 10 s")
        after = await client.get("/health/ready")
    assert after.status_code == 503
    assert "transport task fact-consumer is not running" in after.json()["reasons"]
    await runtime.stop()


async def test_pr50_shutdown_cancels_a_stuck_handler_after_the_grace(
    runtime_env: Any, produce: Any, facts: Any, new_reference: Any
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()  # never set: the handler is stuck

    class Stuck:
        def __init__(self, scope: ProjectorScope) -> None:
            self._scope = scope

        async def handle(self, command: ProjectFactCommand, /) -> ProjectionOutcome:
            started.set()
            await release.wait()
            return ProjectionOutcome.PROCESSED

    def wire() -> Wiring:
        registry = HandlerRegistry[ProjectorScope]()
        registry.register_command(ProjectFactCommand, Stuck)
        return registry.build(otc_projector.application), registry.registered_factories()

    runtime = await runtime_env.start(
        "stuck-handler", externals=Externals(wire=wire), stop_grace_seconds=1.0
    )
    await produce([facts.build("order.placed.v1", payload={"order_reference": new_reference()})])
    try:
        async with asyncio.timeout(30):
            await started.wait()
    except TimeoutError:
        pytest.fail("PR50: the stuck handler was never invoked within 30 s")
    task = runtime.tasks["fact-consumer"]
    begun = time.monotonic()
    try:
        async with asyncio.timeout(15):
            await runtime.stop()
    except TimeoutError:
        pytest.fail(
            "PR50: stop() did not return within 15 s: the stuck handler was never cancelled"
        )
    elapsed = time.monotonic() - begun
    assert elapsed < 5.0, f"stop() took {elapsed:.1f} s with a 1 s grace"
    assert task.done()
    assert task.cancelled(), "the stuck consumer task was not cancelled after the grace"
    release.set()


async def test_pr51_a_rebuilt_runtime_suppresses_every_applied_fact(
    runtime_env: Any, produce: Any, facts: Any, new_reference: Any
) -> None:
    """IN-PROCESS REBUILD (design 11.2a): runtime A applies the facts and stops; runtime B (new
    clients, new consumer, SAME group and database) is fed the same facts again."""
    outcomes: list[ProjectionOutcome] = []
    order = uuid.UUID("0a0b0c0d-6666-4000-8000-0000000000ff")

    class Recording:
        def __init__(self, scope: ProjectorScope) -> None:
            self._inner = ProjectFactHandler(scope)

        async def handle(self, command: ProjectFactCommand, /) -> ProjectionOutcome:
            outcome = await self._inner.handle(command)
            # the topics are private to this test (Topics fixture); the filter keeps only its order
            if command.event.correlation_id == order:
                outcomes.append(outcome)
            return outcome

    def wire() -> Wiring:
        registry = HandlerRegistry[ProjectorScope]()
        registry.register_command(ProjectFactCommand, Recording)
        return registry.build(otc_projector.application), registry.registered_factories()

    events = [
        facts.build(
            "order.placed.v1", correlation_id=order, payload={"order_reference": new_reference()}
        ),
        facts.build("stock.reserved.v1", correlation_id=order),
        facts.build("order.confirmed.v1", correlation_id=order),
    ]
    model = runtime_env.read_model()
    try:
        first = await runtime_env.start("rebuilt", externals=Externals(wire=wire))
        await produce(events)
        await wait_for_keys(model, order, 3)
        await first.stop()
        bytes_before = await model.raw(order)
        assert outcomes == [ProjectionOutcome.PROCESSED] * 3

        second = await runtime_env.start("rebuilt", externals=Externals(wire=wire))
        await produce(events)  # the same facts again
        await wait_for_outcomes(outcomes, 6)
        await second.stop()
        assert outcomes[3:] == [ProjectionOutcome.DUPLICATE] * 3
        assert await model.raw(order) == bytes_before, "a rebuilt runtime changed the document"
    finally:
        await model.client.close()


async def wait_for_keys(model: Any, order: Any, count: int) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        found = await model.collection.find_one({"_id": str(order)})
        if found is not None and len(found["processedEventKeys"]) >= count:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"PR51: {count} dedup keys were not recorded within 60 s")


async def wait_for_outcomes(outcomes: list[ProjectionOutcome], count: int) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if len(outcomes) >= count:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"PR51: {count} outcomes were not observed within 60 s (saw {len(outcomes)})")
