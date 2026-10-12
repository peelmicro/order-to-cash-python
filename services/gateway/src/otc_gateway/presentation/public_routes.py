"""The PUBLIC operations: the only ones that answer without a bearer token.

A literal, equal to what `openapi.yaml` declares with `security: []` (`login`, `healthLive`,
`healthReady`, `apiDocs`) and to `bearerAuth`'s own description ("Required on every endpoint except
`POST /auth/login`, `GET /health/live`, `GET /health/ready` and `GET /docs`").
`tests/unit/test_gateway_auth_sweep.py` holds a SECOND literal, derives every other route of the
running app by subtraction and requires a 401 from each, so widening this set fails there: the
sweep's candidates are not selected by the property under test (#8 defect D2).
"""

from typing import Final

PUBLIC_OPERATIONS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("POST", "/auth/login"),
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
        ("GET", "/docs"),
    }
)
