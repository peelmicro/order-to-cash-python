import httpx

from otc_projector.presentation.app import create_app


class FakeRuntime:
    def __init__(self, reasons: list[str]) -> None:
        self._reasons = reasons

    def unready_reasons(self) -> list[str]:
        return self._reasons


async def test_projector_health_live_returns_200() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


async def test_projector_health_ready_is_503_before_the_lifespan_has_started_a_runtime() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unready",
        "reasons": ["the service has not started"],
    }


async def test_projector_health_ready_is_200_with_a_ready_runtime() -> None:
    app = create_app()
    app.state.runtime = FakeRuntime([])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_projector_health_ready_is_503_naming_the_reasons_of_an_unready_runtime() -> None:
    app = create_app()
    app.state.runtime = FakeRuntime(["the NATS connection is closed"])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["reasons"] == ["the NATS connection is closed"]
