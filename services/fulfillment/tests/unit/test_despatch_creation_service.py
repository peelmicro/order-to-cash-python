"""The `despatch.create` transactional unit over fakes of the ports (R36, F8, SA-4's despatch half).

Every branch of `despatch_creation.create` / `_despatch_work` is driven here (the table is in
`progress/impl_fulfillment_despatch.md`). The ids come from a `FakeIds` that returns values this
test chose, in order, and every assertion is EQUALITY with them (#8 id 49): the application hands
`scope.ids.new` to the domain, and a handler that built its own ids would be seen.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_fulfillment.application import despatch_creation
from otc_fulfillment.application.despatch_creation import NoReservedStockForDespatchError
from otc_fulfillment.application.messages import CreateDespatchCommand
from otc_fulfillment.application.ports.stock_store import (
    ConcurrentDespatchChangeError,
    LockedStock,
    StockTransaction,
)
from otc_fulfillment.application.scope import FulfillmentScope
from otc_fulfillment.domain.despatch_advice import DespatchAdvice
from otc_fulfillment.domain.events import OrderDespatched
from otc_fulfillment.domain.reservation import ReservationStatus
from otc_fulfillment.domain.snapshot import (
    DespatchLineSnapshot,
    DespatchSnapshot,
    ReservationSnapshot,
    StockItemSnapshot,
)
from otc_fulfillment.domain.stock_item import StockItem
from otc_shared_kernel import DespatchReference, UniqueId

NOW = datetime(2026, 10, 8, 9, 0, 0, 123000, tzinfo=UTC)
ORDER = "ORD-000042"
RESERVED, RELEASED, CONSUMED = (
    ReservationStatus.RESERVED,
    ReservationStatus.RELEASED,
    ReservationStatus.CONSUMED,
)


def uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(int=n))


def reservation(
    number: int, stock: int, product: str, status: ReservationStatus, units: int = 3
) -> ReservationSnapshot:
    return ReservationSnapshot(
        id=uid(number),
        stock_id=uid(stock),
        product_code=product,
        order_reference=ORDER,
        retailer_code="RET-9",
        units=units,
        status=status,
    )


def item(code: str, number: int, rows: Sequence[ReservationSnapshot] = ()) -> StockItem:
    return StockItem.rehydrate(
        StockItemSnapshot(
            id=uid(number),
            company_code="ACME-CO",
            product_code=code,
            units=50,
            reserved_units=sum(r.units for r in rows if r.status is RESERVED),
            low_stock_threshold=2,
            reservations=tuple(rows),
        )
    )


EXISTING = DespatchSnapshot(
    id=uid(0xD1),
    despatch_reference=DespatchReference("DES-000009"),
    despatch_date=NOW,
    order_reference=ORDER,
    company_code="ACME-CO",
    retailer_code="RET-9",
    lines=(DespatchLineSnapshot(id=uid(0xD2), product_code="PRD-A1", units=3),),
)


class FakeStockRepository:
    def __init__(self, locked: LockedStock, log: list[str]) -> None:
        self.locked = locked
        self.log = log
        self.lock_calls: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        self.saves = 0

    async def lock_order_items(self, ref: str, keys: Sequence[tuple[str, str]]) -> LockedStock:
        self.log.append("lock")
        self.lock_calls.append((ref, tuple(keys)))
        return self.locked

    async def save(self) -> None:
        self.log.append("save_stock")
        self.saves += 1


class FakeDespatches:
    def __init__(self, found: DespatchSnapshot | None, log: list[str]) -> None:
        self.found = found
        self.log = log
        self.finds = 0
        self.saved: list[DespatchAdvice] = []

    async def find_by_order_reference(self, ref: str) -> DespatchSnapshot | None:
        self.log.append("re-read")
        self.finds += 1
        return self.found

    async def save(self, advice: DespatchAdvice) -> None:
        self.log.append("save_despatch")
        self.saved.append(advice)


class FakeNumbers:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.allocations = 0

    async def next_reference(self) -> DespatchReference:
        self.log.append("allocate")
        self.allocations += 1
        return DespatchReference("DES-000031")


class FakeTransactions:
    def __init__(
        self, repository: FakeStockRepository, despatches: FakeDespatches, numbers: FakeNumbers
    ) -> None:
        self.repository = repository
        self.despatches = despatches
        self.despatch_numbers = numbers
        self.runs = 0
        self.after_work: Callable[[], Awaitable[None]] | None = None

    async def run[T](self, work: Callable[[StockTransaction], Awaitable[T]]) -> T:
        self.runs += 1
        result = await work(self)  # type: ignore[arg-type]
        if self.after_work is not None:
            await self.after_work()
        return result


class FakeReads:
    def __init__(
        self, keys: tuple[tuple[str, str], ...], existing: DespatchSnapshot | None
    ) -> None:
        self.keys = keys
        self.existing = existing
        self.key_reads = 0
        self.despatch_reads = 0

    async def stock_keys_of_order(self, ref: str) -> tuple[tuple[str, str], ...]:
        self.key_reads += 1
        return self.keys

    async def despatch_of_order(self, ref: str) -> DespatchSnapshot | None:
        self.despatch_reads += 1
        return self.existing


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeIds:
    """Hands out the ids the test chose, in order, and fails loudly when it runs out."""

    def __init__(self, supplied: Sequence[UniqueId]) -> None:
        self.queue = list(supplied)

    def new(self) -> UniqueId:
        assert self.queue, "the application asked for more ids than the test supplied"
        return self.queue.pop(0)


class Rig:
    def __init__(
        self,
        items: Sequence[StockItem],
        reservations: Sequence[ReservationSnapshot],
        *,
        keys: tuple[tuple[str, str], ...] = (("ACME-CO", "PRD-A1"),),
        existing_fast: DespatchSnapshot | None = None,
        existing_in_lock: DespatchSnapshot | None = None,
        ids: Sequence[UniqueId] = (uid(0xAD), uid(0x11), uid(0xE5)),
    ) -> None:
        self.log: list[str] = []
        self.items = {i.product_code: i for i in items}
        self.repository = FakeStockRepository(
            LockedStock(items=self.items, reservations_of_order=tuple(reservations)), self.log
        )
        self.despatches = FakeDespatches(existing_in_lock, self.log)
        self.numbers = FakeNumbers(self.log)
        self.transactions = FakeTransactions(self.repository, self.despatches, self.numbers)
        self.reads = FakeReads(keys, existing_fast)
        self.ids = FakeIds(ids)
        self.scope = FulfillmentScope(
            transactions=self.transactions,
            reads=self.reads,  # type: ignore[arg-type]
            clock=FakeClock(),
            ids=self.ids,
        )


def command() -> CreateDespatchCommand:
    return CreateDespatchCommand(
        order_reference=ORDER, correlation_id=uid(0xC0), request_id=uid(0xCA)
    )


def reserved_rig(**kwargs: Any) -> Rig:
    rows = [reservation(0x71, 0xA1, "PRD-A1", RESERVED)]
    return Rig([item("PRD-A1", 0xA1, rows)], rows, **kwargs)


async def test_f8_the_fast_path_returns_the_existing_advice_without_a_transaction_or_a_lock() -> (
    None
):
    rig = reserved_rig(existing_fast=EXISTING)

    result = await despatch_creation.create(command(), rig.scope)

    assert result.created is False
    assert result.despatch == EXISTING
    assert rig.transactions.runs == 0, "no transaction is opened"
    assert rig.reads.key_reads == 0, "the SA-4 pre-read is not even made"
    assert rig.log == []


async def test_r36_an_order_that_never_held_a_reservation_is_refused_without_a_transaction() -> (
    None
):
    rig = Rig([], [], keys=())

    with pytest.raises(NoReservedStockForDespatchError) as raised:
        await despatch_creation.create(command(), rig.scope)

    assert raised.value.order_reference == ORDER
    assert rig.transactions.runs == 0
    assert rig.log == []


async def test_sa4_the_despatch_takes_the_release_lock_on_the_distinct_keys_in_code_point_order() -> (  # noqa: E501
    None
):
    rows = [reservation(0x71, 0xA1, "PRD-A1", RESERVED)]
    rig = Rig(
        [item("PRD-A1", 0xA1, rows)],
        rows,
        # the pre-read returns the keys unsorted and with a duplicate: the lock gets them sorted,
        # each once (feature 17's `distinct_stock_keys`, the lock order of every transaction)
        keys=(("ACME-CO", "PRD-B2"), ("ACME-CO", "PRD-A1"), ("ACME-CO", "PRD-B2")),
    )

    await despatch_creation.create(command(), rig.scope)

    assert rig.repository.lock_calls == [(ORDER, (("ACME-CO", "PRD-A1"), ("ACME-CO", "PRD-B2")))]


async def test_r36_creates_the_advice_under_the_lock_in_the_documented_order_with_the_supplied_ids() -> (  # noqa: E501
    None
):
    rig = reserved_rig()

    result = await despatch_creation.create(command(), rig.scope)

    # lock first, then the number, then the stock rows, then the advice and its fact
    assert rig.log == ["lock", "allocate", "save_stock", "save_despatch"]
    assert result.created is True
    [advice] = rig.despatches.saved
    assert advice.id == uid(0xAD), "the first id the application's source handed out"
    assert [ln.id for ln in advice.lines] == [uid(0x11)]
    [fact] = advice.domain_events
    assert isinstance(fact, OrderDespatched)
    assert fact.event_id == uid(0xE5)
    assert fact.correlation_id == uid(0xC0)
    assert fact.causation_id == uid(0xCA)
    assert fact.occurred_at == NOW
    assert fact.despatch_reference == DespatchReference("DES-000031")
    assert result.despatch == advice.to_snapshot(), "the reply is the saved advice"
    assert rig.items["PRD-A1"].reservations[0].status is CONSUMED
    assert rig.ids.queue == [], "exactly the ids the test supplied were used"


async def test_the_reply_is_returned_only_after_run_returns() -> None:
    rig = reserved_rig()
    commit = asyncio.Event()

    async def blocked_commit() -> None:
        await commit.wait()

    rig.transactions.after_work = blocked_commit
    task = asyncio.create_task(despatch_creation.create(command(), rig.scope))
    await asyncio.sleep(0.05)

    assert rig.despatches.saved, "the work ran"
    assert not task.done(), "but there is no reply while the commit is pending"
    commit.set()
    assert (await asyncio.wait_for(task, timeout=5)).created is True


async def test_a_rollback_propagates_and_produces_no_reply() -> None:
    rig = reserved_rig()

    async def failing_commit() -> None:
        raise ConnectionError("the commit failed")

    rig.transactions.after_work = failing_commit

    with pytest.raises(ConnectionError):
        await despatch_creation.create(command(), rig.scope)


async def test_f8_a_repeat_that_raced_the_fast_path_is_answered_by_the_in_lock_re_read() -> None:
    rows = [reservation(0x71, 0xA1, "PRD-A1", CONSUMED)]
    rig = Rig([item("PRD-A1", 0xA1, rows)], rows, existing_in_lock=EXISTING, ids=())

    result = await despatch_creation.create(command(), rig.scope)

    assert result.created is False
    assert result.despatch == EXISTING
    assert rig.log == ["lock", "re-read"], "re-read AFTER the lock; nothing allocated or saved"
    assert rig.numbers.allocations == 0
    assert rig.despatches.saved == []
    assert rig.repository.saves == 0


async def test_consumed_reservations_with_no_advice_are_a_transient_inconsistency_not_a_refusal() -> (  # noqa: E501
    None
):
    rows = [reservation(0x71, 0xA1, "PRD-A1", CONSUMED)]
    rig = Rig([item("PRD-A1", 0xA1, rows)], rows, existing_in_lock=None, ids=())

    with pytest.raises(ConcurrentDespatchChangeError) as raised:
        await despatch_creation.create(command(), rig.scope)

    assert raised.value.order_reference == ORDER
    assert rig.log == ["lock", "re-read"]


async def test_r36_an_order_whose_reservations_were_all_released_is_refused_and_nothing_is_written() -> (  # noqa: E501
    None
):
    rows = [reservation(0x71, 0xA1, "PRD-A1", RELEASED)]
    rig = Rig([item("PRD-A1", 0xA1, rows)], rows, ids=())

    with pytest.raises(NoReservedStockForDespatchError):
        await despatch_creation.create(command(), rig.scope)

    assert rig.log == ["lock"], "no re-read (nothing consumed), no number, no save"
    assert rig.numbers.allocations == 0
    assert rig.despatches.saved == []


async def test_a_reserved_row_the_loaded_items_do_not_hold_despatches_nothing_and_is_refused() -> (
    None
):
    # defensive: the locked reservations list a `reserved` row but the loaded item holds none of
    # the order's reservations, so `consume` finds nothing and no advice may be built
    rows = [reservation(0x71, 0xA1, "PRD-A1", RESERVED)]
    rig = Rig([item("PRD-A1", 0xA1)], rows, ids=())

    with pytest.raises(NoReservedStockForDespatchError):
        await despatch_creation.create(command(), rig.scope)

    assert rig.despatches.saved == []
    assert rig.repository.saves == 0
