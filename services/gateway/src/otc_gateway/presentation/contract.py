"""The `responses=` a route declares, so FastAPI's generated document names every status that
`openapi.yaml` declares for the operation (`tests/unit/test_openapi_conformance.py` compares the
two; nothing here is read from the committed document, or the comparison would prove nothing).
"""

from typing import Any

from otc_contracts.generated import openapi

type Responses = dict[int | str, dict[str, Any]]


def declared(status: int | str, model: type[Any], description: str) -> Responses:
    return {status: {"model": model, "description": description}}


BAD_REQUEST = declared(
    400, openapi.ValidationProblem, "The request was malformed or failed schema validation."
)
UNAUTHORIZED = declared(401, openapi.Problem, "Missing, expired or invalid bearer token.")
NOT_FOUND = declared(404, openapi.Problem, "No such resource.")
DOMAIN_ERROR = declared(422, openapi.Problem, "A domain rule refused the request.")
TOO_MANY_REQUESTS = declared(
    429, openapi.Problem, "The login rate limit was exceeded; see Retry-After."
)
# `openapi.yaml` (SA-9) gives EVERY operation a `default` response, `UnlistedProblem`: any status
# the operation does not list, always a `Problem`. Declared once, on the application (`create_app`),
# so a route cannot forget it.
UNLISTED_PROBLEM = declared(
    "default",
    openapi.Problem,
    "Any status this operation does not list. The body is always a Problem.",
)
UPSTREAM_UNAVAILABLE = declared(
    503, openapi.Problem, "The owning context did not answer within the deadline."
)
