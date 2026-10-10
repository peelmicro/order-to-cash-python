"""`CreditTransactions.run(work)` (task D2; BC27's store half, BC35's pin, L31).

No database: a fake session factory raises REAL `DBAPIError`s carrying a `sqlstate` (the shape
Fulfillment's test uses: `orig.sqlstate`, exactly the attribute SQLAlchemy's asyncpg adapter
exposes). There is NO re-run: a deadlock victim is `UNAVAILABLE`, retried by the saga.

Loop scope: function (pytest-asyncio default); nothing outlives the test.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
import sqlalchemy.exc
from sqlalchemy.exc import DBAPIError

from otc_billing.application.ports.credit_store import CreditTransaction, StoreUnavailableError
from otc_billing.infrastructure.persistence.credit_transactions import (
    SqlAlchemyCreditTransactions,
)


class DriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"driver error {sqlstate}")
        self.sqlstate = sqlstate


def dbapi_error(sqlstate: str | None) -> DBAPIError:
    return DBAPIError("SELECT 1", {}, DriverError(sqlstate) if sqlstate else None)  # type: ignore[arg-type]


class FakeBegin:
    def __init__(self, rig: Rig) -> None:
        self._rig = rig

    async def __aenter__(self) -> None:
        self._rig.log.append("begin")

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is not None:
            self._rig.log.append("rollback")
            return
        if self._rig.commit_error is not None:
            self._rig.log.append("commit-failed")
            raise self._rig.commit_error
        self._rig.log.append("commit")


class FakeSession:
    def __init__(self, rig: Rig) -> None:
        self._rig = rig

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._rig.log.append("close")

    def begin(self) -> FakeBegin:
        return FakeBegin(self._rig)

    async def connection(self, *, execution_options: dict[str, str]) -> None:
        self._rig.log.append(("connection", execution_options))


class FakeRepository:
    def __init__(self, log: list[Any]) -> None:
        self._log = log

    def clear_saved_events(self) -> None:
        self._log.append("clear_events")


class Rig:
    def __init__(self) -> None:
        self.log: list[Any] = []
        self.calls = 0
        self.commit_error: BaseException | None = None
        self.open_error: BaseException | None = None

        def sessions() -> FakeSession:
            if self.open_error is not None:
                raise self.open_error
            return FakeSession(self)

        self.transactions = SqlAlchemyCreditTransactions(
            sessions=sessions,  # type: ignore[arg-type]
            outbox=None,  # type: ignore[arg-type]
            clock=None,  # type: ignore[arg-type]
            repository_factory=lambda session, outbox, clock: FakeRepository(self.log),  # type: ignore[arg-type]
        )

    def work(self, outcome: BaseException | str) -> Callable[[CreditTransaction], Awaitable[str]]:
        async def work(tx: CreditTransaction) -> str:
            self.calls += 1
            self.log.append("work")
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        return work


@pytest.fixture
def rig() -> Rig:
    return Rig()


@pytest.mark.parametrize(
    "sqlstate", ["40P01", "40001", "55P03", "57014", "53300", "08006", "08001"]
)
async def test_bc27_each_transient_sqlstate_becomes_store_unavailable_and_is_not_rerun(
    rig: Rig, sqlstate: str
) -> None:
    try:
        await rig.transactions.run(rig.work(dbapi_error(sqlstate)))
    except StoreUnavailableError as error:
        reason = error.reason
    except DBAPIError:
        pytest.fail(f"BC27: SQLSTATE {sqlstate} escaped as a raw driver error, not UNAVAILABLE")
    else:
        pytest.fail(f"SQLSTATE {sqlstate} did not raise")
    assert reason == sqlstate
    assert rig.calls == 1, "L31: a deadlock victim is not re-run in process"
    assert "commit" not in rig.log
    assert "clear_events" not in rig.log, "a rolled-back call keeps its events"


async def test_a_pool_timeout_and_a_refused_connection_are_store_unavailable(rig: Rig) -> None:
    with pytest.raises(StoreUnavailableError) as pool:
        await rig.transactions.run(rig.work(sqlalchemy.exc.TimeoutError("QueuePool limit reached")))
    assert pool.value.reason == "TimeoutError"
    with pytest.raises(StoreUnavailableError) as refused:
        await rig.transactions.run(rig.work(ConnectionRefusedError("refused")))
    assert refused.value.reason == "ConnectionRefusedError"
    rig.open_error = OSError("no route to host")
    with pytest.raises(StoreUnavailableError) as unopened:
        await rig.transactions.run(rig.work("x"))
    assert unopened.value.reason == "OSError"
    assert rig.calls == 2, "the unopened session never ran `work`"


async def test_a_non_transient_error_propagates_unchanged(rig: Rig) -> None:
    error = dbapi_error("23505")  # unique_violation
    try:
        await rig.transactions.run(rig.work(error))
    except StoreUnavailableError:
        pytest.fail("a non-transient SQLSTATE (23505) was mapped to StoreUnavailableError")
    except DBAPIError as raised:
        same = raised is error
    else:
        pytest.fail("the non-transient error vanished")
    assert same
    with pytest.raises(DBAPIError):
        await rig.transactions.run(rig.work(dbapi_error(None)))
    with pytest.raises(ValueError, match="a domain refusal"):
        await rig.transactions.run(rig.work(ValueError("a domain refusal")))


async def test_events_are_cleared_only_after_the_commit_returns(rig: Rig) -> None:
    assert await rig.transactions.run(rig.work("done")) == "done"
    assert rig.log.index("commit") < rig.log.index("clear_events"), (
        "OI9: events were cleared before the commit returned"
    )
    assert rig.log.count("clear_events") == 1

    failing = Rig()
    failing.commit_error = dbapi_error("57014")
    with pytest.raises(StoreUnavailableError):
        await failing.transactions.run(failing.work("done"))
    assert "commit-failed" in failing.log
    assert "clear_events" not in failing.log, "a commit that raised must leave the events in place"


async def test_the_isolation_is_pinned_before_the_first_statement(rig: Rig) -> None:
    await rig.transactions.run(rig.work("done"))
    assert rig.log[:3] == ["begin", ("connection", {"isolation_level": "READ COMMITTED"}), "work"]
    assert rig.log.count("close") == 1


# ---------------------------------------------------------- feature 21 (D2): the second aggregate


class SessionRecordingRig:
    """A transactions object whose three adapter factories record the session each was handed and
    log their `clear_saved_events` calls into the same log the fake session writes to."""

    def __init__(self) -> None:
        self.rig = Rig()
        self.sessions_seen: dict[str, object] = {}
        self.log = self.rig.log

        def credit_factory(session: object, outbox: object, clock: object) -> FakeRepository:
            self.sessions_seen["credits"] = session
            return FakeRepository(self.log)

        class InvoiceRepo:
            def __init__(self, outer: SessionRecordingRig) -> None:
                self._outer = outer

            def clear_saved_events(self) -> None:
                self._outer.log.append("clear_invoice_events")

        def invoice_factory(session: object, outbox: object, clock: object) -> InvoiceRepo:
            self.sessions_seen["invoices"] = session
            return InvoiceRepo(self)

        def allocator_factory(session: object) -> object:
            self.sessions_seen["invoice_numbers"] = session
            return object()

        self.transactions = SqlAlchemyCreditTransactions(
            sessions=self.rig.transactions._sessions,
            outbox=None,  # type: ignore[arg-type]
            clock=None,  # type: ignore[arg-type]
            repository_factory=credit_factory,  # type: ignore[arg-type]
            invoice_repository_factory=invoice_factory,  # type: ignore[arg-type]
            allocator_factory=allocator_factory,  # type: ignore[arg-type]
        )


async def test_the_three_adapters_work_receives_share_one_session() -> None:
    rig = SessionRecordingRig()
    seen: list[CreditTransaction] = []

    async def work(tx: CreditTransaction) -> str:
        seen.append(tx)
        return "done"

    await rig.transactions.run(work)

    assert set(rig.sessions_seen) == {"credits", "invoices", "invoice_numbers"}
    sessions = list(rig.sessions_seen.values())
    assert sessions[0] is sessions[1] is sessions[2], (
        "L33: the credit repository, the invoice repository and the allocator are on two sessions"
    )
    assert rig.log.count("close") == 1, "exactly one session was opened for the call"
    assert seen[0].credits is not None
    assert seen[0].invoices is not None
    assert seen[0].invoice_numbers is not None


async def test_a_successful_commit_clears_both_aggregates_events_after_it() -> None:
    rig = SessionRecordingRig()
    await rig.transactions.run(lambda tx: _done())
    assert rig.log.count("clear_events") == 1, "the credit repository's events were not cleared"
    assert rig.log.count("clear_invoice_events") == 1, (
        "L34: the invoice repository's events were not cleared"
    )
    assert rig.log.index("commit") < rig.log.index("clear_events")
    assert rig.log.index("commit") < rig.log.index("clear_invoice_events"), (
        "L34: the invoice repository's events were cleared before the commit returned"
    )


async def test_a_commit_that_raises_leaves_both_aggregates_events_in_place() -> None:
    rig = SessionRecordingRig()
    rig.rig.commit_error = dbapi_error("57014")
    with pytest.raises(StoreUnavailableError):
        await rig.transactions.run(lambda tx: _done())
    assert "commit-failed" in rig.log
    assert "clear_events" not in rig.log, "the credit repository's events were cleared"
    assert "clear_invoice_events" not in rig.log, (
        "L34: the invoice repository's events were cleared although the commit raised"
    )


async def _done() -> str:
    return "done"
