"""`POST /auth/login` and `GET /auth/me`."""

from otc_contracts.generated import openapi
from otc_gateway.application.errors import InvalidCredentialsError, InvalidTokenError
from otc_gateway.application.messages import GetCurrentUserQuery, LoginCommand
from otc_gateway.application.ports.tokens import IssuedToken, TokenClaims
from otc_gateway.application.scope import GatewayScope


class LoginHandler:
    def __init__(self, scope: GatewayScope) -> None:
        self._scope = scope

    async def handle(self, command: LoginCommand, /) -> IssuedToken:
        operator = self._scope.operators.authenticate(command.username, command.password)
        if operator is None:
            raise InvalidCredentialsError("the submitted credentials do not match")
        return self._scope.tokens.issue(TokenClaims(operator.username, operator.roles))


class GetCurrentUserHandler:
    def __init__(self, scope: GatewayScope) -> None:
        self._scope = scope

    async def handle(self, query: GetCurrentUserQuery, /) -> openapi.CurrentUser:
        operator = self._scope.operators.describe(query.subject)
        if operator is None:
            # a validly signed token naming nobody this process knows (e.g. the operator was
            # renamed): the token is no longer good for anything
            raise InvalidTokenError("the token's subject is not a known operator")
        return openapi.CurrentUser(
            username=operator.username,
            display_name=operator.display_name,
            roles=list(operator.roles),
        )
