"""Bearer tokens: issued at login, verified on every protected request."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: str
    roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IssuedToken:
    access_token: str
    expires_in: int  # seconds


class TokenService(Protocol):
    def issue(self, claims: TokenClaims) -> IssuedToken: ...

    def verify(self, token: str) -> TokenClaims:
        """Raises `InvalidTokenError` for a token that is malformed, forged, expired, from another
        issuer, or signed with any algorithm but the pinned one."""
        ...
