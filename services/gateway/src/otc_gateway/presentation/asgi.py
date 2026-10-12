"""Two pure-ASGI middlewares and the Problem writer they share.

Pure ASGI (no `BaseHTTPMiddleware`): a response body is never buffered, which the server-sent event
stream (`GET /orders/stream`, feature 26) depends on.

Order, outermost first: `CorrelationMiddleware` (every later Problem carries the request's
`correlationId`) -> `ProblemMiddleware` (anything a route raises becomes a Problem) ->
`BearerAuthMiddleware` (deny by default: a request is anonymous only when its method and path are in
`PUBLIC_OPERATIONS`, so a route nobody listed is protected, and so is a path that matches no route).
"""

import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from otc_gateway.application.errors import InvalidTokenError
from otc_gateway.application.ports.clock import Clock
from otc_gateway.application.ports.tokens import TokenClaims
from otc_gateway.presentation.problems import (
    PROBLEM_MEDIA_TYPE,
    ProblemSpec,
    classify,
    problem_body,
    unauthorized,
)
from otc_gateway.presentation.public_routes import PUBLIC_OPERATIONS

log = logging.getLogger("otc_gateway.presentation.asgi")

CORRELATION_KEY = "otc.correlation_id"
CLAIMS_KEY = "otc.claims"
CORRELATION_HEADER = b"x-correlation-id"


def correlation_of(scope: Mapping[str, Any]) -> UUID:
    value = scope.get(CORRELATION_KEY)
    return value if isinstance(value, UUID) else uuid4()


def claims_of(scope: Mapping[str, Any]) -> TokenClaims:
    return cast("TokenClaims", scope[CLAIMS_KEY])


def clock_of(scope: Mapping[str, Any]) -> Clock | None:
    runtime = getattr(scope["app"].state, "runtime", None)
    return None if runtime is None else cast("Clock", runtime.clock)


def problem_headers(spec: ProblemSpec, body: bytes) -> list[tuple[bytes, bytes]]:
    headers = [
        (b"content-type", PROBLEM_MEDIA_TYPE.encode("ascii")),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    headers.extend(
        (k.lower().encode("ascii"), v.encode("latin-1")) for k, v in spec.headers.items()
    )
    return headers


async def send_problem(scope: Scope, send: Send, spec: ProblemSpec) -> None:
    clock = clock_of(scope)
    occurred_at = datetime.now(UTC) if clock is None else clock.now()
    body = problem_body(spec, correlation_of(scope), occurred_at)
    await send(
        {
            "type": "http.response.start",
            "status": spec.status,
            "headers": problem_headers(spec, body),
        }
    )
    await send({"type": "http.response.body", "body": body})


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key.lower() == name:
            return cast("bytes", value).decode("latin-1")
    return None


class CorrelationMiddleware:
    """`correlationId` of the request: the caller's `x-correlation-id` when it is a UUID, else a
    fresh one. It is what a Problem reports (R58); a command that names an order replaces it on the
    wire with the order id (`X-Correlation-Id` of `openapi.yaml`'s 201 responses)."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            supplied = _header(scope, CORRELATION_HEADER)
            try:
                scope[CORRELATION_KEY] = UUID(supplied) if supplied else uuid4()
            except ValueError:
                scope[CORRELATION_KEY] = uuid4()
        await self._app(scope, receive, send)


class ProblemMiddleware:
    """Turns whatever the application raises into a Problem. A response already started cannot be
    replaced: that failure is re-raised for the server to log."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self._app(scope, receive, tracking_send)
        except Exception as error:
            if started:
                raise
            spec = classify(error)
            if spec.code == "INTERNAL_ERROR":
                # the one unforeseen failure: the traceback is the evidence
                log.error(
                    "%s %s failed unexpectedly (correlationId=%s)",
                    scope["method"],
                    scope["path"],
                    correlation_of(scope),
                    exc_info=error,
                )
            else:
                # a refusal or an outage the Gateway knows how to describe, 4xx or 5xx: one line
                log.warning(
                    "%s %s refused: %s %s (correlationId=%s)",
                    scope["method"],
                    scope["path"],
                    spec.status,
                    spec.code,
                    correlation_of(scope),
                )
            await send_problem(scope, send, spec)


class BearerAuthMiddleware:
    """Deny by default. The token is `Authorization: Bearer <jwt>`; anything else is a 401 Problem
    before the route (or the lack of one) is looked at."""

    def __init__(self, app: ASGIApp, *, public: Iterable[tuple[str, str]] | None = None) -> None:
        self._app = app
        # read at construction, not at definition: the module's literal is the one source
        self._public = frozenset(PUBLIC_OPERATIONS if public is None else public)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (scope["method"], scope["path"]) in self._public:
            await self._app(scope, receive, send)
            return
        runtime = getattr(scope["app"].state, "runtime", None)
        if runtime is None:
            await send_problem(
                scope,
                send,
                ProblemSpec(
                    503, "UPSTREAM_UNAVAILABLE", "The service has not started", "Not started yet."
                ),
            )
            return
        header = _header(scope, b"authorization")
        scheme, _, token = (header or "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            await send_problem(scope, send, unauthorized())
            return
        try:
            scope[CLAIMS_KEY] = runtime.tokens.verify(token.strip())
        except InvalidTokenError:
            await send_problem(scope, send, unauthorized())
            return
        await self._app(scope, receive, send)
