"""The operator check (feature 25 acceptance item 2, "login"): constant-time, both halves always
evaluated, and indifferent to which half was wrong.

#7 (`operator-credentials.ts:29-31`) and #8 (`OperatorIdentity.cs:26-27`) compared with `===` /
`==` and argued that no timing channel matters for one configured demo identity. The difference in
#9 is one line (`hmac.compare_digest`), so it is made, and the claim is observable: a spy on the
comparison sees BOTH halves compared, as bytes, whichever was wrong.
"""

import hmac
from typing import Any

import pytest

from otc_gateway.infrastructure.operator_directory import ConfiguredOperator

OPERATOR = ConfiguredOperator(
    username="operator",
    password="s3cret-é-password",
    display_name="The Operator",
)


@pytest.fixture
def comparisons(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    seen: list[tuple[Any, Any]] = []
    real = hmac.compare_digest

    def spy(a: Any, b: Any) -> bool:
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)  # the module calls `hmac.compare_digest`
    return seen


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("operator", "s3cret-é-password"),
        ("wrong-user", "s3cret-é-password"),
        ("operator", "wrong-password"),
        ("wrong-user", "wrong-password"),
        ("", ""),
    ],
)
def test_both_halves_are_always_compared_as_bytes_whichever_one_is_wrong(
    comparisons: list[tuple[Any, Any]], username: str, password: str
) -> None:
    OPERATOR.authenticate(username, password)

    assert len(comparisons) == 2
    assert all(isinstance(a, bytes) and isinstance(b, bytes) for a, b in comparisons)


def test_only_the_exact_pair_authenticates_and_the_identity_carries_no_password() -> None:
    identity = OPERATOR.authenticate("operator", "s3cret-é-password")

    assert identity is not None
    assert (identity.username, identity.display_name, identity.roles) == (
        "operator",
        "The Operator",
        ("operator",),
    )
    assert not hasattr(identity, "password")
    for username, password in (
        ("operator", "s3cret-e-password"),  # the accent matters
        ("Operator", "s3cret-é-password"),  # the case matters
        ("operator ", "s3cret-é-password"),
        ("operator", "s3cret-é-password "),
    ):
        assert OPERATOR.authenticate(username, password) is None, (username, password)


def test_describe_knows_only_the_configured_username(comparisons: list[tuple[Any, Any]]) -> None:
    assert OPERATOR.describe("operator") is not None
    assert OPERATOR.describe("someone") is None
    assert len(comparisons) == 2
