import httpx

from otc_fulfillment.presentation.app import create_app


async def test_fulfillment_health_live_returns_200() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}
