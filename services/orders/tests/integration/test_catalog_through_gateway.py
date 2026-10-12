"""Acceptance item 1 of feature 40: `GET /catalog/products|retailers|companies` return the real
rows THROUGH THE REAL GATEWAY (`otc_gateway.main.create_app()`, its own lifespan, its real NATS RPC
client) against the REAL Orders host and PostgreSQL: no stub on either side of the seam
(`docs/lessons.md:123`: #7's first gateway rejection was a client and a responder each green against
the wire it preferred).

The Gateway is driven in-process over ASGI, as the Gateway's own real-responder suite does; MongoDB
is the Gateway's read model, unused by these routes. Fixture values are pairwise distinct across
fields (`catalog_data`, conftest), so the Gateway's mapping of each field is observed.
"""

from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

OPERATOR_PASSWORD = "integration-operator-password"
JWT_SECRET = "integration-jwt-secret-0123456789abcdef-0123456789"


class NatsServerShape(Protocol):
    @property
    def url(self) -> str: ...


class FreshMongoDatabase(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def uri(self) -> str: ...


class GatewayClient:
    def __init__(self, http: httpx.AsyncClient, token: str) -> None:
        self.http = http
        self.auth = {"Authorization": f"Bearer {token}"}

    async def get(self, path: str, **params: Any) -> httpx.Response:
        return await self.http.get(path, params=params, headers=self.auth)


@pytest_asyncio.fixture(loop_scope="function")  # Orders host and Gateway: created and closed here
async def gateway(
    orders_host_factory: Any,
    catalog_data: Any,
    nats_server: NatsServerShape,
    fresh_mongo_database: FreshMongoDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[GatewayClient]:
    from otc_gateway.main import create_app as create_gateway

    async with orders_host_factory(OUTBOX_RELAY_ENABLED="false"):
        for name, value in {
            "NATS_URL": nats_server.url,
            "JWT_SECRET": JWT_SECRET,
            "GATEWAY_OPERATOR_PASSWORD": OPERATOR_PASSWORD,
            "GATEWAY_RPC_TIMEOUT_MS": "5000",
            "MONGO_URI": fresh_mongo_database.uri,
            "MONGO_DB_READMODEL": fresh_mongo_database.name,
        }.items():
            monkeypatch.setenv(name, value)
        app = create_gateway()
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
            ) as http,
        ):
            login = await http.post(
                "/auth/login", json={"username": "operator", "password": OPERATOR_PASSWORD}
            )
            assert login.status_code == 200, login.text
            yield GatewayClient(http, login.json()["accessToken"])


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("/catalog/products", "products"),
        ("/catalog/retailers", "retailers"),
        ("/catalog/companies", "companies"),
    ],
)
async def test_the_gateway_route_returns_the_seeded_enabled_rows_field_for_field_in_code_order(
    gateway: GatewayClient, catalog_data: Any, path: str, kind: str
) -> None:
    response = await gateway.get(path)

    assert response.status_code == 200, response.text
    assert response.json() == {"items": catalog_data.listed(kind, include_disabled=False)}


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("/catalog/products", "products"),
        ("/catalog/retailers", "retailers"),
        ("/catalog/companies", "companies"),
    ],
)
async def test_include_disabled_through_the_gateway_adds_the_disabled_row(
    gateway: GatewayClient, catalog_data: Any, path: str, kind: str
) -> None:
    response = await gateway.get(path, includeDisabled="true")

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items == catalog_data.listed(kind, include_disabled=True)
    assert [item["enabled"] for item in items] == [True, True, True, False]


async def test_a_route_answers_only_its_own_kind(gateway: GatewayClient, catalog_data: Any) -> None:
    products = (await gateway.get("/catalog/products")).json()["items"]
    retailers = (await gateway.get("/catalog/retailers")).json()["items"]

    assert {p["code"] for p in products}.isdisjoint({r["code"] for r in retailers})
    assert all("ean" in p for p in products)
    assert all("ean" not in r for r in retailers)


async def test_without_a_token_the_catalog_is_401(gateway: GatewayClient) -> None:
    response = await gateway.http.get("/catalog/products")

    assert response.status_code == 401
