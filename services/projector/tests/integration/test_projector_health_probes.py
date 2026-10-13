"""R60 for Projector against PAUSED real containers (feature 27, S6.7).

A docker-paused container keeps its TCP connection open and answers nothing, which is the failure
a probe without a bound hangs on. The module starts PRIVATE containers (MongoDB, NATS and a Kafka
broker; never the session's: a failed test that left a shared container paused would stall every
later test), runs the service's REAL lifespan against them, pauses one at a time through
`health_support.paused` (which unpauses in a `finally`), and proves with real HTTP calls that
readiness names only that dependency's check `down` within its bound plus one poll interval while
liveness answers `200` throughout, and that the service recovers once the container is unpaused.

Projector's checks (design 7.1): `readModel` (MongoDB), `factStream` (Kafka) and `rpcTransport`
(NATS, the update signal).
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

from otc_projector.infrastructure.messaging.fact_topics import PROJECTOR_FACT_TOPICS
from otc_projector.main import create_app

pytestmark = pytest.mark.integration

SUPPORT_PATH = Path(__file__).resolve().parents[4] / "tests/observability/health_support.py"
CHECKS = ("readModel", "factStream", "rpcTransport")


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
        support.private_mongo() as (mongo, mongo_uri),
        support.private_nats() as (
            nats,
            nats_url,
        ),
        support.private_kafka() as (kafka, brokers),
    ):
        asyncio.run(support.create_topics(brokers, PROJECTOR_FACT_TOPICS))
        yield {
            "readModel": mongo,
            "rpcTransport": nats,
            "factStream": kafka,
            "mongo_uri": mongo_uri,
            "nats_url": nats_url,
            "brokers": brokers,
        }


@asynccontextmanager
async def running_service(
    containers: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[tuple[Any, Any]]:
    monkeypatch.chdir(tmp_path)  # no developer `.env`
    for name, value in {
        "MONGO_URI": containers["mongo_uri"],
        "MONGO_DB_READMODEL": f"otc_health_{uuid.uuid4().hex[:10]}",
        "NATS_URL": containers["nats_url"],
        "KAFKA_BROKERS": containers["brokers"],
        "PROJECTOR_CONSUMER_GROUP": f"projector-health-{uuid.uuid4().hex[:10]}",
    }.items():
        monkeypatch.setenv(name, value)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://projector.test"
        ) as client,
    ):
        yield client, app.state.runtime


@pytest.mark.parametrize("dependency", CHECKS)
async def test_r60_readiness_reports_the_paused_dependency_down_within_its_bound_while_liveness_answers_throughout_and_recovers(  # noqa: E501
    containers: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dependency: str,
) -> None:
    async with running_service(containers, monkeypatch, tmp_path) as (client, _runtime):
        observation = await support.observe_pause(
            container=containers[dependency],
            ready=lambda: client.get("/health/ready"),
            live=lambda: client.get("/health/live"),
            paused_check=dependency,
            check_names=CHECKS,
        )

        assert observation.down_checks == {dependency: "no answer within 2.0 s"}
