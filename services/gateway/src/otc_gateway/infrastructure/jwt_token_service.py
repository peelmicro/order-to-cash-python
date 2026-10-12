"""`JwtTokenService`: HS256 bearer tokens over PyJWT (acceptance item 2).

#7 used `jsonwebtoken` behind one adapter
(`apps/gateway/src/infrastructure/auth/jwt-token.adapter.ts`);
#8 hand-rolled HS256 over `HMACSHA256` because `JwtBearer` is not in its shared framework, and its
`Verify` checked the issuer only WHEN THE TOKEN CARRIED ONE (a token with no `iss` passed). #9 uses
the library and pins what the library is told to enforce, each property armed in
`tests/unit/test_jwt_token_service.py`:

* signature: HS256 with `JWT_SECRET`; `algorithms=["HS256"]` is a pinned allow-list, so `alg: none`
  and an RS256/HS256 key confusion are refused (`InvalidAlgorithmError`), never "verified";
* expiry: `exp` is REQUIRED and enforced; a token without one is refused;
* issuer: `iss` is REQUIRED and compared with `JWT_ISSUER`; another issuer, or none, is refused;
* subject: `sub` is REQUIRED (it names the operator);
* structure: a token that is not three base64url segments of JSON is refused (`DecodeError`).

Every `jwt.PyJWTError` becomes `InvalidTokenError`, whose message is generic: the response to a bad
token never says which property failed.
"""

from datetime import timedelta

import jwt

from otc_gateway.application.errors import InvalidTokenError
from otc_gateway.application.ports.clock import Clock
from otc_gateway.application.ports.tokens import IssuedToken, TokenClaims

ALGORITHM = "HS256"
REQUIRED_CLAIMS = ["exp", "iss", "sub"]


class JwtTokenService:
    def __init__(self, *, secret: str, issuer: str, expires_in: int, clock: Clock) -> None:
        self._secret = secret
        self._issuer = issuer
        self._expires_in = expires_in
        self._clock = clock

    def issue(self, claims: TokenClaims) -> IssuedToken:
        now = self._clock.now()
        payload = {
            "sub": claims.subject,
            "roles": list(claims.roles),
            "iss": self._issuer,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self._expires_in)).timestamp()),
        }
        token = jwt.encode(payload, self._secret, algorithm=ALGORITHM)
        return IssuedToken(access_token=token, expires_in=self._expires_in)

    def verify(self, token: str) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError:
            raise InvalidTokenError("the bearer token is invalid or expired") from None
        subject = payload["sub"]
        roles = payload.get("roles", [])
        if not isinstance(subject, str) or not isinstance(roles, list):
            raise InvalidTokenError("the bearer token is invalid or expired")
        return TokenClaims(subject=subject, roles=tuple(str(role) for role in roles))
