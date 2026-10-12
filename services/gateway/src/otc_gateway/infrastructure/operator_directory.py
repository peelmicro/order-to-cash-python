"""`ConfiguredOperator`: the one operator of `GATEWAY_OPERATOR_USERNAME` /
`GATEWAY_OPERATOR_PASSWORD`
(`openapi.yaml` `/auth/login`: a single identity, deliberately not multi-tenant).

The comparison is CONSTANT TIME (`hmac.compare_digest` over UTF-8 bytes) and evaluates both halves
whatever the first said, so neither the response nor its timing tells an attacker which of the two
was wrong. #7 (`operator-credentials.ts`) and #8 (`OperatorAuthenticator.Matches`, `==`) compared
with plain equality and argued no timing channel matters for one configured demo identity; the
comparison is a one-line difference in #9, so it is made.
"""

import hmac

from otc_gateway.domain.auth import OperatorIdentity


class ConfiguredOperator:
    def __init__(self, *, username: str, password: str, display_name: str) -> None:
        self._username = username
        self._password = password
        self._identity = OperatorIdentity(
            username=username, display_name=display_name, roles=("operator",)
        )

    def authenticate(self, username: str, password: str) -> OperatorIdentity | None:
        same_username = hmac.compare_digest(
            username.encode("utf-8"), self._username.encode("utf-8")
        )
        same_password = hmac.compare_digest(
            password.encode("utf-8"), self._password.encode("utf-8")
        )
        return self._identity if same_username and same_password else None

    def describe(self, username: str) -> OperatorIdentity | None:
        known = hmac.compare_digest(username.encode("utf-8"), self._username.encode("utf-8"))
        return self._identity if known else None
