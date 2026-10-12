"""Request bodies and responses through the ONE serializer of the contracts package.

* A body is validated by `model_validate_json(..., by_alias=True, by_name=False)` (the wire form:
  camelCase, integers strict, instants `.mmmZ`), NOT by FastAPI's own validation, which runs in
  Python mode: under `WireModel`'s `strict=True` a JSON string would then be refused for a UUID,
  an enum or a datetime (measured on FastAPI 0.142.2). `wire_body` puts that validation inside the
  parameter's type, so FastAPI still documents the model, and a failure keeps the nested field path
  (`body.amount.amount`) for the `errors[]` of the 400.
* A response is written by `to_wire_json` and returned as a `Response`, so FastAPI neither
  re-validates nor re-serialises it: compact JSON, non-ASCII raw, `.mmmZ` instants, explicit `null`
  only where the contract says a field is nullable.
"""

import json
from typing import Annotated, Any

from fastapi import Body, Response
from pydantic import ValidatorFunctionWrapHandler, WrapValidator

from otc_contracts import WireModel, to_wire_json
from otc_contracts.generated import openapi


def _json_mode_validator[M: WireModel](model: type[M]) -> WrapValidator:
    def validate(value: Any, handler: ValidatorFunctionWrapHandler) -> M:
        # FastAPI hands over BYTES, not the parsed document, when the request's media type is not
        # JSON (or is absent). That body is not the JSON the contract describes: refuse it as a
        # validation failure (-> 400 `VALIDATION_FAILED`) instead of letting `json.dumps` raise a
        # TypeError (500). #7's body parser left `{}` -> 400; #8's ASP.NET answered 415; #9 answers
        # 400: `openapi.yaml` declares it on four of the five body operations and no 415 on any.
        # `cancelOrder` declares no 400, so 400 there is an undeclared status (backlog 215),
        # chosen over a 500 and over an undeclared 415.
        if isinstance(value, bytes | bytearray):
            raise ValueError("the request body must be application/json")
        return model.model_validate_json(json.dumps(value), by_alias=True, by_name=False)

    return WrapValidator(validate)


LoginBody = Annotated[openapi.LoginRequest, Body(), _json_mode_validator(openapi.LoginRequest)]
PlaceOrderBody = Annotated[
    openapi.PlaceOrderRequest, Body(), _json_mode_validator(openapi.PlaceOrderRequest)
]
CancelOrderBody = Annotated[
    openapi.CancelOrderRequest | None,
    Body(),
    _json_mode_validator(openapi.CancelOrderRequest),
]
RegisterPaymentBody = Annotated[
    openapi.RegisterPaymentRequest, Body(), _json_mode_validator(openapi.RegisterPaymentRequest)
]
ReplenishStockBody = Annotated[
    openapi.ReplenishStockRequest, Body(), _json_mode_validator(openapi.ReplenishStockRequest)
]


class ProductsResponse(WireModel):
    items: list[openapi.Product]


class RetailersResponse(WireModel):
    items: list[openapi.Party]


class CompaniesResponse(WireModel):
    items: list[openapi.Party]


def wire_response(
    model: WireModel, status: int = 200, headers: dict[str, str] | None = None
) -> Response:
    return Response(
        content=to_wire_json(model),
        status_code=status,
        media_type="application/json",
        headers=headers,
    )
