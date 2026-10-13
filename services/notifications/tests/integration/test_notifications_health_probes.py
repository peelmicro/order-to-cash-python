"""R60 for Notifications against PAUSED real containers (feature 27, S6.7).

A docker-paused container keeps its TCP connection open and answers nothing, which is the failure
a probe without a bound hangs on. The module starts PRIVATE containers (PostgreSQL and a Kafka
broker; never the session's: a failed test that left a shared container paused would stall every
later test), runs the service's REAL lifespan against them, pauses one at a time through
`health_support.paused` (which unpauses in a `finally`), and proves with real HTTP calls that
readiness names only that dependency's check `down` within its bound plus one poll interval while
liveness answers `200` throughout, and that the service recovers once the container is unpaused.
For PostgreSQL a write through the service's own pool succeeds afterwards (the probe, on its own
`NullPool` engine, left no poisoned connection in it).

Notifications's checks (design 7.1): `writeModel` (PostgreSQL, the delivery ledger) and
`factStream` (Kafka).
"""

import asyncio
import importlib.util
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from otc_notifications.infrastructure.messaging.fact_topics import NOTIFICATION_FACT_TOPICS
from otc_notifications.main import create_app

pytestmark = pytest.mark.integration

SUPPORT_PATH = Path(__file__).resolve().parents[4] / "tests/observability/health_support.py"
CHECKS = ("writeModel", "factStream")


def _support() -> ModuleType:
    spec = importlib.util.spec_from_file_location("health_support", SUPPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


support = _support()


@pytest.fixture(scope="module")
def containers() -> Iterator[dict[str, Any]]:
    """The private containers of this module, one per dependency, started once."""
    with (
        support.private_postgres() as (postgres, database_url),
        support.private_kafka() as (
            kafka,
            brokers,
        ),
    ):
        asyncio.run(support.create_topics(brokers, NOTIFICATION_FACT_TOPICS))
        yield {
            "writeModel": postgres,
            "factStream": kafka,
            "database_url": database_url,
            "brokers": brokers,
        }


@asynccontextmanager
async def running_service(
    containers: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[tuple[Any, Any]]:
    monkeypatch.chdir(tmp_path)  # no developer `.env`
    for name, value in {
        "NOTIFICATIONS_DATABASE_URL": containers["database_url"],
        "KAFKA_BROKERS": containers["brokers"],
        "NOTIFICATIONS_CONSUMER_GROUP": f"notifications-health-{uuid.uuid4().hex[:10]}",
        "NOTIFICATIONS_SENDER": "console",
    }.items():
        monkeypatch.setenv(name, value)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://notifications.test"
        ) as client,
    ):
        yield client, app.state.runtime


async def write_row(runtime: Any, value: int) -> list[int]:
    """A write through the SERVICE's pool; returns every value stored so far."""
    async with runtime.engine.begin() as connection:
        await connection.execute(text("CREATE TABLE IF NOT EXISTS health_writes (value int)"))
        await connection.execute(
            text("INSERT INTO health_writes VALUES (:value)"), {"value": value}
        )
        rows = await connection.execute(text("SELECT value FROM health_writes ORDER BY value"))
        return [row[0] for row in rows]


@pytest.mark.parametrize("dependency", CHECKS)
async def test_r60_readiness_reports_the_paused_dependency_down_within_its_bound_while_liveness_answers_throughout_and_recovers(  # noqa: E501
    containers: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dependency: str,
) -> None:
    async with running_service(containers, monkeypatch, tmp_path) as (client, runtime):
        if dependency == "writeModel":
            assert await write_row(runtime, 1) == [1], (
                "the pool holds a connection before the pause"
            )

        observation = await support.observe_pause(
            container=containers[dependency],
            ready=lambda: client.get("/health/ready"),
            live=lambda: client.get("/health/live"),
            paused_check=dependency,
            check_names=CHECKS,
        )

        assert observation.down_checks == {dependency: "no answer within 2.0 s"}
        if dependency == "writeModel":
            assert await write_row(runtime, 2) == [1, 2], (
                "a write through the service's pool failed after the PostgreSQL unpause: the "
                "probe poisoned a pooled connection"
            )
