"""Who may log in. The credential check lives behind this port (constant-time comparison in the
adapter), so no application or domain code ever holds the secret."""

from typing import Protocol

from otc_gateway.domain.auth import OperatorIdentity


class OperatorDirectory(Protocol):
    def authenticate(self, username: str, password: str) -> OperatorIdentity | None:
        """The operator when both match, else `None` (never says which one was wrong)."""
        ...

    def describe(self, username: str) -> OperatorIdentity | None:
        """The operator a verified token's subject names, or `None` when it names nobody."""
        ...
