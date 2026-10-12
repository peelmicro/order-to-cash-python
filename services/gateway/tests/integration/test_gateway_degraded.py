"""R54's Gateway half and R60's Gateway leg, against real outages.

* R54 (`gateway/integration/query-source.spec`): the order list and the order detail are answered
  from the read model ONLY. Proof by outage: the Gateway is booted over a MongoDB holding the six
  seeded sagas (written by the real projector) and a NATS of its own; NATS is then STOPPED. No
  PostgreSQL, no Kafka and no responder exists in this test at all (the Gateway has no setting that
  names a write model). The list and the detail still answer, in full; a route that does need the
  transport answers its mapped 503; readiness says which dependency is down; liveness stays up.
* R60 (Gateway leg): the same with MongoDB stopped: `readModel` is down, `rpcTransport` is up, the
  read routes answer 503 within the driver bound instead of holding the request for 30 s, and
  liveness stays up.
* Phase 11's boot bound (`1a9ac06`): an unreachable NATS fails the Gateway's boot within the bound,
  naming `NATS_URL`.

Loop scope: function. Containers are Docker-held (assigned ports); every client is closed in the
loop that opened it.
"""

import asyncio
import time
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol

import httpx
import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError
from testcontainers.community.mongodb import MongoDbContainer
from testcontainers.community.nats import NatsContainer
from testcontainers.core.container import DockerContainer

from otc_gateway.composition import load_settings, start_runtime
from otc_gateway.main import create_app
from otc_seed.domain.data.sagas import SAGAS

pytestmark = pytest.mark.integration

NATS_IMAGE = "nats:2.14.5-alpine"  # the compose pin
MONGO_IMAGE = "mongo:8.3.8"  # the compose pin
OPERATOR_PASSWORD = "degraded-operator-password"
JWT_SECRET = "degraded-jwt-secret-0123456789abcdef-0123456789"


def start_nats() -> NatsContainer:
    container = NatsContainer(NATS_IMAGE)
    with warnings.catch_warnings():
        # testcontainers 4.15.0's own readiness wait calls its deprecated `wait_for_logs(<str>)`;
        # the library's warning, ignored for exactly this message around `start()` (as the root
        # conftest does for the session's NATS)
        warnings.filterwarnings(
            "ignore",
            message="The wait_for_logs function with string or callable predicates is deprecated",
            category=DeprecationWarning,
        )
        container.start()
    return container


def gateway_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, *, nats: str, mongo_uri: str, database: str
) -> None:
    monkeypatch.chdir(tmp_path)  # no developer `.env`
    for name, value in {
        "NATS_URL": nats,
        "MONGO_URI": mongo_uri,
        "MONGO_DB_READMODEL": database,
        "JWT_SECRET": JWT_SECRET,
        "GATEWAY_OPERATOR_PASSWORD": OPERATOR_PASSWORD,
        "GATEWAY_RPC_TIMEOUT_MS": "500",
        "GATEWAY_READ_MODEL_TIMEOUT_MS": "1000",
    }.items():
        monkeypatch.setenv(name, value)


@asynccontextmanager
async def gateway_client() -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str], Any]]:
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
        ) as client,
    ):
        login = await client.post(
            "/auth/login", json={"username": "operator", "password": OPERATOR_PASSWORD}
        )
        assert login.status_code == 200, login.text
        yield client, {"Authorization": f"Bearer {login.json()['accessToken']}"}, app


class Container(Protocol):
    def stop(self) -> None: ...


def stop_once(container: Container, stopped: list[bool]) -> None:
    """The test stops a container on purpose and its `finally` must not stop it again."""
    if not stopped:
        stopped.append(True)
        container.stop()


async def retry(
    operation: Callable[[], Awaitable[bool]], *, interval: float, seconds: float, what: str
) -> int:
    """Run `operation` until it answers True: bounded by a deadline and PACED, one attempt per
    `interval` (CLAUDE.md "Retry loops"). Returns the attempts it took, so the pacing is a number a
    test can read (`test_a_retry_loop_is_paced_which_a_count_proves`), not a claim."""
    started = time.monotonic()
    attempts = 0
    while time.monotonic() < started + seconds:
        attempts += 1
        if await operation():
            return attempts
        await asyncio.sleep(interval)
    raise AssertionError(f"{what} did not happen within {seconds} s")


async def mongo_answers(uri: str) -> None:
    """mongo:8 with MONGO_INITDB_ROOT_* restarts mongod after its init: wait for the second one."""

    async def ping() -> bool:
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
            uri, serverSelectionTimeoutMS=500
        )
        try:
            await client.get_database("admin").command("ping")
            return True
        except PyMongoError:
            return False
        finally:
            await client.close()

    await retry(ping, interval=0.3, seconds=40, what="mongod's second start")


async def until(condition: Callable[[], Any], what: str, seconds: float = 15.0) -> None:
    """Wait for a condition that is an event in another process (see `retry`)."""

    async def check() -> bool:
        return bool(await condition())

    await retry(check, interval=0.1, seconds=seconds, what=what)


async def test_a_retry_loop_is_paced_which_a_count_proves() -> None:
    """The pacing of every wait in this file, proved by a COUNT: an operation that fails for one
    second is attempted about ten times at 0.1 s, never hundreds (a loop with its sleep deleted
    spins for the whole second)."""
    started = time.monotonic()

    async def becomes_true_after_a_second() -> bool:
        return time.monotonic() - started >= 1.0

    attempts = await retry(
        becomes_true_after_a_second, interval=0.1, seconds=10, what="a condition one second away"
    )

    assert 8 <= attempts <= 13, f"{attempts} attempts in about 1 s at a 0.1 s interval"


async def test_r54_the_list_and_the_detail_are_answered_with_nats_stopped_and_no_write_model_at_all(
    projected_sagas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    nats = start_nats()
    stopped: list[bool] = []
    try:
        gateway_environment(
            monkeypatch,
            tmp_path,
            nats=nats.nats_uri(),
            mongo_uri=projected_sagas.uri,
            database=projected_sagas.name,
        )
        async with gateway_client() as (client, auth, _):
            ready = await client.get("/health/ready")
            assert ready.status_code == 200, ready.text  # NATS is up: this is the "before"
            stop_once(nats, stopped)

            async def transport_is_down() -> bool:
                body = (await client.get("/health/ready")).json()
                return bool(body["checks"]["rpcTransport"]["status"] == "down")

            await until(transport_is_down, "the Gateway noticing that NATS is gone")

            listed = await client.get("/orders", headers=auth)
            assert listed.status_code == 200
            assert listed.json()["page"] == {"page": 1, "pageSize": 25, "total": 6}
            assert [i["orderReference"] for i in listed.json()["items"]] == [
                f"ORD-00000{n}" for n in (6, 5, 4, 3, 2, 1)
            ]
            for saga in SAGAS:
                detail = await client.get(f"/orders/{saga.order_id}", headers=auth)
                assert detail.status_code == 200, saga.order_reference
                assert detail.json()["orderReference"] == saga.order_reference
                assert detail.json()["status"] == saga.status
                assert len(detail.json()["events"]) == len(saga.timeline)
            unknown = await client.get("/orders/00000000-0000-4000-8000-000000000001", headers=auth)
            assert unknown.status_code == 404

            # the routes that DO need the transport say so, mapped; the read halves did not
            stock = await client.get("/stock", headers=auth)
            assert stock.status_code == 503
            assert stock.json()["code"] in {"UPSTREAM_UNAVAILABLE", "UPSTREAM_TIMEOUT"}
            # readiness names the dependency, liveness is untouched (R60, the RPC transport leg)
            down = await client.get("/health/ready")
            assert down.status_code == 503
            assert down.json()["status"] == "down"
            assert down.json()["checks"]["rpcTransport"]["status"] == "down"
            assert down.json()["checks"]["readModel"] == {"status": "up"}
            assert (await client.get("/health/live")).status_code == 200
    finally:
        stop_once(nats, stopped)


async def test_r60_a_paused_nats_is_down_within_the_probe_bound_not_instantly_and_recovers(
    projected_sagas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A paused broker leaves the TCP connection OPEN and answers nothing: the case #7's NATS probe
    missed (it awaited a PONG with no bound: `order-to-cash-nestjs/progress/
    impl_observability_reliability.md:912`). The probe's own bound is what turns it into `down`."""
    nats = start_nats()
    stopped: list[bool] = []
    try:
        gateway_environment(
            monkeypatch,
            tmp_path,
            nats=nats.nats_uri(),
            mongo_uri=projected_sagas.uri,
            database=projected_sagas.name,
        )
        async with gateway_client() as (client, _, _):
            assert (await client.get("/health/ready")).status_code == 200
            container = nats.get_wrapped_container()
            assert container is not None
            container.pause()
            try:
                started = time.monotonic()
                paused = await client.get("/health/ready")
                elapsed = time.monotonic() - started
            finally:
                container.unpause()

            assert paused.status_code == 503
            assert paused.json()["checks"]["rpcTransport"] == {
                "status": "down",
                "detail": "no answer within 2.0 s",
            }
            assert paused.json()["checks"]["readModel"] == {"status": "up"}
            assert 1.8 <= elapsed < 5.0, f"the probe answered in {elapsed:.2f} s: not its 2 s bound"
            assert (await client.get("/health/live")).status_code == 200

            async def ready_again() -> bool:
                return (await client.get("/health/ready")).status_code == 200

            await until(ready_again, "readiness recovering after the broker was unpaused", 20.0)
    finally:
        stop_once(nats, stopped)


async def test_r60_with_mongodb_stopped_the_read_model_is_down_and_the_read_routes_answer_503_fast(
    nats_server: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    mongo = MongoDbContainer(MONGO_IMAGE, username="otc_test", password="degraded_mongo_pw")
    mongo.start()
    stopped: list[bool] = []
    try:
        uri = (
            f"mongodb://otc_test:degraded_mongo_pw@{mongo.get_container_host_ip()}:"
            f"{mongo.get_exposed_port(27017)}/?authSource=admin"
        )
        await mongo_answers(uri)
        gateway_environment(
            monkeypatch, tmp_path, nats=nats_server.url, mongo_uri=uri, database="otc_degraded"
        )
        async with gateway_client() as (client, auth, _):
            assert (await client.get("/health/ready")).status_code == 200
            stop_once(mongo, stopped)

            started = time.monotonic()
            listed = await client.get("/orders", headers=auth)
            detail = await client.get("/orders/00000000-0000-4000-8000-000000000001", headers=auth)
            elapsed = time.monotonic() - started

            assert (listed.status_code, listed.json()["code"]) == (503, "UPSTREAM_UNAVAILABLE")
            assert (detail.status_code, detail.json()["code"]) == (503, "UPSTREAM_UNAVAILABLE")
            assert elapsed < 6.0, f"two reads took {elapsed:.1f} s against a 1 s driver bound"
            ready = await client.get("/health/ready")
            assert ready.status_code == 503
            assert ready.json()["checks"]["readModel"]["status"] == "down"
            assert ready.json()["checks"]["rpcTransport"] == {"status": "up"}
            assert (await client.get("/health/live")).status_code == 200
    finally:
        stop_once(mongo, stopped)


async def test_an_unreachable_nats_fails_the_gateways_boot_within_the_bound_naming_nats_url(
    fresh_mongo_database: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A Docker-held port with nothing behind it (the nats image, its entrypoint replaced) accepts
    the TCP connection and drops it, as an unreachable broker does; the port is held by Docker."""
    container = (
        DockerContainer(NATS_IMAGE)
        .with_exposed_ports(4222)
        .with_kwargs(entrypoint=["sleep", "120"])
    )
    with container:
        url = f"nats://{container.get_container_host_ip()}:{container.get_exposed_port(4222)}"
        gateway_environment(
            monkeypatch,
            tmp_path,
            nats=url,
            mongo_uri=fresh_mongo_database.uri,
            database=fresh_mongo_database.name,
        )
        before = {
            t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()
        }
        started = time.monotonic()

        with pytest.raises(RuntimeError) as refused:
            async with asyncio.timeout(20):
                await start_runtime(load_settings(), nats_connect_seconds=2.0)

        elapsed = time.monotonic() - started
    assert elapsed < 6.0, f"the Gateway's boot took {elapsed:.1f} s against a 2 s bound"
    assert "NATS_URL" in str(refused.value)
    assert url in str(refused.value)
    after = {t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()}
    assert after == before, "a task was left behind by the failed boot"
