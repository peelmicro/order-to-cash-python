"""`StockTransactions.run(work)` (D3, D4): isolation, commit, and the `40P01` re-run (FS19, FS23).

No database: a fake session factory raises REAL `DBAPIError`s carrying a `sqlstate` (the shape
Orders' `test_deadlock_classifier.py` uses: `orig.sqlstate`, exactly the attribute SQLAlchemy's
asyncpg adapter exposes). The pacing is proven by the recorded `sleep` calls, a change of kind
(zero recorded sleeps), not by timing.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
import sqlalchemy.exc
from sqlalchemy.exc import DBAPIError

from otc_fulfillment.application.ports.stock_store import StockTransaction, StoreUnavailableError
from otc_fulfillment.infrastructure.persistence.stock_transactions import (
    SqlAlchemyStockTransactions,
)


class DriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"driver error {sqlstate}")
        self.sqlstate = sqlstate


def dbapi_error(sqlstate: str | None) -> DBAPIError:
    return DBAPIError("SELECT 1", {}, DriverError(sqlstate) if sqlstate else None)  # type: ignore[arg-type]


class FakeBegin:
    def __init__(self, log: list[Any]) -> None:
        self._log = log

    async def __aenter__(self) -> None:
        self._log.append("begin")

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._log.append("rollback" if exc_type is not None else "commit")


class FakeSession:
    def __init__(self, log: list[Any]) -> None:
        self._log = log

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._log.append("close")

    def begin(self) -> FakeBegin:
        return FakeBegin(self._log)

    async def connection(self, *, execution_options: dict[str, str]) -> None:
        self._log.append(("connection", execution_options))


class FakeRepository:
    def __init__(self, log: list[Any]) -> None:
        self._log = log

    def clear_saved_events(self) -> None:
        self._log.append("clear_events")


class Rig:
    def __init__(self) -> None:
        self.log: list[Any] = []
        self.sleeps: list[float] = []
        self.calls = 0
        self.open_error: BaseException | None = None

        def sessions() -> FakeSession:
            if self.open_error is not None:
                raise self.open_error
            return FakeSession(self.log)

        async def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        self.transactions = SqlAlchemyStockTransactions(
            sessions=sessions,  # type: ignore[arg-type]
            outbox=None,  # type: ignore[arg-type]
            clock=None,  # type: ignore[arg-type]
            sleep=sleep,
            repository_factory=lambda session, outbox, clock: FakeRepository(self.log),  # type: ignore[arg-type]
        )

    def work_raising(
        self, *outcomes: BaseException | str
    ) -> Callable[[StockTransaction], Awaitable[str]]:
        """A `work` that raises/returns the next scripted outcome on every call."""
        script = list(outcomes)

        async def work(tx: StockTransaction) -> str:
            self.calls += 1
            self.log.append("work")
            assert script, (
                "an attempt ran beyond the scripted ones: a victim is re-run at most three times"
            )
            outcome = script.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        return work


@pytest.fixture
def rig() -> Rig:
    return Rig()


async def test_fs23_a_deadlock_victim_is_rerun_at_most_three_times_paced_by_200_ms_then_unavailable(
    rig: Rig,
) -> None:
    work = rig.work_raising(dbapi_error("40P01"), dbapi_error("40P01"), dbapi_error("40P01"))

    with pytest.raises(StoreUnavailableError) as refusal:
        await rig.transactions.run(work)

    assert rig.calls == 3, "three attempts in total"
    # literals, not the constants against themselves: 200 ms before each of the two re-runs
    assert rig.sleeps == [0.2, 0.2]
    assert refusal.value.reason == "40P01"
    assert rig.log.count("commit") == 0, "nothing was committed"
    assert rig.log.count("rollback") == 3
    assert "clear_events" not in rig.log, "a rolled-back attempt keeps its events"

    # a survivor: one deadlock, then success. The second attempt commits.
    survivor = Rig()
    result = await survivor.transactions.run(
        survivor.work_raising(dbapi_error("40P01"), "accepted")
    )
    assert result == "accepted"
    assert survivor.calls == 2
    assert survivor.sleeps == [0.2]
    assert survivor.log.count("commit") == 1


@pytest.mark.parametrize("sqlstate", ["40001", "55P03", "57014", "53300", "08006", "08001"])
async def test_fs23_no_other_store_failure_is_rerun(rig: Rig, sqlstate: str) -> None:
    with pytest.raises(StoreUnavailableError) as refusal:
        await rig.transactions.run(rig.work_raising(dbapi_error(sqlstate), "never reached"))

    assert rig.calls == 1
    assert rig.sleeps == []
    assert refusal.value.reason == sqlstate


async def test_fs23_a_non_transient_database_error_is_reraised_unchanged_and_not_rerun(
    rig: Rig,
) -> None:
    error = dbapi_error("23505")  # unique_violation

    with pytest.raises(DBAPIError) as raised:
        await rig.transactions.run(rig.work_raising(error, "never reached"))

    assert raised.value is error
    assert rig.calls == 1
    assert rig.sleeps == []


async def test_fs23_an_error_carrying_no_sqlstate_and_a_domain_error_are_not_rerun(
    rig: Rig,
) -> None:
    with pytest.raises(DBAPIError):
        await rig.transactions.run(rig.work_raising(dbapi_error(None), "never reached"))
    with pytest.raises(ValueError, match="a domain refusal"):
        await rig.transactions.run(rig.work_raising(ValueError("a domain refusal"), "x"))
    assert rig.calls == 2
    assert rig.sleeps == []


async def test_a_pool_timeout_and_a_refused_connection_are_store_unavailable(rig: Rig) -> None:
    with pytest.raises(StoreUnavailableError) as pool:
        await rig.transactions.run(
            rig.work_raising(sqlalchemy.exc.TimeoutError("QueuePool limit reached"), "x")
        )
    assert pool.value.reason == "TimeoutError"

    with pytest.raises(StoreUnavailableError) as refused:
        await rig.transactions.run(rig.work_raising(ConnectionRefusedError("refused"), "x"))
    assert refused.value.reason == "ConnectionRefusedError"

    # a refusal when the session is opened (before `work` ever runs) is the same refusal
    rig.open_error = OSError("no route to host")
    with pytest.raises(StoreUnavailableError) as unopened:
        await rig.transactions.run(rig.work_raising("x"))
    assert unopened.value.reason == "OSError"
    assert rig.calls == 2, "the unopened session never ran `work`"
    assert rig.sleeps == []


async def test_a_cancellation_during_the_backoff_propagates_and_runs_no_further_attempt() -> None:
    rig = Rig()

    async def cancelled_sleep(seconds: float) -> None:
        rig.sleeps.append(seconds)
        raise asyncio.CancelledError

    rig.transactions = SqlAlchemyStockTransactions(
        sessions=lambda: FakeSession(rig.log),  # type: ignore[arg-type]
        outbox=None,  # type: ignore[arg-type]
        clock=None,  # type: ignore[arg-type]
        sleep=cancelled_sleep,
        repository_factory=lambda session, outbox, clock: FakeRepository(rig.log),  # type: ignore[arg-type]
    )

    with pytest.raises(asyncio.CancelledError):
        await rig.transactions.run(rig.work_raising(dbapi_error("40P01"), "never reached"))

    assert rig.calls == 1, "no attempt runs after the cancelled back-off"
    assert rig.sleeps == [0.2]


async def test_events_are_cleared_only_after_the_commit_returns(rig: Rig) -> None:
    result = await rig.transactions.run(rig.work_raising("done"))

    assert result == "done"
    assert rig.log.index("commit") < rig.log.index("clear_events")
    assert rig.log.count("clear_events") == 1

    failing = Rig()
    with pytest.raises(ValueError, match="boom"):
        await failing.transactions.run(failing.work_raising(ValueError("boom")))
    assert "clear_events" not in failing.log, "a rollback keeps the events"


async def test_the_isolation_is_pinned_before_the_first_statement(rig: Rig) -> None:
    await rig.transactions.run(rig.work_raising("done"))

    assert rig.log[:3] == ["begin", ("connection", {"isolation_level": "READ COMMITTED"}), "work"]


async def test_each_attempt_gets_its_own_session_and_transaction(rig: Rig) -> None:
    await rig.transactions.run(rig.work_raising(dbapi_error("40P01"), "ok"))

    assert rig.log.count("begin") == 2
    assert rig.log.count("close") == 2, "the session of a rerun attempt is closed with it"
