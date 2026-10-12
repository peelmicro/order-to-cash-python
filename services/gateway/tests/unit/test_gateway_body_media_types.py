"""A request body under a non-JSON or absent `Content-Type` is a 400, never a 500 (review B1).

FastAPI hands the body to the parameter as BYTES when the media type is not JSON. The wire
validator (`presentation/wire.py`) once ran `json.dumps` on it: a TypeError, i.e. a 500
`INTERNAL_ERROR` with an ERROR traceback, on every body route, including the anonymous login.
`openapi.yaml` declares 400 on four of the five and no 415 on any, so 400 `VALIDATION_FAILED`;
`cancelOrder` declares no 400, so answering 400 there is an undeclared status (backlog 215, R2-N1).

The population is DERIVED from the running app (every served route that has a body parameter), and
a census sentinel equals it to a literal, so a body route that escapes the derivation fails.
"""

import logging
from typing import Any
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute, iter_route_contexts

EXPECTED_BODY_OPERATIONS = {
    ("POST", "/auth/login"),
    ("POST", "/orders"),
    ("POST", "/orders/{id}/cancel"),
    ("POST", "/invoices/{id}/payments"),
    ("POST", "/stock/replenish"),
}
MEDIA_CASES: dict[str, dict[str, str]] = {
    "text/plain": {"Content-Type": "text/plain"},
    "application/x-www-form-urlencoded": {"Content-Type": "application/x-www-form-urlencoded"},
    "no Content-Type": {},
}


def body_operations(app: Any) -> set[tuple[str, str]]:
    """Every (METHOD, path) the app serves whose route declares a request body."""
    return {
        (method, str(context.path))
        for context in iter_route_contexts(app.routes)
        if isinstance(context.original_route, APIRoute) and context.original_route.body_field
        for method in context.methods or ()
        if method != "HEAD"
    }


async def media_violations(harness: Any, operations: set[tuple[str, str]]) -> list[str]:
    wrong: list[str] = []
    for method, path in sorted(operations):
        for label, extra in MEDIA_CASES.items():
            headers = {**harness.bearer(), **extra}
            response = await harness.client.request(
                method,
                path.replace("{id}", str(uuid4())),
                headers=headers,
                content=b'{"username":"operator","password":"x"}',
            )
            # httpx sets a Content-Type for some content; the `no Content-Type` case must have none
            if label == "no Content-Type":
                assert "content-type" not in response.request.headers
            body = response.json() if response.content else {}
            ok = (
                response.status_code == 400
                and response.headers.get("content-type") == "application/problem+json"
                and body.get("code") == "VALIDATION_FAILED"
            )
            if not ok:
                wrong.append(
                    f"{method} {path} [{label}] -> {response.status_code} "
                    f"{response.headers.get('content-type')} {body.get('code')}"
                )
    return wrong


async def test_the_body_operations_of_the_running_app_are_the_expected_five(harness: Any) -> None:
    assert body_operations(harness.app) == EXPECTED_BODY_OPERATIONS


async def test_every_body_operation_answers_400_validation_failed_for_a_non_json_media_type(
    harness: Any, caplog: pytest.LogCaptureFixture
) -> None:
    operations = body_operations(harness.app)
    assert operations == EXPECTED_BODY_OPERATIONS

    with caplog.at_level(logging.DEBUG):
        wrong = await media_violations(harness, operations)

    assert wrong == []
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], [r.getMessage() for r in errors]


async def test_the_guard_sees_a_sixth_body_route_added_to_the_app(harness: Any) -> None:
    from pydantic import BaseModel

    class Extra(BaseModel):
        x: int

    async def extra(body: Extra) -> dict[str, int]:
        return {"x": body.x}

    harness.app.add_api_route("/zz-extra-body", extra, methods=["POST"])

    found = body_operations(harness.app)

    assert found - EXPECTED_BODY_OPERATIONS == {("POST", "/zz-extra-body")}
