"""Every route requires a valid bearer token except the literal public set (#8 defect D2).

#8's sweep selected its candidates BY the `[AllowAnonymous]` metadata under test, so marking a route
anonymous removed it from the sweep and 141 tests stayed green. Here the public set is a LITERAL
(`PUBLIC`, below, written once and independent of the application's own `PUBLIC_OPERATIONS`), the
protected set is DERIVED BY SUBTRACTION from the routes the running app actually has, and the sweep
is shown to fail when a protected route is made public and to see a route added after the literals
were written. A second literal is cross-checked against `openapi.yaml`'s `security: []` operations.

For each protected route the refusals are the ones a client can produce: no header, a scheme that
is not Bearer, an empty token, a token signed with another key, an expired one, one from another
issuer, `alg: none` and a malformed one. Every one is a 401
`application/problem+json` carrying `WWW-Authenticate: Bearer`. A control proves the 401 is about
the credentials and not the path: with a valid token no protected route answers 401.
"""

import asyncio
import time
from typing import Any
from uuid import uuid4

import jwt
import pytest
import yaml
from fastapi.routing import APIRoute, iter_route_contexts

from otc_gateway.presentation import asgi
from otc_gateway.presentation.public_routes import PUBLIC_OPERATIONS

PUBLIC = {
    ("POST", "/auth/login"),
    ("GET", "/health/live"),
    ("GET", "/health/ready"),
    ("GET", "/docs"),
}
SECRET = "unit-test-secret-0123456789abcdef-0123"
OTHER_SECRET = "a-different-secret-0123456789abcdef-01"


def real_operations(app: Any) -> set[tuple[str, str]]:
    """Every (METHOD, path) the app routes, read from the running app (never from a list)."""
    # FastAPI 0.142 includes routers lazily (`app.routes` holds `_IncludedRouter` wrappers, not
    # routes); `iter_route_contexts` is the framework's own public flattening, the one its OpenAPI
    # generator walks.
    return {
        (method, str(context.path))
        for context in iter_route_contexts(app.routes)
        if isinstance(context.original_route, APIRoute)
        for method in context.methods or ()
        if method != "HEAD"
    }


def concrete(path: str) -> str:
    return path.replace("{id}", str(uuid4()))


def forged(
    secret: str | None,
    *,
    expired: bool = False,
    issuer: str = "order-to-cash",
    algorithm: str = "HS256",
) -> str:
    now = int(time.time())
    claims = {
        "sub": "operator",
        "iss": issuer,
        "iat": now - (7200 if expired else 0),
        "exp": now - 3600 if expired else now + 600,
    }
    return jwt.encode(claims, secret, algorithm=algorithm)


async def anonymous_violations(harness: Any, operations: set[tuple[str, str]]) -> list[str]:
    """The protected operations that did NOT refuse some kind of unauthenticated request."""
    wrong: list[str] = []
    attempts: dict[str, dict[str, str]] = {
        "no header": {},
        "basic scheme": {"Authorization": "Basic b3BlcmF0b3I6cHc="},
        "empty bearer": {"Authorization": "Bearer "},
        "another key": {"Authorization": f"Bearer {forged(OTHER_SECRET)}"},
        "expired": {"Authorization": f"Bearer {forged(SECRET, expired=True)}"},
        "another issuer": {"Authorization": f"Bearer {forged(SECRET, issuer='someone-else')}"},
        "alg none": {"Authorization": f"Bearer {forged(None, algorithm='none')}"},
        "malformed": {"Authorization": "Bearer not.a.jwt"},
    }
    for method, path in sorted(operations - PUBLIC):
        for label, headers in attempts.items():
            try:
                # bounded: a protected route that is wrongly public and STREAMS would otherwise
                # never answer (`httpx.ASGITransport` waits for the whole body)
                async with asyncio.timeout(1):
                    response = await harness.client.request(
                        method, concrete(path), headers=headers, json={}
                    )
            except TimeoutError:
                wrong.append(f"{method} {path} [{label}] -> an open response, no 401 within 1 s")
                continue
            problem = response.headers.get("content-type") == "application/problem+json"
            challenge = response.headers.get("www-authenticate") == "Bearer"
            if response.status_code != 401 or not problem or not challenge:
                wrong.append(f"{method} {path} [{label}] -> {response.status_code}")
    return wrong


async def test_every_protected_route_of_the_running_app_refuses_every_kind_of_anonymous_request(
    harness: Any,
) -> None:
    operations = real_operations(harness.app)

    assert operations >= PUBLIC, "a public operation is not routed at all"
    assert await anonymous_violations(harness, operations) == []


async def test_the_sweep_covers_the_expected_population_by_subtraction(harness: Any) -> None:
    protected = real_operations(harness.app) - PUBLIC

    # a literal of the protected set, written from `openapi.yaml` (feature 26's stream included)
    assert protected == {
        ("GET", "/auth/me"),
        ("POST", "/orders"),
        ("GET", "/orders"),
        ("GET", "/orders/stream"),
        ("GET", "/orders/{id}"),
        ("POST", "/orders/{id}/cancel"),
        ("GET", "/stock"),
        ("POST", "/stock/replenish"),
        ("GET", "/invoices"),
        ("POST", "/invoices/{id}/payments"),
        ("GET", "/credits"),
        ("GET", "/catalog/products"),
        ("GET", "/catalog/retailers"),
        ("GET", "/catalog/companies"),
    }


STREAMING = {("GET", "/orders/stream")}  # never ends: `httpx.ASGITransport` would wait for ever


async def test_control_with_a_valid_token_no_protected_route_answers_401(
    harness: Any, asgi_stream: Any
) -> None:
    streaming = asgi_stream(harness.app, "/orders/stream", dict(harness.bearer()))
    (ready,) = await streaming.frames(1, "the stream with a valid token")
    assert streaming.status == 200, "the stream refused a valid token"
    assert ready.event == "stream.ready"
    for method, path in sorted(real_operations(harness.app) - PUBLIC - STREAMING):
        response = await harness.client.request(
            method, concrete(path), headers=harness.bearer(), json={}
        )
        assert response.status_code != 401, f"{method} {path}"


async def test_a_path_that_matches_no_route_is_refused_before_it_is_looked_up(
    harness: Any,
) -> None:
    anonymous = await harness.client.get("/no/such/route")
    authenticated = await harness.client.get("/no/such/route", headers=harness.bearer())

    assert anonymous.status_code == 401  # deny by default: nothing is revealed to the anonymous
    assert authenticated.status_code == 404
    assert authenticated.json()["code"] == "NOT_FOUND"


async def test_arm_making_a_protected_route_public_fails_the_sweep(
    harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from otc_gateway.presentation.app import create_app

    monkeypatch.setattr(asgi, "PUBLIC_OPERATIONS", PUBLIC_OPERATIONS | {("GET", "/orders")})
    widened = create_app()
    widened.state.runtime = harness.runtime

    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=widened), base_url="http://gateway.test"
    ) as client:
        harness.client, original = client, harness.client
        try:
            violations = await anonymous_violations(harness, real_operations(widened))
        finally:
            harness.client = original

    assert violations, "the sweep passed with GET /orders made public: it cannot fail"
    assert all(v.startswith("GET /orders [") for v in violations), violations
    assert {v.split(" -> ")[0].split(" [")[1].rstrip("]") for v in violations} == {
        "no header",
        "basic scheme",
        "empty bearer",
        "another key",
        "expired",
        "another issuer",
        "alg none",
        "malformed",
    }


async def test_arm_a_route_added_after_the_literals_were_written_is_in_the_sweep(
    harness: Any,
) -> None:
    async def added_later() -> dict[str, str]:
        return {"hello": "world"}

    harness.app.add_api_route("/added-later", added_later, methods=["GET"])

    operations = real_operations(harness.app)

    assert ("GET", "/added-later") in operations - PUBLIC
    assert await anonymous_violations(harness, operations) == []  # and it IS protected


def test_the_literal_public_set_is_what_openapi_declares_with_security_empty_and_what_the_app_uses() -> (  # noqa: E501
    None
):
    from pathlib import Path

    document = yaml.safe_load(
        (Path(__file__).resolve().parents[4] / "specs/shared/openapi.yaml").read_text("utf-8")
    )
    declared_public = {
        (method.upper(), path)
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method in {"get", "post"} and operation.get("security") == []
    }

    assert declared_public == PUBLIC
    assert PUBLIC_OPERATIONS == PUBLIC
