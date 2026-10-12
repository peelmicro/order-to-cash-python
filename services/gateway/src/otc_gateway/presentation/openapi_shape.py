"""FastAPI's generated OpenAPI document, shaped to the conventions of `openapi.yaml`.

This is NOT how the document is made to match: the routes declare their own parameters, bodies and
`responses=`, and `tests/unit/test_openapi_conformance.py` compares what FastAPI generated with the
committed `specs/shared/openapi.yaml` in both directions. The shaping only removes what the
framework adds that the contract's conventions do not use, and renames a media type:

* `separate_input_output_schemas=False`, for the reason beside it;
* the framework's `422` `HTTPValidationError` (the contract answers a malformed request with 400,
  `ValidationProblem`; `presentation.problems.validation_failed`);
* every `>= 400` response, and the `default` one, whose schema is a Problem (`Problem`,
  `ValidationProblem`, `StockUnavailableProblem`) is `application/problem+json`, as RFC 9457 and
  the contract say, not the `application/json` the framework writes for a model (the readiness
  probe's `503` is a `HealthResponse` and stays `application/json`).
"""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

FRAMEWORK_SCHEMAS = ("HTTPValidationError", "ValidationError")
PROBLEM_SCHEMAS = ("Problem", "ValidationProblem", "StockUnavailableProblem")
HTTP_METHODS = ("get", "post", "put", "delete", "patch", "head", "options")


def _is_framework_validation_response(response: dict[str, Any] | None) -> bool:
    """The `422` the framework adds to a route with parameters, as opposed to one the route declared
    (`placeOrder` and `registerPayment` declare a `422` of their own, a `Problem`)."""
    if response is None:
        return False
    schema = response.get("content", {}).get("application/json", {}).get("schema", {})
    return str(schema.get("$ref", "")).endswith("/HTTPValidationError")


def shaped_openapi(app: FastAPI) -> dict[str, Any]:
    document = get_openapi(
        title="Order-To-Cash - Gateway REST API",
        version="1.0.0",
        routes=app.routes,
        # `WireModel`'s wrap serializer hides the model's fields from the framework's
        # serialization-mode schema (it sees `dict[str, Any]`), so the output schemas are written in
        # validation mode too, which names the fields by their wire aliases.
        separate_input_output_schemas=False,
    )
    for item in document.get("paths", {}).values():
        for method in HTTP_METHODS:
            operation = item.get(method)
            if operation is None:
                continue
            responses = operation.get("responses", {})
            if _is_framework_validation_response(responses.get("422")):
                del responses["422"]
            for status, response in responses.items():
                content = response.get("content", {})
                schema = content.get("application/json", {}).get("schema", {})
                if (status == "default" or int(status) >= 400) and str(
                    schema.get("$ref", "")
                ).rsplit("/", 1)[-1] in (PROBLEM_SCHEMAS):
                    content["application/problem+json"] = content.pop("application/json")
    for name in FRAMEWORK_SCHEMAS:
        document.get("components", {}).get("schemas", {}).pop(name, None)
    return document
