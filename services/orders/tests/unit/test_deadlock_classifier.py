"""The relay's deadlock classifier (feature 14, 4.6; `design.md` 5.7), on REAL `DBAPIError`s.

Port of #8's `DeadlockRetryExecutionStrategyTests` onto SQLSTATE: only `40P01` is retried. The
driver error is a stand-in carrying a `sqlstate`, exactly the attribute SQLAlchemy's asyncpg adapter
exposes on `DBAPIError.orig` (SQLAlchemy 2.1.3 `dialects/postgresql/asyncpg.py:972-983`).
"""

import asyncio
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from otc_orders.infrastructure.outbox.relay import (
    DEADLOCK_ATTEMPTS,
    DEADLOCK_DETECTED,
    OutboxRelay,
    RelayResult,
    sqlstate_of,
)


class DriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"driver error {sqlstate}")
        self.sqlstate = sqlstate


def dbapi_error(orig: Any) -> DBAPIError:  # `None` is typed out of the signature, not out of life
    return DBAPIError("SELECT 1", {}, orig)


@pytest.mark.parametrize(
    ("error", "expected_state", "retried"),
    [
        (dbapi_error(DriverError("40P01")), "40P01", True),  # deadlock_detected
        (dbapi_error(DriverError("40001")), "40001", False),  # serialization_failure
        (dbapi_error(DriverError("23505")), "23505", False),  # unique_violation
        (dbapi_error(None), None, False),  # no driver error attached
        (RuntimeError("not a database error"), None, False),
    ],
    ids=["40P01", "40001", "23505", "orig-none", "runtime-error"],
)
def test_the_classifier_retries_only_a_deadlock_victim(
    error: BaseException, expected_state: str | None, retried: bool
) -> None:
    state = sqlstate_of(error)
    assert state == expected_state
    assert (state == DEADLOCK_DETECTED) is retried


class ScriptedRelay(OutboxRelay):
    """A relay whose cycle is scripted: the retry loop of `run_once` is the production one."""

    def __init__(self, outcomes: list[BaseException | RelayResult]) -> None:
        self._outcomes = outcomes
        self.cycles = 0

    async def _cycle(self) -> RelayResult:
        self.cycles += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


async def test_run_once_retries_a_deadlock_victim_up_to_the_bound_then_lets_it_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def no_wait(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", no_wait)  # the backoff is not what this case measures
    victims = [dbapi_error(DriverError("40P01")) for _ in range(DEADLOCK_ATTEMPTS)]
    relay = ScriptedRelay(list[BaseException | RelayResult](victims))
    with pytest.raises(DBAPIError):
        await relay.run_once()
    assert relay.cycles == DEADLOCK_ATTEMPTS
    # design L17: 3 attempts, 200 ms between them. Literals, not the constant against itself.
    assert sleeps == [0.2, 0.2], "the backoff between deadlock retries is 200 ms, once per retry"
    sleeps.clear()
    survivor = ScriptedRelay([dbapi_error(DriverError("40P01")), RelayResult(0, 0, None)])
    assert (await survivor.run_once()) == RelayResult(0, 0, None)
    assert survivor.cycles == 2
    assert sleeps == [0.2]
    other = ScriptedRelay([dbapi_error(DriverError("40001"))])
    with pytest.raises(DBAPIError):
        await other.run_once()
    assert other.cycles == 1, "40001 is not retried"
