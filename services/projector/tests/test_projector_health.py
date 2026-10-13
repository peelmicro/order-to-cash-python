import httpx
from fastapi import FastAPI

from otc_projector.infrastructure.health.checks import CheckResult
from otc_projector.presentation.app import create_app


class FakeRuntime:
    def __init__(self, results: list[CheckResult]) -> None:
        self._results = results

    async def readiness(self) -> list[CheckResult]:
        return self._results


async def get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_projector_health_live_returns_200() -> None:
    response = await get(create_app(), "/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "up"}


async def test_projector_health_ready_is_503_before_the_lifespan_has_started_a_runtime() -> None:
    response = await get(create_app(), "/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "down", "checks": {}}


async def test_projector_health_ready_is_200_with_a_ready_runtime() -> None:
    app = create_app()
    app.state.runtime = FakeRuntime(
        [CheckResult("readModel", True, None), CheckResult("factStream", True, None)]
    )
    response = await get(app, "/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "up",
        "checks": {"readModel": {"status": "up"}, "factStream": {"status": "up"}},
    }


async def test_projector_health_ready_is_503_naming_only_the_failing_check() -> None:
    app = create_app()
    app.state.runtime = FakeRuntime(
        [
            CheckResult("readModel", True, None),
            CheckResult("rpcTransport", False, "NatsNotConnectedError"),
        ]
    )
    response = await get(app, "/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "down",
        "checks": {
            "readModel": {"status": "up"},
            "rpcTransport": {"status": "down", "detail": "NatsNotConnectedError"},
        },
    }
