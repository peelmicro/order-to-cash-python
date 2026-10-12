"""Acceptance item 2: PyJWT HS256 login, `GET /auth/me`, and R63 (the login limit).

Black-box through the real app (middlewares, routes, dispatcher, JWT service, operator check,
throttle); only the RPC client and the read model are fakes. R63's three sentences are three tests.
"""

import re
from typing import Any

import httpx
import jwt

from otc_contracts.generated import openapi
from otc_gateway.application.errors import RpcUnavailableError

OPERATOR = {"username": "operator", "password": "unit-test-operator-password"}


async def test_login_issues_an_hs256_bearer_token_for_the_operator_and_the_expiry_in_seconds(
    harness: Any,
) -> None:
    response = await harness.login()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert set(body) == {"accessToken", "tokenType", "expiresIn"}
    assert body["tokenType"] == "Bearer"
    assert body["expiresIn"] == 3600  # JWT_EXPIRES_IN, in seconds
    openapi.LoginResponse.model_validate_json(response.content, by_alias=True)
    header = jwt.get_unverified_header(body["accessToken"])
    assert header["alg"] == "HS256"
    claims = jwt.decode(
        body["accessToken"],
        "unit-test-secret-0123456789abcdef-0123",
        algorithms=["HS256"],
        issuer="order-to-cash",
    )
    assert claims["sub"] == "operator"
    assert claims["roles"] == ["operator"]
    assert claims["exp"] - claims["iat"] == 3600


async def test_a_wrong_password_and_a_wrong_username_are_refused_identically_and_issue_no_token(
    harness: Any,
) -> None:
    wrong_password = await harness.login(password="not-the-password")
    wrong_username = await harness.login(username="not-the-operator")

    for response in (wrong_password, wrong_username):
        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"
        body = response.json()
        assert body["code"] == "INVALID_CREDENTIALS"
        assert "accessToken" not in body
    # the two refusals differ in nothing a caller could use to tell which half was wrong
    keys = {"type", "title", "status", "detail", "code"}
    assert {k: wrong_password.json()[k] for k in keys} == {
        k: wrong_username.json()[k] for k in keys
    }


async def test_me_describes_the_operator_the_token_names(harness: Any) -> None:
    token = (await harness.login()).json()["accessToken"]

    response = await harness.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {
        "username": "operator",
        "displayName": "Order-To-Cash Operator",
        "roles": ["operator"],
    }


async def test_a_validly_signed_token_naming_nobody_this_process_knows_is_refused(
    harness: Any,
) -> None:
    response = await harness.client.get("/auth/me", headers=harness.bearer("somebody-else"))

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


async def test_a_malformed_login_body_is_a_400_with_field_errors_that_never_echo_the_password(
    harness: Any,
) -> None:
    # the PASSWORD is the field that fails (a list, not a string), so an error that echoed its
    # input would write the secret into the response
    response = await harness.client.post(
        "/auth/login", json={"username": "operator", "password": ["hunter2-do-not-echo"]}
    )

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert [e["field"] for e in body["errors"]] == ["password"]
    assert "hunter2-do-not-echo" not in response.text


# ---------------------------------------------------------------------------------------- R63


async def exhaust_the_limit(harness: Any) -> None:
    for _ in range(3):  # the harness's limit
        assert (await harness.login(password="wrong")).status_code == 401


async def test_r63_exceeding_the_login_limit_is_a_429_problem_with_retry_after_in_whole_seconds_and_no_token(  # noqa: E501
    harness: Any,
) -> None:
    await exhaust_the_limit(harness)

    response = await harness.login(password="wrong")

    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    assert re.fullmatch(r"[0-9]+", response.headers["retry-after"])  # delta-seconds, no HTTP-date
    assert int(response.headers["retry-after"]) == 60  # the window's remaining life: all of it
    problem = openapi.Problem.model_validate_json(response.content, by_alias=True)
    assert problem.status == 429
    assert problem.code == "TOO_MANY_REQUESTS"
    assert "accessToken" not in response.json()


async def test_r63_the_refusal_is_the_same_for_valid_and_for_invalid_credentials(
    harness: Any,
) -> None:
    await exhaust_the_limit(harness)

    valid = await harness.login()
    invalid = await harness.login(password="wrong")

    assert valid.status_code == invalid.status_code == 429
    assert "accessToken" not in valid.text
    # same body (modulo the instant and the per-request correlation id), same header
    drop = {"occurredAt", "correlationId"}
    assert {k: v for k, v in valid.json().items() if k not in drop} == {
        k: v for k, v in invalid.json().items() if k not in drop
    }
    assert valid.headers["retry-after"] == invalid.headers["retry-after"]


async def test_r63_the_limit_counts_every_attempt_whatever_its_credentials_and_whatever_its_body(
    harness: Any,
) -> None:
    await harness.login(password="wrong")
    await harness.client.post("/auth/login", json={"username": 1})  # a 400: still an attempt
    await harness.login()  # a valid one: still an attempt

    assert (await harness.login()).status_code == 429


async def test_r63_a_refused_client_is_still_served_on_every_other_endpoint(
    harness: Any,
) -> None:
    from otc_contracts.generated import asyncapi

    headers = harness.bearer()  # a token issued out of band: logging in would spend an attempt
    await exhaust_the_limit(harness)
    assert (await harness.login()).status_code == 429
    harness.rpc.will_reply(
        "catalog.reference.list", asyncapi.CatalogReferenceListReplyPayload(products=[])
    )

    assert (await harness.client.get("/auth/me", headers=headers)).status_code == 200
    assert (await harness.client.get("/health/live")).status_code == 200
    assert (await harness.client.get("/catalog/products", headers=headers)).status_code == 200
    assert (await harness.client.get("/docs")).status_code == 200


async def test_r63_the_retry_after_is_what_remains_of_the_window_and_the_window_reopens(
    harness: Any,
) -> None:
    await exhaust_the_limit(harness)
    harness.clock.mono_ms += 20_500  # 20.5 s into a 60 s window

    refused = await harness.login()
    assert int(refused.headers["retry-after"]) == 40  # 39.5 s rounded UP to whole seconds

    harness.clock.mono_ms += 39_500  # the window has run out
    assert (await harness.login()).status_code == 200


async def test_r63_the_budget_is_per_client_address(harness: Any) -> None:
    await exhaust_the_limit(harness)
    assert (await harness.login()).status_code == 429

    other = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app, client=("203.0.113.9", 4242)),
        base_url="http://gateway.test",
    )
    async with other:
        response = await other.post("/auth/login", json=OPERATOR)

    assert response.status_code == 200


async def test_a_login_that_the_rpc_transport_cannot_affect_never_touches_the_rpc_client(
    harness: Any,
) -> None:
    harness.rpc.will_reply("orders.create", RpcUnavailableError("orders.create", "down"))

    await harness.login()
    await harness.client.get("/auth/me", headers=harness.bearer())

    assert harness.rpc.calls == []
