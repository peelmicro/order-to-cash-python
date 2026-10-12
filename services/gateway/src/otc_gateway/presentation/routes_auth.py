"""`POST /auth/login`, `GET /auth/me` (`openapi.yaml` tag `auth`)."""

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response

from otc_contracts.generated import openapi
from otc_gateway.application.messages import GetCurrentUserQuery, LoginCommand
from otc_gateway.presentation import contract
from otc_gateway.presentation.asgi import claims_of
from otc_gateway.presentation.dependencies import Runtime, login_throttle_guard
from otc_gateway.presentation.wire import LoginBody, wire_response

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/login",
    operation_id="login",
    summary="Issue a bearer token.",
    response_model=openapi.LoginResponse,
    responses={
        **contract.BAD_REQUEST,
        **contract.declared(401, openapi.Problem, "Bad credentials."),
        **contract.TOO_MANY_REQUESTS,
    },
    # R63: the guard runs BEFORE the body is validated and before the credentials are looked at,
    # so the refusal cannot depend on either.
    dependencies=[Depends(login_throttle_guard)],
)
async def login(body: LoginBody, runtime: Runtime) -> Response:
    issued = await runtime.dispatcher.send(
        LoginCommand(username=body.username, password=body.password), runtime.scope
    )
    scheme: Literal["Bearer"] = "Bearer"
    return wire_response(
        openapi.LoginResponse(
            access_token=issued.access_token, token_type=scheme, expires_in=issued.expires_in
        )
    )


@router.get(
    "/auth/me",
    operation_id="getCurrentUser",
    summary="Describe the authenticated operator.",
    response_model=openapi.CurrentUser,
    responses={**contract.UNAUTHORIZED},
)
async def current_user(request: Request, runtime: Runtime) -> Response:
    claims = claims_of(request.scope)
    user = await runtime.dispatcher.ask(GetCurrentUserQuery(subject=claims.subject), runtime.scope)
    return wire_response(user)
