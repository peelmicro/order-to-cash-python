"""E4: the reserve and release transactional units, over fakes of the ports.

FS5 (a reservation in ANY status answers `already_reserved`: no domain call, nothing saved), the
reply only after `run()` returns, a rollback producing no reply, FS9 (an order with no reservation
answers without a transaction) and the no-carrier branch. The fixture's requested units ARE
satisfiable, so a handler that filtered by status would reserve (#7's rejection).
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

import pytest

from otc_fulfillment.application import stock_reservation
from otc_fulfillment.application.messages import (
    ReleaseOutcomeKind,
    ReleaseStockCommand,
    ReserveOutcomeKind,
    ReserveStockCommand,
    StockLine,
)
from otc_fulfillment.application.ports.stock_store import LockedStock, StockTransaction
from otc_fulfillment.application.scope import FulfillmentScope
from otc_fulfillment.application.stock_reservation import NoKnownStockItemError
from otc_fulfillment.domain.events import (
    ReleaseReason,
    ReservationRef,
    StockReleased,
    StockReserved,
)
from otc_fulfillment.domain.reservation import ReservationStatus
from otc_fulfillment.domain.snapshot import ReservationSnapshot, StockItemSnapshot
from otc_fulfillment.domain.stock_item import StockItem
from otc_shared_kernel import Quantity, UniqueId

NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)
ORDER = "ORD-000042"


def uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(int=n))


def item(code: str, number: int, *, units: int = 50, reserved: int = 0) -> StockItem:
    return StockItem.rehydrate(
        StockItemSnapshot(
            id=uid(number),
            company_code="ACME-CO",
            product_code=code,
            units=units,
            reserved_units=reserved,
            low_stock_threshold=2,
            reservations=(),
        )
    )


def existing(status: ReservationStatus) -> ReservationSnapshot:
    return ReservationSnapshot(
        id=uid(0x71),
        stock_id=uid(0xA1),
        product_code="PRD-A1",
        order_reference=ORDER,
        retailer_code="RET-9",
        units=3,
        status=status,
    )


class FakeRepository:
    def __init__(self, locked: LockedStock) -> None:
        self.locked = locked
        self.saves = 0
        self.lock_calls: list[object] = []

    async def lock_for_reserve(
        self, company_code: str, codes: Sequence[str], ref: str
    ) -> LockedStock:
        self.lock_calls.append((company_code, tuple(codes), ref))
        return self.locked

    async def lock_order_items(self, ref: str, keys: Sequence[tuple[str, str]]) -> LockedStock:
        self.lock_calls.append((ref, tuple(keys)))
        return self.locked

    async def save(self) -> None:
        self.saves += 1


class FakeTransactions:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self.runs = 0
        self.after_work: Callable[[], Awaitable[None]] | None = None

    async def run[T](self, work: Callable[[StockTransaction], Awaitable[T]]) -> T:
        self.runs += 1
        result = await work(self)  # type: ignore[arg-type]
        if self.after_work is not None:
            await self.after_work()  # the commit: may block, or fail (a rollback)
        return result


class FakeReads:
    def __init__(self, keys: tuple[tuple[str, str], ...]) -> None:
        self.keys = keys
        self.calls = 0

    async def stock_keys_of_order(self, ref: str) -> tuple[tuple[str, str], ...]:
        self.calls += 1
        return self.keys


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeIds:
    def __init__(self) -> None:
        self.minted = 0

    def new(self) -> UniqueId:
        self.minted += 1
        return uid(0x9000 + self.minted)


class Rig:
    def __init__(
        self,
        items: Sequence[StockItem],
        reservations: tuple[ReservationSnapshot, ...] = (),
        keys: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.items = {i.product_code: i for i in items}
        self.repository = FakeRepository(
            LockedStock(items=self.items, reservations_of_order=reservations)
        )
        self.transactions = FakeTransactions(self.repository)
        self.reads = FakeReads(keys)
        self.ids = FakeIds()
        self.scope = FulfillmentScope(
            transactions=self.transactions,
            reads=self.reads,  # type: ignore[arg-type]
            clock=FakeClock(),
            ids=self.ids,
        )


def reserve_command(*lines: tuple[str, int]) -> ReserveStockCommand:
    return ReserveStockCommand(
        order_reference=ORDER,
        company_code="ACME-CO",
        retailer_code="RET-9",
        lines=tuple(StockLine(product_code=c, units=Quantity(n)) for c, n in lines),
        correlation_id=uid(0xC0),
        request_id=uid(0xCA),
    )


def release_command() -> ReleaseStockCommand:
    return ReleaseStockCommand(
        order_reference=ORDER,
        reason=ReleaseReason.ORDER_CANCELLED,
        correlation_id=uid(0xC0),
        request_id=uid(0xCA),
    )


@pytest.mark.parametrize("status", [ReservationStatus.RELEASED, ReservationStatus.CONSUMED])
async def test_fs5_short_circuits_to_already_reserved_on_a_reservation_in_any_status_calling_no_domain_function_and_saving_nothing(  # noqa: E501
    status: ReservationStatus,
) -> None:
    stocked = item("PRD-A1", 0xA1, units=50)  # 50 units: the requested 4 ARE satisfiable
    before = stocked.to_snapshot()
    rig = Rig([stocked], reservations=(existing(status),))

    result = await stock_reservation.reserve(reserve_command(("PRD-A1", 4)), rig.scope)

    assert result.outcome is ReserveOutcomeKind.ALREADY_RESERVED
    # the reply's refs equal the EXISTING rows exactly (3 units, not the 4 requested)
    assert result.reservations == (
        ReservationRef(reservation_id=uid(0x71), product_code="PRD-A1", units=3),
    )
    assert result.shortages is None
    assert rig.repository.saves == 0
    # "no domain function ran" is carried by the item itself, NOT by the id port (M1 showed the
    # port is blind when the handler bypasses it): a domain call would have added a reservation
    # row to the snapshot and recorded a fact on the item.
    assert stocked.to_snapshot() == before, "counters, reservations and statuses untouched"
    assert stocked.reservations == (), "no reservation was added"
    assert stocked.domain_events == (), "no fact was recorded"


async def test_the_reply_is_returned_only_after_run_returns() -> None:
    rig = Rig([item("PRD-A1", 0xA1)])
    commit = asyncio.Event()

    async def blocked_commit() -> None:
        await commit.wait()

    rig.transactions.after_work = blocked_commit
    task = asyncio.create_task(stock_reservation.reserve(reserve_command(("PRD-A1", 4)), rig.scope))
    await asyncio.sleep(0.05)

    assert rig.repository.saves == 1, "the work ran"
    assert not task.done(), "but there is no reply while the commit is pending"
    commit.set()
    result = await asyncio.wait_for(task, timeout=5)
    assert result.outcome is ReserveOutcomeKind.ACCEPTED


async def test_a_rollback_propagates_and_produces_no_reply() -> None:
    rig = Rig([item("PRD-A1", 0xA1)])

    async def failing_commit() -> None:
        raise ConnectionError("the commit failed")

    rig.transactions.after_work = failing_commit

    with pytest.raises(ConnectionError):
        await stock_reservation.reserve(reserve_command(("PRD-A1", 4)), rig.scope)


async def test_a_rejection_is_a_result_saved_once_never_a_raise() -> None:
    rig = Rig([item("PRD-A1", 0xA1, units=2)])

    result = await stock_reservation.reserve(reserve_command(("PRD-A1", 4)), rig.scope)

    assert result.outcome is ReserveOutcomeKind.REJECTED
    assert result.shortages is not None
    assert rig.repository.saves == 1, "the rejected fact's outbox row needs the save (#8 D1)"


async def test_fs9_an_order_with_no_reservation_answers_already_released_without_calling_run() -> (
    None
):
    rig = Rig([], keys=())

    result = await stock_reservation.release(release_command(), rig.scope)

    assert result.outcome is ReleaseOutcomeKind.ALREADY_RELEASED
    assert result.released == ()
    assert rig.reads.calls == 1
    assert rig.transactions.runs == 0, "no transaction is opened"
    assert rig.repository.saves == 0


async def test_a_release_runs_under_the_lock_and_saves_once() -> None:
    held = StockItem.rehydrate(
        StockItemSnapshot(
            id=uid(0xA1),
            company_code="ACME-CO",
            product_code="PRD-A1",
            units=50,
            reserved_units=3,
            low_stock_threshold=2,
            reservations=(existing(ReservationStatus.RESERVED),),
        )
    )
    rig = Rig([held], keys=(("ACME-CO", "PRD-A1"),))

    result = await stock_reservation.release(release_command(), rig.scope)

    assert result.outcome is ReleaseOutcomeKind.RELEASED
    assert result.released == (
        ReservationRef(reservation_id=uid(0x71), product_code="PRD-A1", units=3),
    )
    assert rig.repository.saves == 1
    assert rig.repository.lock_calls == [(ORDER, (("ACME-CO", "PRD-A1"),))]


async def test_a_release_of_only_released_reservations_saves_nothing() -> None:
    held = StockItem.rehydrate(
        StockItemSnapshot(
            id=uid(0xA1),
            company_code="ACME-CO",
            product_code="PRD-A1",
            units=50,
            reserved_units=0,
            low_stock_threshold=2,
            reservations=(existing(ReservationStatus.RELEASED),),
        )
    )
    rig = Rig([held], keys=(("ACME-CO", "PRD-A1"),))

    result = await stock_reservation.release(release_command(), rig.scope)

    assert result.outcome is ReleaseOutcomeKind.ALREADY_RELEASED
    assert rig.repository.saves == 0


async def test_no_carrier_raises_no_known_stock_item_and_saves_nothing() -> None:
    rig = Rig([item("PRD-A1", 0xA1)])  # the request names only a product with no item

    with pytest.raises(NoKnownStockItemError) as refusal:
        await stock_reservation.reserve(reserve_command(("PRD-Z9", 4)), rig.scope)

    assert refusal.value.order_reference == ORDER
    assert rig.repository.saves == 0


async def test_fs24_the_reserve_uses_the_id_port_for_every_reservation_id_and_the_reserved_facts_event_id() -> (  # noqa: E501
    None
):
    stocked_a = item("PRD-A1", 0xA1)
    stocked_b = item("PRD-B2", 0xB2)
    rig = Rig([stocked_a, stocked_b])

    result = await stock_reservation.reserve(
        reserve_command(("PRD-A1", 4), ("PRD-B2", 6)), rig.scope
    )

    assert result.outcome is ReserveOutcomeKind.ACCEPTED
    # FakeIds mints uid(0x9001), uid(0x9002), ... in order: two reservations, then the fact
    assert result.reservations is not None
    assert [ref.reservation_id for ref in result.reservations] == [uid(0x9001), uid(0x9002)]
    assert [v.id for v in stocked_a.reservations + stocked_b.reservations] == [
        uid(0x9001),
        uid(0x9002),
    ]
    [fact] = stocked_a.domain_events
    assert isinstance(fact, StockReserved)
    assert fact.event_id == uid(0x9003), "the reserved fact's event id comes from the id port"
    assert rig.ids.minted == 3


async def test_fs24_the_release_uses_the_id_port_for_the_released_facts_event_id() -> None:
    held = StockItem.rehydrate(
        StockItemSnapshot(
            id=uid(0xA1),
            company_code="ACME-CO",
            product_code="PRD-A1",
            units=50,
            reserved_units=3,
            low_stock_threshold=2,
            reservations=(existing(ReservationStatus.RESERVED),),
        )
    )
    rig = Rig([held], keys=(("ACME-CO", "PRD-A1"),))

    result = await stock_reservation.release(release_command(), rig.scope)

    assert result.outcome is ReleaseOutcomeKind.RELEASED
    [fact] = held.domain_events
    assert isinstance(fact, StockReleased)
    assert fact.event_id == uid(0x9001), "the released fact's event id comes from the id port"
    assert rig.ids.minted == 1
