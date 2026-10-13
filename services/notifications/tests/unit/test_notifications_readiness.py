"""R60 for Notifications, S6.4: liveness consults nothing; readiness is `200` naming every check up,
and `503` naming ONLY the failing check, driven once per check position; each task's death is
attributed to the check of the dependency it serves.

The real `NotificationsRuntime` and the real `build_health_checks` of the composition root are
used, over switchable probes (the real probes against a paused container are
`test_notifications_health_probes.py`) and real asyncio tasks named as the composition names them.
Black-box through the real `create_app`.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Any

import httpx
import pytest

from otc_notifications.composition import NotificationsRuntime, build_health_checks
from otc_notifications.presentation.app import create_app

# The runtime's constructor wants adapters this test never touches: readiness reads only `checks`.
NOTHING: Any = None
CHECKS = ("writeModel", "factStream")
# task name -> the check of the dependency it serves (design 7.2)
TASKS = {"fact-consumer": "factStream"}


class Probes:
    """One switchable fake per check; `calls` counts how often each was consulted."""

    def __init__(self) -> None:
        self.failing: set[str] = set()
        self.calls: list[str] = []

    def probe(self, name: str) -> Any:
        async def run() -> object:
            self.calls.append(name)
            if name in self.failing:
                raise ConnectionError(f"{name} is gone")
            return None

        return run


class World:
    def __init__(self) -> None:
        self.probes = Probes()
        self.joined = True
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.stop = asyncio.Event()

    async def start_tasks(self) -> None:
        async def serve() -> None:
            await self.stop.wait()

        for name in TASKS:
            self.tasks[name] = asyncio.create_task(serve(), name=name)

    def runtime(self) -> Any:
        probe = self.probes.probe
        checks = build_health_checks(
            tasks=self.tasks,
            write_model=probe("writeModel"),
            fact_stream=probe("factStream"),
            consumer_joined=lambda: self.joined,
        )
        return NotificationsRuntime(
            settings=NOTHING,
            dispatcher=NOTHING,
            tasks=self.tasks,
            engine=NOTHING,
            subscriber=NOTHING,
            sender=NOTHING,
            stop_event=self.stop,
            stack=AsyncExitStack(),
            checks=checks,
        )

    async def get(self, path: str, runtime: Any = None) -> httpx.Response:
        app = create_app()
        app.state.runtime = runtime if runtime is not None else self.runtime()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)


@pytest.fixture
async def world() -> AsyncIterator[World]:
    world = World()
    await world.start_tasks()
    yield world
    world.stop.set()
    await asyncio.gather(*world.tasks.values(), return_exceptions=True)


def down_checks(response: httpx.Response) -> dict[str, str | None]:
    checks: dict[str, dict[str, str]] = response.json()["checks"]
    return {n: c.get("detail") for n, c in checks.items() if c["status"] == "down"}


async def test_r60_liveness_answers_up_and_consults_nothing_while_every_check_raises(
    world: World,
) -> None:
    world.probes.failing = set(CHECKS)

    response = await world.get("/health/live")

    assert (response.status_code, response.json()) == (200, {"status": "up"})
    assert world.probes.calls == [], "liveness must not consult a dependency"


async def test_r60_readiness_is_200_and_names_every_check_up_when_all_answer(world: World) -> None:
    response = await world.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "up",
        "checks": {name: {"status": "up"} for name in CHECKS},
    }
    assert sorted(world.probes.calls) == sorted(CHECKS), "every check was probed exactly once"


@pytest.mark.parametrize("failing", CHECKS)
async def test_r60_readiness_is_503_naming_only_the_failing_check_notifications(
    world: World, failing: str
) -> None:
    world.probes.failing = {failing}

    response = await world.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "down"
    assert down_checks(response) == {failing: "ConnectionError"}
    assert sorted(response.json()["checks"]) == sorted(CHECKS), "the others are named, up"


@pytest.mark.parametrize(("task_name", "check_name"), sorted(TASKS.items()))
async def test_r60_a_dead_task_takes_down_the_check_of_the_dependency_it_serves(
    world: World, task_name: str, check_name: str
) -> None:
    world.tasks[task_name].cancel()
    await asyncio.wait({world.tasks[task_name]}, timeout=5)

    response = await world.get("/health/ready")

    assert response.status_code == 503
    assert down_checks(response) == {check_name: f"transport task {task_name} is not running"}


async def test_r60_a_stopping_runtime_reports_every_check_down_without_probing(
    world: World,
) -> None:
    runtime = world.runtime()
    runtime._stopping = True

    response = await world.get("/health/ready", runtime)

    assert response.status_code == 503
    assert down_checks(response) == dict.fromkeys(CHECKS, "shutting down")
    assert world.probes.calls == []


async def test_r60_a_consumer_that_has_not_joined_its_group_takes_the_fact_stream_down(
    world: World,
) -> None:
    world.joined = False

    response = await world.get("/health/ready")

    assert response.status_code == 503
    assert down_checks(response) == {
        "factStream": "the Kafka fact consumer has not joined its group"
    }
