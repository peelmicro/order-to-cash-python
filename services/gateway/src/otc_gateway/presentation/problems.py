"""Every non-2xx response is an RFC 9457 `application/problem+json` document (`openapi.yaml`
`Problem`, R58): ONE place decides the status and the stable `code` of every failure the Gateway
raises, and ONE function writes it.

A handler throws the error that is true and nothing here is a handler's business. The mapping:

* an owning context's `RpcError` -> `domain.rpc_error_classification` (the table; the payment rows
  of `openapi.yaml:673-675` are in it);
* no responder / no answer in time / a reply the Gateway could not read -> 503
  `UPSTREAM_UNAVAILABLE`, 503 `UPSTREAM_TIMEOUT`, 503 `UPSTREAM_UNAVAILABLE` (SA-9);
* bad credentials -> 401 `INVALID_CREDENTIALS`; a bad bearer token -> 401 `UNAUTHORIZED`;
* a request that fails its schema -> 400 `VALIDATION_FAILED` with `errors[]` (field, message); the
  message never echoes the submitted value (a rejected login body holds a password);
* anything unforeseen -> 500 `INTERNAL_ERROR` with a GENERIC detail (an exception's text can hold a
  path or a query), the exception logged with the correlation id.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from otc_contracts import WireModel, to_wire_json
from otc_contracts.generated import openapi
from otc_gateway.application.errors import (
    GatewayNotFoundError,
    InvalidCredentialsError,
    InvalidTokenError,
    InvoiceScanBudgetExceededError,
    OrderNotYetProjectedError,
    ReadModelUnavailableError,
    RpcProtocolError,
    RpcRemoteError,
    RpcTimeoutError,
    RpcUnavailableError,
)
from otc_gateway.domain.rpc_error_classification import (
    GENERIC,
    NO_REPLY_IN_TIME,
    NO_RESPONDER,
    PROTOCOL_ERROR,
    Classified,
    classify_rpc_error,
)

log = logging.getLogger("otc_gateway.presentation.problems")

PROBLEM_MEDIA_TYPE = "application/problem+json"
ORDER_NOT_PROJECTED_RETRY_AFTER_SECONDS = 2


class LoginThrottledError(Exception):
    """R63: the login limit was exceeded; wait `retry_after_seconds` (a whole number)."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("too many login attempts")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class ProblemSpec:
    status: int
    code: str
    title: str
    detail: str
    headers: dict[str, str] = field(default_factory=dict)
    errors: tuple[tuple[str, str], ...] | None = None  # (field, message) of a ValidationProblem
    shortages: tuple[openapi.Shortage, ...] | None = None  # of a StockUnavailableProblem


def _shortages(details: object) -> tuple[openapi.Shortage, ...] | None:
    if not isinstance(details, dict):
        return None
    raw = details.get("shortages")
    if not isinstance(raw, list):
        return None
    try:
        return tuple(
            openapi.Shortage.model_validate(item, by_alias=True)
            for item in raw
            if isinstance(item, dict)
        )
    except ValueError:
        return None


def _from_classified(classified: Classified, detail: str) -> ProblemSpec:
    # an INTERNAL_ERROR (or anything that fell to it) never forwards the responder's own text
    text = classified.title if classified.status >= 500 else (detail or classified.title)
    return ProblemSpec(classified.status, classified.code, classified.title, text)


def classify(error: BaseException) -> ProblemSpec:
    """The `ProblemSpec` for a failure of the request path. Order matters: the specific errors
    come before the general ones they are subclasses of."""
    if isinstance(error, LoginThrottledError):
        return ProblemSpec(
            429,
            "TOO_MANY_REQUESTS",
            "Too many requests",
            "Too many login attempts - try again later.",
            {"Retry-After": str(error.retry_after_seconds)},
        )
    if isinstance(error, RpcRemoteError):
        classified = classify_rpc_error(error.code, error.details)
        spec = _from_classified(classified, str(error))
        if classified.code == "STOCK_UNAVAILABLE":
            return ProblemSpec(
                spec.status, spec.code, spec.title, spec.detail, shortages=_shortages(error.details)
            )
        return spec
    if isinstance(error, RpcTimeoutError):
        return _from_classified(GENERIC[NO_REPLY_IN_TIME], str(error))
    if isinstance(error, RpcUnavailableError):
        return _from_classified(GENERIC[NO_RESPONDER], str(error))
    if isinstance(error, RpcProtocolError):
        return _from_classified(PROTOCOL_ERROR, str(error))
    if isinstance(error, ReadModelUnavailableError):
        return _from_classified(GENERIC[NO_RESPONDER], str(error))
    if isinstance(error, InvalidCredentialsError):
        return ProblemSpec(401, "INVALID_CREDENTIALS", "Bad credentials", "Bad credentials.")
    if isinstance(error, InvalidTokenError):
        return unauthorized()
    if isinstance(error, GatewayNotFoundError):
        return ProblemSpec(404, "NOT_FOUND", "No such resource", str(error))
    if isinstance(error, InvoiceScanBudgetExceededError):
        # The invoice may exist; the Gateway only stopped looking. A 404 would be a false statement.
        return ProblemSpec(
            503,
            "SCAN_BUDGET_EXCEEDED",
            "Could not resolve the invoice within this gateway's search window",
            str(error),
        )
    if isinstance(error, OrderNotYetProjectedError):
        # Retryable, never a payment under the wrong correlation (feature 25 acceptance 6).
        return ProblemSpec(
            503,
            "UPSTREAM_UNAVAILABLE",
            "The order is not yet available for this operation",
            str(error),
            {"Retry-After": str(ORDER_NOT_PROJECTED_RETRY_AFTER_SECONDS)},
        )
    return ProblemSpec(
        500, "INTERNAL_ERROR", "An unexpected error occurred", "An unexpected error occurred."
    )


def unauthorized() -> ProblemSpec:
    return ProblemSpec(
        401,
        "UNAUTHORIZED",
        "Missing, expired or invalid bearer token",
        "A valid bearer token is required.",
        {"WWW-Authenticate": "Bearer"},
    )


def validation_failed(errors: list[tuple[str, str]]) -> ProblemSpec:
    return ProblemSpec(
        400,
        "VALIDATION_FAILED",
        "The request was malformed or failed schema validation",
        "The request was malformed or failed schema validation.",
        errors=tuple(errors),
    )


def problem_body(spec: ProblemSpec, correlation_id: UUID, occurred_at: datetime) -> bytes:
    model: WireModel
    if spec.errors is not None:
        model = openapi.ValidationProblem(
            title=spec.title,
            status=spec.status,
            detail=spec.detail,
            code=spec.code,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            errors=[openapi.Error(field=f, message=m) for f, m in spec.errors],
        )
    elif spec.shortages is not None:
        model = openapi.StockUnavailableProblem(
            title=spec.title,
            status=spec.status,
            detail=spec.detail,
            code=spec.code,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            shortages=list(spec.shortages),
        )
    else:
        model = openapi.Problem(
            title=spec.title,
            status=spec.status,
            detail=spec.detail,
            code=spec.code,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
    return to_wire_json(model).encode("utf-8")
