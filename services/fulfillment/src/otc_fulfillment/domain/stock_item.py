"""The `StockItem` aggregate root: one product's on-hand and reserved units, with the reservations
loaded for the order being handled (`design.md` 5.1; F1, F2, F4, F5; R30, R35, R61).

Synchronous and pure: no I/O, no clock, no width arithmetic (Python's `int` is exact and unbounded;
the `integer` column's width is the write boundary's concern, L5).

* F1 (`reserved_units <= units`): `reserve` refuses by SUBTRACTION (`requested > units -
  reserved_units`); `rehydrate` refuses a stored row that breaks it.
* F2: `reserved_units` is never assigned from outside; every change sits beside the reservation
  change it describes.
* Every mutation is all-or-nothing within the call: compute, check, THEN assign. A raised error
  leaves the aggregate unchanged (the R30 / R35 / FS10 tests compare `to_snapshot()` before and
  after).
"""

from typing import Self

from otc_fulfillment.domain.errors import (
    FactAggregateMismatchError,
    InsufficientStockError,
    InvalidStockItemSnapshotError,
    ReservationTerminalError,
)
from otc_fulfillment.domain.events import StockEvent
from otc_fulfillment.domain.reservation import Reservation, ReservationStatus, ReservationView
from otc_fulfillment.domain.snapshot import ReservationSnapshot, StockItemSnapshot
from otc_shared_kernel import AggregateRoot, Quantity, UniqueId


def _require_count(name: str, value: object) -> int:
    if type(value) is not int:
        raise InvalidStockItemSnapshotError(f"{name} {value!r} is not an int")
    if value < 0:
        raise InvalidStockItemSnapshotError(f"{name} {value} is negative")
    return value


class StockItem(AggregateRoot):
    __slots__ = (
        "_company_code",
        "_low_stock_threshold",
        "_product_code",
        "_reservations",
        "_reserved_units",
        "_units",
    )

    def __init__(
        self,
        item_id: UniqueId,
        *,
        company_code: str,
        product_code: str,
        units: int,
        reserved_units: int,
        low_stock_threshold: int,
        reservations: list[Reservation],
    ) -> None:
        super().__init__(item_id)
        self._company_code = company_code
        self._product_code = product_code
        self._units = units
        self._reserved_units = reserved_units
        self._low_stock_threshold = low_stock_threshold
        self._reservations = reservations

    @classmethod
    def rehydrate(cls, snapshot: StockItemSnapshot) -> Self:
        """Restore a stored item. Bypasses the operations and raises no event.

        Refuses: a non-`int` or negative count, `reserved_units > units` (F1), and a reservation
        that belongs to another item (another stock id or another product). The stored counter is
        trusted (it is the authoritative cache): only the order's reservations are loaded, so the
        sum cannot be re-derived here.
        """
        units = _require_count("units", snapshot.units)
        reserved_units = _require_count("reserved_units", snapshot.reserved_units)
        threshold = _require_count("low_stock_threshold", snapshot.low_stock_threshold)
        if reserved_units > units:
            raise InvalidStockItemSnapshotError(
                f"reserved_units {reserved_units} exceeds units {units}"
            )
        loaded: list[Reservation] = []
        for stored in snapshot.reservations:
            if stored.stock_id != snapshot.id:
                raise InvalidStockItemSnapshotError(
                    f"reservation {stored.id} belongs to stock item {stored.stock_id}, "
                    f"not {snapshot.id}"
                )
            if stored.product_code != snapshot.product_code:
                raise InvalidStockItemSnapshotError(
                    f"reservation {stored.id} is for product {stored.product_code!r}, "
                    f"not {snapshot.product_code!r}"
                )
            loaded.append(
                Reservation.rehydrate(
                    reservation_id=stored.id,
                    order_reference=stored.order_reference,
                    retailer_code=stored.retailer_code,
                    units=stored.units,
                    status=stored.status,
                )
            )
        return cls(
            snapshot.id,
            company_code=snapshot.company_code,
            product_code=snapshot.product_code,
            units=units,
            reserved_units=reserved_units,
            low_stock_threshold=threshold,
            reservations=loaded,
        )

    @property
    def company_code(self) -> str:
        return self._company_code

    @property
    def product_code(self) -> str:
        return self._product_code

    @property
    def units(self) -> int:
        return self._units

    @property
    def reserved_units(self) -> int:
        return self._reserved_units

    @property
    def low_stock_threshold(self) -> int:
        return self._low_stock_threshold

    @property
    def available_units(self) -> int:
        return self._units - self._reserved_units

    @property
    def reservations(self) -> tuple[ReservationView, ...]:
        return tuple(r.view() for r in self._reservations)

    def can_reserve(self, units: int) -> bool:
        """The pure question `stock.check` asks (R31's shape): would `units` fit right now?"""
        return units <= self.available_units

    def reserve(
        self,
        *,
        reservation_id: UniqueId,
        order_reference: str,
        retailer_code: str,
        units: Quantity,
    ) -> Reservation:
        """One new `reserved` reservation, `reserved_units` up by its units (R30, F1)."""
        if units.value > self.available_units:
            raise InsufficientStockError(self._product_code, units.value, self.available_units)
        reservation = Reservation.create(
            reservation_id=reservation_id,
            order_reference=order_reference,
            retailer_code=retailer_code,
            units=units.value,
        )
        self._reservations.append(reservation)
        self._reserved_units = self._reserved_units + units.value
        return reservation

    def release(self, order_reference: str) -> tuple[Reservation, ...]:
        """Move this item's `reserved` reservations of the order to `released`, subtracting their
        units; empty when none was `reserved` (F5). A `consumed` reservation of the order raises
        `ReservationTerminalError` and nothing moves (F4, FS10): it is checked BEFORE any change."""
        mine = [r for r in self._reservations if r.order_reference == order_reference]
        if any(r.status is ReservationStatus.CONSUMED for r in mine):
            raise ReservationTerminalError(
                ReservationStatus.CONSUMED.value, ReservationStatus.RELEASED.value
            )
        moving = [r for r in mine if r.status is ReservationStatus.RESERVED]
        total = sum(r.units for r in moving)
        for reservation in moving:
            reservation.release()
        self._reserved_units = self._reserved_units - total
        return tuple(moving)

    def consume(self, order_reference: str) -> tuple[Reservation, ...]:
        """Move this item's `reserved` reservations of the order to `consumed`, subtracting their
        total from BOTH `units` and `reserved_units` (FS11). Appends no event."""
        moving = [
            r
            for r in self._reservations
            if r.order_reference == order_reference and r.status is ReservationStatus.RESERVED
        ]
        total = sum(r.units for r in moving)
        for reservation in moving:
            reservation.consume()
        self._units = self._units - total
        self._reserved_units = self._reserved_units - total
        return tuple(moving)

    def replenish(self, quantity: Quantity) -> None:
        """Add on-hand units only (R61): `reserved_units` and every reservation are untouched and
        no domain event is appended. No width check here: Python's `int` does not wrap (L5)."""
        self._units = self._units + quantity.value

    def record_order_fact(self, fact: StockEvent) -> None:
        """Append an order-scoped fact on this item (the carrier, FS13). Refuses a fact whose
        `aggregate_id` is not this item's own."""
        if fact.aggregate_id != self.id:
            raise FactAggregateMismatchError(self.id, fact.aggregate_id)
        self._raise_event(fact)

    def to_snapshot(self) -> StockItemSnapshot:
        return StockItemSnapshot(
            id=self.id,
            company_code=self._company_code,
            product_code=self._product_code,
            units=self._units,
            reserved_units=self._reserved_units,
            low_stock_threshold=self._low_stock_threshold,
            reservations=tuple(
                ReservationSnapshot(
                    id=r.id,
                    stock_id=self.id,
                    product_code=self._product_code,
                    order_reference=r.order_reference,
                    retailer_code=r.retailer_code,
                    units=r.units,
                    status=r.status,
                )
                for r in self._reservations
            ),
        )
