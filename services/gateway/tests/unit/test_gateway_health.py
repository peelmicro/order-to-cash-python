"""R60, the Gateway's leg: liveness consults nothing, readiness reports the two dependencies the
Gateway owns (the RPC transport and the read model), each BOUNDED, and a down dependency withdraws
readiness while liveness stays up. (The Gateway has no write model and no fact stream; the other
services' legs are theirs, and the live-stack proof across all six is feature 27.)

Black-box through the real app; the probes are the harness's switchable fakes. The real probes
(`composition.start_runtime`: a NATS flush, a MongoDB `ping`) are exercised in
`tests/integration/test_gateway_http_over_real_brokers.py`, where a stopped container is the outage.
"""

import asyncio
import time
from typing import Any

import httpx

from otc_contracts.generated import openapi
from otc_gateway.presentation.app import create_app


async def broken() -> object:
    raise ConnectionError("the broker is gone")


async def test_live_answers_up_and_consults_nothing(harness: Any) -> None:
    calls: list[str] = []

    async def counting() -> object:
        calls.append("probe")
        raise ConnectionError

    harness.health_probes["rpcTransport"] = counting
    harness.health_probes["readModel"] = counting

    response = await harness.client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "up"}
    openapi.HealthResponse.model_validate_json(response.content, by_alias=True)
    assert calls == []


async def test_live_answers_before_the_lifespan_has_built_a_runtime() -> None:
    app = create_app()  # app.state.runtime is None: nothing started
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        live = await client.get("/health/live")
        ready = await client.get("/health/ready")

    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json()["code"] == "UPSTREAM_UNAVAILABLE"


async def test_ready_is_up_with_a_check_per_dependency_when_both_answer(harness: Any) -> None:
    response = await harness.client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "up",
        "checks": {"rpcTransport": {"status": "up"}, "readModel": {"status": "up"}},
    }


async def test_r60_an_unreachable_rpc_transport_is_not_ready_while_liveness_stays_up(
    harness: Any,
) -> None:
    harness.health_probes["rpcTransport"] = broken

    ready = await harness.client.get("/health/ready")
    live = await harness.client.get("/health/live")

    assert ready.status_code == 503
    body = openapi.HealthResponse.model_validate_json(ready.content, by_alias=True)
    assert body.status is openapi.Status.down
    assert body.checks is not None
    assert body.checks["rpcTransport"].status is openapi.Status.down
    assert body.checks["rpcTransport"].detail == "ConnectionError"
    assert body.checks["readModel"].status is openapi.Status.up
    assert live.status_code == 200


async def test_r60_an_unreachable_read_model_is_not_ready_while_liveness_stays_up(
    harness: Any,
) -> None:
    harness.health_probes["readModel"] = broken

    ready = await harness.client.get("/health/ready")

    assert ready.status_code == 503
    checks = ready.json()["checks"]
    assert checks["readModel"]["status"] == "down"
    assert checks["rpcTransport"]["status"] == "up"
    assert (await harness.client.get("/health/live")).status_code == 200


async def test_r60_a_probe_that_never_answers_is_bounded_and_two_cost_one_bound(
    harness: Any,
) -> None:
    async def hangs() -> object:
        await asyncio.sleep(30)
        return None

    harness.health_probes["rpcTransport"] = hangs
    harness.health_probes["readModel"] = hangs
    started = time.monotonic()

    ready = await harness.client.get("/health/ready")

    elapsed = time.monotonic() - started
    assert ready.status_code == 503
    assert ready.json()["checks"]["rpcTransport"]["detail"] == "no answer within 0.2 s"
    assert ready.json()["checks"]["readModel"]["detail"] == "no answer within 0.2 s"
    assert elapsed < 0.6, f"two hung probes took {elapsed:.2f} s against a 0.2 s bound each"


async def test_the_probes_are_public_and_need_no_token(harness: Any) -> None:
    for path in ("/health/live", "/health/ready"):
        response = await harness.client.get(path)
        assert response.status_code != 401, path
