"""Acceptance item 2: the properties the JWT library is told to enforce, each proven to refuse.

`JwtTokenService.verify` is the only verifier. A token is refused (`InvalidTokenError`, one generic
message) when it is signed with another key, expired, from another issuer or from none, has no
expiry or no subject, is `alg: none`, is signed with an algorithm other than the pinned HS256, is
malformed, or has been tampered with. Each row crafts the token with `jwt.encode` directly, so the
service under test cannot have produced the defect for us; the control row (a token the service
issued) must pass, so the instrument can say yes as well as no.
"""

import base64
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest

from otc_gateway.application.errors import InvalidTokenError
from otc_gateway.application.ports.tokens import TokenClaims
from otc_gateway.infrastructure.jwt_token_service import JwtTokenService

SECRET = (
    "jwt-test-secret-0123456789abcdef-0123456789abcdef-0123456789abcdef"  # 66 bytes: HS512-safe
)
OTHER_SECRET = "another-test-secret-0123456789abcdef-0123456789abcdef-0123456789"
ISSUER = "order-to-cash"


class Clock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def service(now: datetime | None = None, *, expires_in: int = 3600) -> JwtTokenService:
    return JwtTokenService(
        secret=SECRET,
        issuer=ISSUER,
        expires_in=expires_in,
        clock=Clock(now or datetime.now(UTC)),
    )


def crafted(
    *,
    key: str | None = SECRET,
    algorithm: str = "HS256",
    drop: tuple[str, ...] = (),
    **override: Any,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {"sub": "operator", "iss": ISSUER, "iat": now, "exp": now + 600}
    claims.update(override)
    for name in drop:
        del claims[name]
    return jwt.encode(claims, key, algorithm=algorithm)


def flipped_signature() -> str:
    """The FIRST character of the signature changed (all six of its bits are significant; the last
    character of an unpadded base64url signature carries only four, so changing it can decode to the
    same bytes: an earlier version of this row failed one run in sixty-four)."""
    header, payload, signature = crafted().split(".")
    first = "B" if signature[0] == "A" else "A"
    return f"{header}.{payload}.{first}{signature[1:]}"


def b64(document: dict[str, Any]) -> str:
    raw = json.dumps(document, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_control_a_token_the_service_issued_is_accepted_with_its_subject_and_roles() -> None:
    issued = service().issue(TokenClaims("operator", ("operator", "auditor")))

    claims = service().verify(issued.access_token)

    assert claims == TokenClaims("operator", ("operator", "auditor"))
    assert issued.expires_in == 3600


def test_the_expiry_is_the_clock_plus_the_configured_seconds() -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    issued = service(now, expires_in=90).issue(TokenClaims("operator", ()))

    claims = jwt.decode(issued.access_token, SECRET, algorithms=["HS256"], issuer=ISSUER)

    assert claims["exp"] == int((now + timedelta(seconds=90)).timestamp())
    assert claims["iat"] == int(now.timestamp())


@pytest.mark.parametrize(
    ("label", "token"),
    [
        ("signed with another key", crafted(key=OTHER_SECRET)),
        ("expired a second ago", crafted(exp=int(time.time()) - 1)),
        ("from another issuer", crafted(iss="someone-else")),
        ("carrying no issuer", crafted(drop=("iss",))),
        ("carrying no expiry", crafted(drop=("exp",))),
        ("carrying no subject", crafted(drop=("sub",))),
        ("alg none", crafted(key=None, algorithm="none")),
        ("signed with HS384, which the pin does not allow", crafted(algorithm="HS384")),
        ("signed with HS512, which the pin does not allow", crafted(algorithm="HS512")),
        (
            "an RS256 header over an HS256-style signature (key confusion)",
            f"{b64({'alg': 'RS256', 'typ': 'JWT'})}."
            f"{b64({'sub': 'operator', 'iss': ISSUER, 'exp': int(time.time()) + 600})}."
            "c2lnbmF0dXJl",
        ),
        ("not a token at all", "abc"),
        ("three segments of nonsense", "a.b.c"),
        ("empty", ""),
        ("a valid token with one character of the signature changed", flipped_signature()),
        ("a token whose payload was swapped after signing", None),
    ],
)
def test_a_token_that_breaks_any_pinned_property_is_refused_with_a_generic_message(
    label: str, token: str | None
) -> None:
    if token is None:  # tampering: keep the header and signature, replace the payload
        header, _, signature = crafted().split(".")
        forged_payload = b64({"sub": "operator", "iss": ISSUER, "exp": int(time.time()) + 9999})
        token = f"{header}.{forged_payload}.{signature}"

    with pytest.raises(InvalidTokenError) as refused:
        service().verify(token)

    assert str(refused.value) == "the bearer token is invalid or expired", (
        label
    )  # says nothing of why


def test_a_hs256_token_signed_with_the_right_key_but_missing_roles_is_accepted_with_none() -> None:
    claims = service().verify(crafted())

    assert claims == TokenClaims("operator", ())
