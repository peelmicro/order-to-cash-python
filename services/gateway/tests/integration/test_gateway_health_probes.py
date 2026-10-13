"""R60 for the Gateway against PAUSED real containers (feature 27, S6.7).

A docker-paused container keeps its TCP connection open and answers nothing, which is the failure a
probe without a bound hangs on. The Gateway's leg was proven with STOPPED containers (a refused
connection fails at once) and, for NATS, in `test_gateway_degraded.py`; this module pauses BOTH of
its dependencies. It starts a PRIVATE MongoDB and a PRIVATE NATS (never the session's: a failed test
that left a shared container paused would stall every later test), runs the service's REAL
lifespan against them, pauses one at a time through `health_support.paused` (which unpauses in a
`finally`), and proves with real HTTP calls that readiness names only that dependency's check
`down` within its bound plus one poll interval while liveness answers `200` throughout, and that
the Gateway recovers once the container is unpaused.

The Gateway's checks (design 7.1): `rpcTransport` (NATS), `readModel` (MongoDB) and
`streamSignals` (the SSE subscriber's task and subscription, which is not a container).
"""

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

from otc_gateway.main import create_app

pytestmark = pytest.mark.integration

SUPPORT_PATH = Path(__file__).resolve().parents[4] / "tests/observability/health_support.py"
CHECKS = ("rpcTransport", "readModel", "streamSignals")
PAUSABLE = ("rpcTransport", "readModel")
OPERATOR_PASSWORD = "health-operator-password"
JWT_SECRET = "health-jwt-secret-0123456789abcdef-0123456789"


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
    with support.private_mongo() as (mongo, mongo_uri), support.private_nats() as (nats, nats_url):
        yield {
            "readModel": mongo,
            "rpcTransport": nats,
            "mongo_uri": mongo_uri,
            "nats_url": nats_url,
        }


@asynccontextmanager
async def running_service(
    containers: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.chdir(tmp_path)  # no developer `.env`
    for name, value in {
        "NATS_URL": containers["nats_url"],
        "MONGO_URI": containers["mongo_uri"],
        "MONGO_DB_READMODEL": f"otc_health_{uuid.uuid4().hex[:10]}",
        "JWT_SECRET": JWT_SECRET,
        "GATEWAY_OPERATOR_PASSWORD": OPERATOR_PASSWORD,
        "GATEWAY_RPC_TIMEOUT_MS": "500",
        "GATEWAY_READ_MODEL_TIMEOUT_MS": "1000",
    }.items():
        monkeypatch.setenv(name, value)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
        ) as client,
    ):
        yield client


@pytest.mark.parametrize("dependency", PAUSABLE)
async def test_r60_readiness_reports_the_paused_dependency_down_within_its_bound_while_liveness_answers_throughout_and_recovers(  # noqa: E501
    containers: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dependency: str,
) -> None:
    async with running_service(containers, monkeypatch, tmp_path) as client:
        observation = await support.observe_pause(
            container=containers[dependency],
            ready=lambda: client.get("/health/ready"),
            live=lambda: client.get("/health/live"),
            paused_check=dependency,
            check_names=CHECKS,
        )

        assert observation.down_checks == {dependency: "no answer within 2.0 s"}
