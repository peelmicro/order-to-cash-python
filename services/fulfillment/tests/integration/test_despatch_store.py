"""`despatch.create` against the real store, below the NATS responder: the SA-4 read order (the
despatch half of FS25's lock test, #8 id 79), atomicity by FAULT INJECTION (#7's proof), F8's last
line of defence (the unique key), and id provenance end to end.

No host and no NATS: the application function runs over the real `SqlAlchemyStockTransactions`, so
the constructed lock waits and the injected faults act on the real transaction. Each async fixture
is function-scoped (the engine is created and disposed in the loop that uses it).

Atomicity (task J4's shape): a raise AFTER the advice was saved must leave no advice, no line, the
reservations still `reserved`, both stock counters and the `DES-` counter unchanged, and no outbox
row. The probe is shown to DISCRIMINATE by a control run: the same raise with the outbox write moved
OUTSIDE the transaction must report an orphan fact.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from otc_fulfillment.application import despatch_creation
from otc_fulfillment.application.messages import CreateDespatchCommand
from otc_fulfillment.application.ports.clock import Clock
from otc_fulfillment.application.ports.stock_store import StockTransaction
from otc_fulfillment.application.scope import FulfillmentScope
from otc_fulfillment.domain.despatch_advice import DespatchAdvice, DespatchLine
from otc_fulfillment.infrastructure.clock import SystemClock
from otc_fulfillment.infrastructure.outbox.writer import OutboxWriter
from otc_fulfillment.infrastructure.persistence.despatch_repository import (
    SqlAlchemyDespatchRepository,
)
from otc_fulfillment.infrastructure.persistence.stock_reads import SqlAlchemyStockReads
from otc_fulfillment.infrastructure.persistence.stock_transactions import (
    DespatchRepositoryFactory,
    SqlAlchemyStockTransactions,
)
from otc_shared_kernel import DespatchReference, Quantity, UniqueId

COMPANY = "ACME-CO"
ORDER = "ORD-000050"
OTHER_ORDER = "ORD-000051"


def uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(int=n))


def command(order: str = ORDER) -> CreateDespatchCommand:
    return CreateDespatchCommand(
        order_reference=order, correlation_id=uid(0xC0), request_id=uid(0xCA)
    )


class SuppliedIds:
    """An `IdSource` that returns the ids the test chose, in order, and fails when it runs out."""

    def __init__(self, supplied: Sequence[UniqueId]) -> None:
        self.queue = list(supplied)

    def new(self) -> UniqueId:
        assert self.queue, "the application asked for more ids than the test supplied"
        return self.queue.pop(0)


class InjectedFaultError(Exception):
    pass


class RaiseAfterSave(SqlAlchemyDespatchRepository):
    """The fault: the advice, its lines and its fact are saved, THEN the work fails."""

    async def save(self, advice: DespatchAdvice) -> None:
        await super().save(advice)
        raise InjectedFaultError


class AutonomousOutbox(OutboxWriter):
    """The CONTROL's defect: the outbox write on its OWN session and transaction, committed at once,
    i.e. outside the despatch's transaction."""

    def __init__(self, *, clock: Clock, sessions: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(clock=clock)
        self._sessions = sessions

    async def write(self, session: AsyncSession, events: Any) -> None:
        async with self._sessions() as own, own.begin():
            await super().write(own, events)


class OrphanFactRepository(RaiseAfterSave):
    pass


@pytest_asyncio.fixture(loop_scope="function")
async def sessions(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield async_sessionmaker(engine, expire_on_commit=False)


def build_scope(
    sessions: async_sessionmaker[AsyncSession],
    *,
    ids: Any,
    despatch_repository_factory: DespatchRepositoryFactory = SqlAlchemyDespatchRepository,
    outbox: OutboxWriter | None = None,
) -> tuple[FulfillmentScope, SqlAlchemyStockTransactions]:
    clock = SystemClock()
    transactions = SqlAlchemyStockTransactions(
        sessions=sessions,
        outbox=outbox or OutboxWriter(clock=clock),
        clock=clock,
        despatch_repository_factory=despatch_repository_factory,
    )
    scope = FulfillmentScope(
        transactions=transactions, reads=SqlAlchemyStockReads(sessions), clock=clock, ids=ids
    )
    return scope, transactions


def reservation_insert() -> str:
    return (
        "INSERT INTO reservations (id, stock_id, company_code, retailer_code, product_code,"
        " order_reference, units, status, created_at, updated_at)"
        " SELECT $1, id, company_code, 'RET-9', product_code, $2, $3, 'reserved', $4, $4"
        " FROM stock WHERE company_code = $5 AND product_code = $6"
    )


async def reserve_directly(db: Any, number: int, order: str, product: str, units: int) -> uuid.UUID:
    reservation_id = uuid.UUID(int=number)
    await db.execute(
        reservation_insert(), reservation_id, order, units, datetime.now(UTC), COMPANY, product
    )
    return reservation_id


async def snapshot_of_the_store(db: Any) -> dict[str, list[dict[str, Any]]]:
    tables = (
        "stock",
        "reservations",
        "despatches",
        "despatch_items",
        "despatch_number_sequences",
        "outbox",
    )
    return {
        table: [dict(r) for r in await db.fetch(f"SELECT * FROM {table} ORDER BY 1")]  # noqa: S608
        for table in tables
    }


# -------------------------------------------------------------- SA-4: the order of the two reads


async def test_fs25_the_despatch_lock_reads_the_orders_reservations_only_after_the_stock_lock_and_consumes_one_committed_while_it_waited(  # noqa: E501
    db: Any, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # D5's construction applied to `lock_order_items` as the DESPATCH uses it (#8 id 79's despatch
    # half). The order ALREADY holds a reserved reservation of 3 units on PRD-A1.
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 3, 3)])
    existing = await reserve_directly(db, 0x71, ORDER, "PRD-A1", 3)
    scope, _ = build_scope(sessions, ids=SuppliedIds([uid(0xAD), uid(0x11), uid(0x12), uid(0xE5)]))
    # the test's connection FOLLOWS THE PROTOCOL: it locks the stock row, inserts a FURTHER reserved
    # reservation of the order (4 units) on it, raises the counter, and holds
    hold = await db.hold([(COMPANY, "PRD-A1")])
    late = uuid.UUID(int=0x72)
    try:
        await hold.execute(
            reservation_insert(), late, ORDER, 4, datetime.now(UTC), COMPANY, "PRD-A1"
        )
        await hold.execute("UPDATE stock SET reserved_units = 7 WHERE product_code = 'PRD-A1'")

        despatching = asyncio.create_task(despatch_creation.create(command(), scope))
        await db.wait_for_lock_waiters("SELECT%FROM stock%FOR UPDATE%", 1)  # seen UNGRANTED
        assert not despatching.done()
        await hold.commit()

        result = await asyncio.wait_for(despatching, timeout=15)
    finally:
        await hold.rollback()

    assert result.created is True
    statuses = {r["id"]: r["status"] for r in await db.reservations(ORDER)}
    assert statuses == {existing: "consumed", late: "consumed"}, (
        "the despatch read the order's reservations BEFORE the stock lock was granted: the "
        "reservation committed while it waited was not consumed"
    )
    assert sorted(ln.units for ln in result.despatch.lines) == [3, 4], "a line per reservation"
    stock = await db.stock(COMPANY, "PRD-A1")
    assert (stock["units"], stock["reserved_units"]) == (3, 0), (
        "7 units consumed from both counters"
    )


# ------------------------------------------------------------------- F8: the unique key's turn


async def test_f8_the_unique_key_refuses_a_second_advice_for_one_order_and_rolls_the_attempt_back(
    db: Any, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 3, 3)])
    await reserve_directly(db, 0x71, ORDER, "PRD-A1", 3)
    scope, transactions = build_scope(sessions, ids=SuppliedIds([uid(0xAD), uid(0x11), uid(0xE5)]))
    first = await despatch_creation.create(command(), scope)
    assert first.created is True
    before = await snapshot_of_the_store(db)

    def second_advice() -> DespatchAdvice:
        return DespatchAdvice.create(
            advice_id=uid(0xAE),
            event_id=uid(0xE6),
            despatch_reference=DespatchReference("DES-000002"),
            despatch_date=datetime.now(UTC),
            order_reference=ORDER,  # the SAME order
            company_code=COMPANY,
            retailer_code="RET-9",
            lines=[DespatchLine(id=uid(0x21), product_code="PRD-A1", units=Quantity(3))],
            correlation_id=uid(0xC0),
            causation_id=uid(0xCA),
        )

    async def insert_a_second_advice(tx: StockTransaction) -> None:
        await tx.despatches.save(second_advice())  # bypasses the fast path and the in-lock re-read

    with pytest.raises(IntegrityError) as raised:
        await transactions.run(insert_a_second_advice)

    assert getattr(raised.value.orig, "sqlstate", None) == "23505", "a unique violation"
    assert await snapshot_of_the_store(db) == before, "nothing of the second attempt survived"
    # control: a DIFFERENT order's advice is accepted by the same path, so the refusal was the key's
    await db.seed_stock(COMPANY, [("PRD-B2", 10, 0, 3)])

    async def insert_for_another_order(tx: StockTransaction) -> None:
        advice = DespatchAdvice.create(
            advice_id=uid(0xAF),
            event_id=uid(0xE7),
            despatch_reference=DespatchReference("DES-000003"),
            despatch_date=datetime.now(UTC),
            order_reference=OTHER_ORDER,
            company_code=COMPANY,
            retailer_code="RET-9",
            lines=[DespatchLine(id=uid(0x22), product_code="PRD-B2", units=Quantity(1))],
            correlation_id=uid(0xC1),
            causation_id=uid(0xCB),
        )
        await tx.despatches.save(advice)

    await transactions.run(insert_for_another_order)
    assert len(await db.fetch("SELECT * FROM despatches")) == 2


# ------------------------------------------------------------------ atomicity by fault injection


async def reserved_orders(db: Any) -> None:
    """Two orders on two products, reserved directly: A holds 3 + 5, the faulted B holds 2 + 4."""
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 5, 3), ("PRD-B2", 20, 9, 3)])
    await reserve_directly(db, 0x71, ORDER, "PRD-A1", 3)
    await reserve_directly(db, 0x72, ORDER, "PRD-B2", 5)
    await reserve_directly(db, 0x73, OTHER_ORDER, "PRD-A1", 2)
    await reserve_directly(db, 0x74, OTHER_ORDER, "PRD-B2", 4)


async def test_j4_a_failure_after_the_advice_was_saved_leaves_no_advice_no_line_no_fact_no_burned_number_and_every_reservation_reserved(  # noqa: E501
    db: Any, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await reserved_orders(db)
    ok_scope, _ = build_scope(
        sessions, ids=SuppliedIds([uid(0xAD), uid(0x11), uid(0x12), uid(0xE5)])
    )
    assert (await despatch_creation.create(command(ORDER), ok_scope)).created is True
    before = await snapshot_of_the_store(db)
    assert len(before["despatches"]) == 1
    assert before["despatch_number_sequences"][0]["next_value"] == 2
    assert len(before["outbox"]) == 1, "control: the first despatch's fact is in the outbox"
    faulty_scope, _ = build_scope(
        sessions,
        ids=SuppliedIds([uid(0xBD), uid(0x21), uid(0x22), uid(0xE6)]),
        despatch_repository_factory=RaiseAfterSave,
    )

    with pytest.raises(InjectedFaultError):
        await despatch_creation.create(command(OTHER_ORDER), faulty_scope)

    after = await snapshot_of_the_store(db)
    assert after["despatches"] == before["despatches"], "no advice for the faulted order"
    assert after["despatch_items"] == before["despatch_items"], "no line"
    assert after["outbox"] == before["outbox"], "no fact (zero rows for the faulted order)"
    assert after["despatch_number_sequences"] == before["despatch_number_sequences"], (
        "no DES- number burned"
    )
    assert after["reservations"] == before["reservations"]
    assert [r["status"] for r in after["reservations"] if r["order_reference"] == OTHER_ORDER] == [
        "reserved",
        "reserved",
    ]
    assert after["stock"] == before["stock"], "both counters of both products unchanged"


async def test_j4_control_the_probe_reports_an_orphan_fact_when_the_outbox_write_is_outside_the_transaction(  # noqa: E501
    db: Any, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # The probe above reads "zero outbox rows". It must be CAPABLE of seeing one: the same raise,
    # with the outbox written on its own session and committed at once, leaves a fact for an
    # advice that does not exist. If this test fails, the atomicity test above proves nothing.
    await reserved_orders(db)
    real_clock = SystemClock()

    def orphaning(
        session: AsyncSession, outbox: OutboxWriter, clock: Clock
    ) -> OrphanFactRepository:
        # the transaction's own `outbox` is IGNORED: the fact goes out on a session of its own
        autonomous = AutonomousOutbox(clock=real_clock, sessions=sessions)
        return OrphanFactRepository(session, autonomous, clock)

    scope, _ = build_scope(
        sessions,
        ids=SuppliedIds([uid(0xBD), uid(0x21), uid(0x22), uid(0xE6)]),
        despatch_repository_factory=orphaning,
    )

    with pytest.raises(InjectedFaultError):
        await despatch_creation.create(command(OTHER_ORDER), scope)

    assert await db.fetch("SELECT * FROM despatches") == [], "the advice was rolled back"
    orphans = [r for r in await db.outbox() if r["event_type"] == "order.despatched.v1"]
    assert len(orphans) == 1, "an orphan fact: the probe can see it"
    assert orphans[0]["event_id"] == uuid.UUID(int=0xE6)


# ------------------------------------------------------------------ id provenance, end to end


async def test_fs24_every_id_of_the_advice_its_lines_and_its_fact_is_a_supplied_id_in_minting_order(
    db: Any, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 20, 7, 3), ("PRD-B2", 20, 5, 3)])
    await reserve_directly(db, 0x71, ORDER, "PRD-A1", 3)
    await reserve_directly(db, 0x72, ORDER, "PRD-A1", 4)
    await reserve_directly(db, 0x73, ORDER, "PRD-B2", 5)
    # minting order: the advice, then a line per consumed reservation (A1's 0x71, A1's 0x72, B2's
    # 0x73), then the fact. A1's two line ids are supplied DESCENDING so the canonical order
    # (product code, then line id) differs from the minting order.
    ids = SuppliedIds([uid(0xAD), uid(0x33), uid(0x31), uid(0x32), uid(0xE5)])
    scope, _ = build_scope(sessions, ids=ids)

    result = await despatch_creation.create(command(), scope)

    assert ids.queue == [], "exactly the five supplied ids were used"
    [advice] = await db.fetch("SELECT * FROM despatches")
    assert advice["id"] == uuid.UUID(int=0xAD)
    items = await db.fetch("SELECT id, product_code, units FROM despatch_items ORDER BY id")
    assert [(i["id"], i["product_code"], i["units"]) for i in items] == [
        (uuid.UUID(int=0x31), "PRD-A1", 4),
        (uuid.UUID(int=0x32), "PRD-B2", 5),
        (uuid.UUID(int=0x33), "PRD-A1", 3),
    ]
    [fact] = [r for r in await db.outbox() if r["event_type"] == "order.despatched.v1"]
    assert fact["event_id"] == uuid.UUID(int=0xE5)
    assert fact["aggregate_id"] == uuid.UUID(int=0xAD)
    assert fact["correlation_id"] == uuid.UUID(int=0xC0)
    assert fact["causation_id"] == uuid.UUID(int=0xCA)
    expected_lines = [("PRD-A1", 4), ("PRD-A1", 3), ("PRD-B2", 5)]
    assert [(ln.product_code, ln.units) for ln in result.despatch.lines] == expected_lines
    assert [(ln["productCode"], ln["units"]) for ln in fact["payload"]["lines"]] == expected_lines
    assert [ln.id for ln in result.despatch.lines] == [uid(0x31), uid(0x33), uid(0x32)]

    # F8: the repeat asks the id source for NOTHING (its queue is empty) and answers with the same
    # advice in the same line order, reloaded from the rows
    again = await despatch_creation.create(command(), scope)
    assert again.created is False
    assert again.despatch == result.despatch
    assert [ln.id for ln in again.despatch.lines] == [uid(0x31), uid(0x33), uid(0x32)]


# ------------------------------------------------------------ the fast path takes no transaction


async def test_f8_the_fast_path_answers_a_repeat_from_a_plain_read(
    db: Any, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 3, 3)])
    await reserve_directly(db, 0x71, ORDER, "PRD-A1", 3)
    scope, _ = build_scope(sessions, ids=SuppliedIds([uid(0xAD), uid(0x11), uid(0xE5)]))
    created = await despatch_creation.create(command(), scope)
    hold = await db.hold([(COMPANY, "PRD-A1")])  # a held stock row would block any lock taker
    try:
        again = await asyncio.wait_for(despatch_creation.create(command(), scope), timeout=5)
    except TimeoutError:
        pytest.fail(
            "the repeat waited on the held stock row: "
            "F8's fast path did not answer before the transaction"
        )
    finally:
        await hold.rollback()

    assert again.created is False
    assert again.despatch == created.despatch


# ----------------------------------------------------------------- the reload's canonical order


async def test_f8_a_stored_advice_is_reloaded_in_the_canonical_line_order_whatever_the_rows_physical_order(  # noqa: E501
    db: Any, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # rows inserted in an order that is NOT the canonical one (product code, then line id): the
    # reload must sort them itself, in Python; the physical order of the rows is no contract
    now = datetime.now(UTC)
    header = uuid.UUID(int=0xD1)
    await db.execute(
        "INSERT INTO despatches (id, despatch_reference, despatch_date, company_code,"
        " retailer_code, order_reference, created_at, updated_at)"
        " VALUES ($1, 'DES-000009', $2, $3, 'RET-9', $4, $2, $2)",
        header,
        now,
        COMPANY,
        ORDER,
    )
    for number, product, units in ((0x33, "PRD-B2", 5), (0x32, "PRD-A1", 3), (0x31, "PRD-A1", 4)):
        await db.execute(
            "INSERT INTO despatch_items (id, despatch_id, product_code, units, created_at,"
            " updated_at) VALUES ($1, $2, $3, $4, $5, $5)",
            uuid.UUID(int=number),
            header,
            product,
            units,
            now,
        )
    scope, _ = build_scope(sessions, ids=SuppliedIds([]))

    found = await scope.reads.despatch_of_order(ORDER)

    assert found is not None
    assert [(ln.id, ln.product_code, ln.units) for ln in found.lines] == [
        (uid(0x31), "PRD-A1", 4),
        (uid(0x32), "PRD-A1", 3),
        (uid(0x33), "PRD-B2", 5),
    ]
    assert found.id == uid(0xD1)
    assert found.despatch_reference == DespatchReference("DES-000009")
    assert await scope.reads.despatch_of_order("ORD-000099") is None, "control: no such advice"
