import httpx

from otc_orders.presentation.app import create_app


async def test_orders_health_live_returns_200() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


async def test_orders_health_ready_is_503_until_the_lifespan_has_started_the_runtime() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unready", "reasons": ["the service has not started"]}
