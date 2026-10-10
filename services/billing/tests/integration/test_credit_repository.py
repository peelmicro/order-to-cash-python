"""The credit repository and its transaction against a real PostgreSQL (tasks D3 - D6, D4's pin).

BC10 (rollback), BC24 (instants), BC30 (overflow), BC35 (isolation), BC37 (exact int, unknown
token), and the append-only ledger at SQL level (an earlier row is byte-equal after a later
operation).

Loop scope: function. The engines are created by the tests' own factory and disposed in it, in the
loop that made them.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from otc_billing.application import credit_hold
from otc_billing.application.messages import HoldCreditCommand, HoldOutcomeKind
from otc_billing.application.ports.credit_store import CreditTransaction
from otc_billing.application.scope import BillingScope
from otc_billing.domain.buyer_credit import BuyerCredit, CreditContext, HoldRequest
from otc_billing.domain.errors import CreditLedgerOverflowError, UnknownCreditEntryTypeError
from otc_billing.domain.reasons import CreditReleaseReason
from otc_billing.infrastructure.clock import SystemClock
from otc_billing.infrastructure.credit.always_approve import AlwaysApproveCreditDecision
from otc_billing.infrastructure.ids import UuidIdSource
from otc_billing.infrastructure.outbox.writer import OutboxWriter
from otc_billing.infrastructure.persistence.credit_reads import SqlAlchemyCreditReads
from otc_billing.infrastructure.persistence.credit_transactions import (
    SqlAlchemyCreditTransactions,
)
from otc_billing.infrastructure.persistence.invoice_reads import SqlAlchemyInvoiceReads
from otc_shared_kernel import Money, UniqueId

RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
ORDER = "ORD-000101"
OTHER = "ORD-000202"
WHEN = datetime(2026, 10, 8, 9, 30, 15, 123000, tzinfo=UTC)


class DatabaseShape(Protocol):
    @property
    def url(self) -> str: ...
    @property
    def dsn(self) -> str: ...
    @property
    def name(self) -> str: ...


@dataclass
class Store:
    transactions: SqlAlchemyCreditTransactions
    sessions: async_sessionmaker[AsyncSession]
    engine: AsyncEngine


StoreFactory = Callable[..., Store]


@pytest_asyncio.fixture(loop_scope="function")
async def make_store(migrated_db: DatabaseShape) -> AsyncIterator[StoreFactory]:
    """`make_store(server_settings={...})`: an engine built in THIS test's loop, disposed here."""
    engines: list[AsyncEngine] = []

    def make(*, server_settings: dict[str, str] | None = None) -> Store:
        engine = create_async_engine(
            migrated_db.url,
            connect_args={"server_settings": server_settings} if server_settings else {},
        )
        engines.append(engine)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        transactions = SqlAlchemyCreditTransactions(
            sessions=sessions, outbox=OutboxWriter(clock=SystemClock()), clock=SystemClock()
        )
        return Store(transactions=transactions, sessions=sessions, engine=engine)

    try:
        yield make
    finally:
        for engine in engines:
            await engine.dispose()


def _uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(int=n))


def _hold_work(
    amount: int, order: str = ORDER, *, at: datetime = WHEN, fail_after_save: bool = False
) -> Callable[[CreditTransaction], Awaitable[BuyerCredit]]:
    ids = iter(UniqueId.new() for _ in range(8))

    async def work(tx: CreditTransaction) -> BuyerCredit:
        credit = await tx.credits.lock_for_order(RETAILER, COMPANY, order)
        assert credit is not None, "the seeded line was not found"
        credit.approve(
            HoldRequest(
                order_reference=order, amount=Money(amount, "EUR"), correlation_id=_uid(0xC0)
            ),
            CreditContext(occurred_at=at, causation_id=_uid(0xCA0)),
            lambda: next(ids),
        )
        await tx.credits.save(credit)
        if fail_after_save:
            raise RuntimeError("injected after save, before commit")
        return credit

    return work


async def test_bc10_a_forced_rollback_leaves_neither_the_hold_row_nor_the_outbox_row(
    db: Any, make_store: StoreFactory
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=100_000, code=CODE)
    store = make_store()
    with pytest.raises(RuntimeError, match="injected after save"):
        await store.transactions.run(_hold_work(250, fail_after_save=True))
    assert await db.count("credit_items") == 0, "the hold row survived the rollback"
    assert await db.count("outbox") == 0, "the outbox row survived the rollback"

    # control row: the same work, committed, leaves one of each
    await store.transactions.run(_hold_work(250))
    assert await db.count("credit_items") == 1
    assert await db.count("outbox") == 1


async def test_bc35_the_transaction_runs_at_read_committed(
    db: Any, migrated_db: DatabaseShape, make_store: StoreFactory
) -> None:
    # the server default is changed BEFORE the engine connects, so an inherited default cannot
    # satisfy the assertion
    admin = await asyncpg.connect(migrated_db.dsn)
    try:
        await admin.execute(
            f'ALTER DATABASE "{migrated_db.name}" SET default_transaction_isolation = '
            "'repeatable read'"
        )
    finally:
        await admin.close()
    store = make_store()
    seen: dict[str, str] = {}

    async def work(tx: CreditTransaction) -> None:
        session = tx.credits._session  # type: ignore[attr-defined]
        seen["inside"] = await session.scalar(
            text("SELECT current_setting('transaction_isolation')")
        )

    await store.transactions.run(work)
    assert seen["inside"] == "read committed", (
        f"BC35: the transaction ran at {seen['inside']!r}, not read committed"
    )
    # control: a session that does not pin inherits the altered default
    async with store.sessions() as session:
        inherited = await session.scalar(text("SELECT current_setting('transaction_isolation')"))
    assert inherited == "repeatable read"


async def test_bc37_the_committed_exposure_reaches_the_domain_as_an_exact_int(
    db: Any, make_store: StoreFactory
) -> None:
    credit_id = await db.seed_line(RETAILER, COMPANY, limit=100_000, code=CODE)
    await db.plant_entry(credit_id, ORDER, 5000, "hold")
    await db.plant_entry(credit_id, OTHER, 3000, "hold")
    await db.plant_entry(credit_id, ORDER, 1000, "release")
    await db.plant_entry(credit_id, OTHER, 2000, "consume")  # moves nothing
    store = make_store()
    seen: dict[str, Any] = {}

    async def work(tx: CreditTransaction) -> None:
        credit = await tx.credits.lock_for_order(RETAILER, COMPANY, ORDER)
        assert credit is not None
        seen["snapshot"] = credit.to_snapshot()

    await store.transactions.run(work)
    committed = seen["snapshot"].committed_exposure
    assert type(committed) is int, f"BC37: the committed exposure arrived as {type(committed)}"
    assert committed == 5000 + 3000 - 1000  # the hand sum of the seeded rows
    assert len(seen["snapshot"].entries) == 2, "only the named order's entries are loaded"


def _scope(store: Store) -> BillingScope:
    return BillingScope(
        transactions=store.transactions,
        reads=SqlAlchemyCreditReads(store.sessions),
        invoice_reads=SqlAlchemyInvoiceReads(store.sessions),
        clock=SystemClock(),
        ids=UuidIdSource(),
        credit_decision=AlwaysApproveCreditDecision(),
    )


def _command(retailer: str, company: str, amount: int = 250) -> HoldCreditCommand:
    return HoldCreditCommand(
        order_reference=ORDER,
        retailer_code=retailer,
        company_code=company,
        amount=Money(amount, "EUR"),
        correlation_id=_uid(0xC0),
        request_id=_uid(0xCA0),
    )


async def test_bc37_an_unknown_type_token_on_the_line_refuses_the_hold(
    db: Any, make_store: StoreFactory
) -> None:
    bad = await db.seed_line(RETAILER, COMPANY, limit=100_000, code=CODE)
    await db.plant_entry(bad, OTHER, 777, "Hold")  # another order, so the order's rows are clean
    good = await db.seed_line("RETAIL-88", "SUPPLY-88", limit=100_000, code="CR-000654")
    await db.plant_entry(good, OTHER, 777, "hold")
    scope = _scope(make_store())

    # control line: the same ledger shape with a valid token approves
    approved = await credit_hold.hold(_command("RETAIL-88", "SUPPLY-88"), scope)
    assert approved.outcome is HoldOutcomeKind.APPROVED

    try:
        result = await credit_hold.hold(_command(RETAILER, COMPANY), scope)
    except UnknownCreditEntryTypeError:
        pass
    else:
        pytest.fail(f"BC37: a line with an unknown type token answered {result.outcome}")
    assert await db.count("outbox") == 1, "the refused hold wrote a fact"


async def test_bc30_an_out_of_range_line_sum_is_refused_as_ledger_overflow(
    db: Any, make_store: StoreFactory
) -> None:
    credit_id = await db.seed_line(RETAILER, COMPANY, limit=100_000, code=CODE)
    half = (1 << 62) + 1
    await db.plant_entry(credit_id, OTHER, half, "hold")
    await db.plant_entry(credit_id, OTHER, half, "hold")
    scope = _scope(make_store())
    try:
        result = await credit_hold.hold(_command(RETAILER, COMPANY), scope)
    except CreditLedgerOverflowError as error:
        code = error.code
    except DBAPIError as error:
        pytest.fail(
            f"BC30: the scalar's driver error escaped unmapped: {type(error.orig).__name__}"
        )
    else:
        pytest.fail(f"BC30: an out-of-range line sum answered {result.outcome}")
    assert code == "credit.ledger_overflow"


async def test_bc24_a_ledger_entry_instant_reads_back_unchanged_through_the_mapper_under_a_non_utc_session_time_zone(  # noqa: E501
    db: Any, make_store: StoreFactory
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=100_000, code=CODE)
    store = make_store(server_settings={"TimeZone": "Europe/Madrid"})
    async with store.sessions() as session:
        zone = await session.scalar(text("SHOW TimeZone"))
    assert zone == "Europe/Madrid", "the session time zone was not applied"

    await store.transactions.run(_hold_work(250, at=WHEN))
    seen: dict[str, Any] = {}

    async def read(tx: CreditTransaction) -> None:
        credit = await tx.credits.lock_for_order(RETAILER, COMPANY, ORDER)
        assert credit is not None
        seen["entries"] = credit.entries

    await store.transactions.run(read)
    [entry] = seen["entries"]
    assert entry.entry_date == WHEN, f"BC24: wrote {WHEN}, read back {entry.entry_date}"
    assert entry.entry_date.utcoffset() == timedelta(0), (
        f"BC24: read back {entry.entry_date}, offset {entry.entry_date.utcoffset()}, not UTC"
    )


async def test_an_earlier_ledger_row_is_byte_equal_after_a_later_release(
    db: Any, make_store: StoreFactory
) -> None:
    await db.seed_line(RETAILER, COMPANY, limit=100_000, code=CODE)
    store = make_store()
    await store.transactions.run(_hold_work(250))
    [before] = await db.ledger_of(ORDER)
    assert before["updated_at"] == before["created_at"]

    ids = iter(UniqueId.new() for _ in range(4))

    async def release(tx: CreditTransaction) -> None:
        credit = await tx.credits.lock_for_order(RETAILER, COMPANY, ORDER)
        assert credit is not None
        released = credit.release(
            ORDER,
            CreditReleaseReason.ORDER_CANCELLED,
            _uid(0xC0),
            CreditContext(occurred_at=WHEN + timedelta(seconds=5), causation_id=_uid(0xCA1)),
            lambda: next(ids),
        )
        assert released is not None
        await tx.credits.save(credit)

    await store.transactions.run(release)
    rows = await db.ledger_of(ORDER)
    assert len(rows) == 2
    hold_after = next(r for r in rows if r["id"] == before["id"])
    assert dict(hold_after) == dict(before), "an earlier ledger row changed (updated_at included)"
