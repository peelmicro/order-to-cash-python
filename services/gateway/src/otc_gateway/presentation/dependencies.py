"""FastAPI dependencies shared by the routes."""

from typing import Annotated, cast

from fastapi import Depends, Request
from starlette.exceptions import HTTPException

from otc_gateway.presentation.problems import LoginThrottledError
from otc_gateway.presentation.runtime import GatewayRuntime


def runtime_of(request: Request) -> GatewayRuntime:
    runtime = request.app.state.runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail="the service has not started")
    return cast("GatewayRuntime", runtime)


Runtime = Annotated[GatewayRuntime, Depends(runtime_of)]


def login_throttle_guard(request: Request, runtime: Runtime) -> None:
    """R63: every attempt on `POST /auth/login` counts, whatever the credentials; the key is the
    client address (#7's `ThrottlerGuard` tracker). Behind a proxy every client shares one address
    (and one budget): the trade-off `requirements.md` section 8.1 names and leaves per
    assessment."""
    client = request.client.host if request.client is not None else "unknown"
    wait = runtime.login_throttle.check(client)
    if wait:
        raise LoginThrottledError(wait)
