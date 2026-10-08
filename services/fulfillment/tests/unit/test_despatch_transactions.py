"""`StockTransactions.run` and the despatch repository it builds (feature 18): the transaction hands
`work` the despatch repository and the `DES-` allocator of the SAME session, and the advice's events
are forgotten only AFTER the commit returned (OI9, as the stock repository's are; D4f's sibling).

No database: a fake session factory records `begin` / `commit` / `rollback` / `clear_events` in one
log, so the ORDER is the assertion.
"""

from typing import Any

import pytest

from otc_fulfillment.application.ports.stock_store import StockTransaction
from otc_fulfillment.infrastructure.persistence.despatch_number_allocator import (
    SqlAlchemyDespatchNumberAllocator,
)
from otc_fulfillment.infrastructure.persistence.stock_transactions import (
    SqlAlchemyStockTransactions,
)


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


class FakeStockRepository:
    def clear_saved_events(self) -> None:
        pass


class FakeDespatchRepository:
    def __init__(self, session: FakeSession, log: list[Any]) -> None:
        self.session = session
        self._log = log

    def clear_saved_events(self) -> None:
        self._log.append("clear_despatch_events")


def transactions(log: list[Any], made: list[FakeDespatchRepository]) -> SqlAlchemyStockTransactions:
    def despatch_factory(session: Any, outbox: Any, clock: Any) -> Any:
        repository = FakeDespatchRepository(session, log)
        made.append(repository)
        return repository

    return SqlAlchemyStockTransactions(
        sessions=lambda: FakeSession(log),  # type: ignore[arg-type]
        outbox=None,  # type: ignore[arg-type]
        clock=None,  # type: ignore[arg-type]
        repository_factory=lambda session, outbox, clock: FakeStockRepository(),  # type: ignore[arg-type]
        despatch_repository_factory=despatch_factory,
    )


async def test_the_despatch_events_are_cleared_only_after_the_commit_returned() -> None:
    log: list[Any] = []
    made: list[FakeDespatchRepository] = []

    async def work(tx: StockTransaction) -> str:
        log.append("work")
        return "done"

    assert await transactions(log, made).run(work) == "done"

    assert [entry for entry in log if isinstance(entry, str)] == [
        "begin",
        "work",
        "commit",
        "close",
        "clear_despatch_events",
    ]


async def test_the_despatch_events_are_kept_when_the_attempt_rolls_back() -> None:
    log: list[Any] = []

    async def work(tx: StockTransaction) -> str:
        raise ValueError("a refusal")

    with pytest.raises(ValueError, match="a refusal"):
        await transactions(log, []).run(work)

    assert "rollback" in log
    assert "clear_despatch_events" not in log, "a rolled-back attempt keeps its events"


async def test_the_transaction_hands_work_the_despatch_repository_and_an_allocator_of_its_session() -> (  # noqa: E501
    None
):
    log: list[Any] = []
    made: list[FakeDespatchRepository] = []
    seen: list[StockTransaction] = []

    async def work(tx: StockTransaction) -> None:
        seen.append(tx)

    await transactions(log, made).run(work)

    [tx] = seen
    [repository] = made
    built: Any = tx.despatches
    assert built is repository, "the despatch repository the factory built for this attempt"
    assert isinstance(tx.despatch_numbers, SqlAlchemyDespatchNumberAllocator)
    allocator: Any = tx.despatch_numbers
    assert allocator._session is repository.session, "one session, one transaction"
