"""The ports of the stock store: transactions, the repository, and the lock-free reads.

`StockTransactions.run(work)` opens ONE transaction per attempt and hands `work` a
`StockTransaction`; it may RE-RUN `work` after a deadlock (FS23), so `work` is re-runnable by
construction: everything it needs arrives through `tx` and its own arguments, it builds its
aggregates from rows read in THIS attempt, and it performs no I/O outside the transaction.

No SQLAlchemy type crosses into `application` or `presentation`: a transient store failure is the
application-level `StoreUnavailableError`.
"""

from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from otc_fulfillment.application.messages import StockAvailability, StockPage
from otc_fulfillment.domain.despatch_advice import DespatchAdvice
from otc_fulfillment.domain.snapshot import DespatchSnapshot, ReservationSnapshot
from otc_fulfillment.domain.stock_item import StockItem
from otc_shared_kernel import DespatchReference


class StoreUnavailableError(Exception):
    """A transient store failure (a deadlock victim after its attempts, a lost connection, a lock or
    statement timeout, a pool timeout): answered `UNAVAILABLE`, which the caller retries (FS21)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the stock store is temporarily unavailable ({reason})")
        self.reason = reason


class ConcurrentReservationChangeError(Exception):
    """A reservation of the order sits on a stock row that was not locked: the order changed
    between the pre-read and the lock (defensive, `design.md` 6.3). Transient: `UNAVAILABLE`."""

    def __init__(self, order_reference: str) -> None:
        super().__init__(
            f"order {order_reference} gained a reservation on a stock item that was not locked"
        )
        self.order_reference = order_reference


class ConcurrentDespatchChangeError(Exception):
    """The order's reservations are `consumed` under the lock but no despatch advice exists: the
    state F8's in-lock re-read cannot explain (defensive, `despatch_creation`). Transient:
    `UNAVAILABLE`, so the caller asks again and the fast path or the lock decides."""

    def __init__(self, order_reference: str) -> None:
        super().__init__(
            f"order {order_reference} holds consumed reservations but has no despatch advice"
        )
        self.order_reference = order_reference


def distinct_stock_keys(keys: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    """The lock order (FS19, L3, L4): the distinct `(company_code, product_code)` pairs in
    code-point order, by EXACT equality. No upper-casing: PostgreSQL's deterministic collation is
    case-sensitive, so a code differing only in letter case is a different item (G2). Reserve,
    release, replenish and (feature 18) despatch all lock in this order."""
    return tuple(sorted(set(keys)))


@dataclass(frozen=True, slots=True)
class LockedStock:
    """What the lock protocol returns: the locked items by exact product code, in lock order, and
    ALL of the order's reservations (any status, any product: FS5)."""

    items: dict[str, StockItem]
    reservations_of_order: tuple[ReservationSnapshot, ...]


class StockRepository(Protocol):
    async def lock_for_reserve(
        self, company_code: str, product_codes: Sequence[str], order_reference: str
    ) -> LockedStock: ...

    async def lock_order_items(
        self, order_reference: str, keys: Sequence[tuple[str, str]]
    ) -> LockedStock:
        """The SA-4 lock: the stock rows of every item the order holds a reservation on, each
        `FOR UPDATE` in `distinct_stock_keys` order, then the order's reservations `FOR UPDATE
        ORDER BY id`. Feature 18's `despatch.create` takes the same one."""
        ...

    async def lock_for_replenish(
        self, company_code: str, product_codes: Sequence[str]
    ) -> dict[str, StockItem]: ...

    async def save(self) -> None:
        """Sync every loaded item and its reservations, and drain every item's events into outbox
        rows, all in this transaction."""
        ...


class DespatchRepository(Protocol):
    async def find_by_order_reference(self, order_reference: str) -> DespatchSnapshot | None:
        """The advice of the order, or None. Read INSIDE the transaction after the SA-4 lock, it is
        the F8 in-lock re-read: a new statement under the pinned `READ COMMITTED`, so it sees what a
        concurrent despatch committed while this one waited for the lock (#8 id 54)."""
        ...

    async def save(self, advice: DespatchAdvice) -> None:
        """Insert the advice and its lines (plain INSERTs, never an upsert) and drain its events
        into outbox rows, all in this transaction."""
        ...


class DespatchNumberAllocator(Protocol):
    async def next_reference(self) -> DespatchReference:
        """The next `DES-######`, allocated in the caller's transaction (a rollback burns none)."""
        ...


class StockTransaction(Protocol):
    @property
    def repository(self) -> StockRepository: ...

    @property
    def despatches(self) -> DespatchRepository: ...

    @property
    def despatch_numbers(self) -> DespatchNumberAllocator: ...


class StockTransactions(Protocol):
    async def run[T](self, work: Callable[[StockTransaction], Awaitable[T]]) -> T: ...


class StockReads(Protocol):
    """Reads that hold nothing and write nothing (R31, FS15)."""

    async def availability(
        self, company_code: str, lines: Sequence[tuple[str, int]]
    ) -> StockAvailability: ...

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        company_code: str | None,
        product_code: str | None,
        below_threshold: bool | None,
    ) -> StockPage: ...

    async def stock_keys_of_order(self, order_reference: str) -> tuple[tuple[str, str], ...]:
        """The `(company_code, product_code)` of every stock item the order holds a reservation on,
        in any status (SA-4's step 0, outside any transaction)."""
        ...

    async def despatch_of_order(self, order_reference: str) -> DespatchSnapshot | None:
        """The order's despatch advice, if any (F8's fast path, outside any transaction)."""
        ...
