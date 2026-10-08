"""`Reservation`: the child entity of a `StockItem`, and its three-status state machine (R35, F4).

`ReservationStatus` is a plain `Enum` (not `StrEnum`): a raw `"reserved"` read from a row never
compares equal to `ReservationStatus.RESERVED` and must be parsed. Tokens are written out, never
derived from member names (the Orders `OrderStatus` convention).

Only `reserved -> released` and `reserved -> consumed` exist. From either terminal, `release()` and
`consume()` raise `ReservationTerminalError` and change nothing. A `Reservation` is reachable only
through its `StockItem`, which exposes frozen `ReservationView`s.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Self

from otc_fulfillment.domain.errors import (
    InvalidStockItemSnapshotError,
    ReservationTerminalError,
    UnknownReservationStatusError,
)
from otc_shared_kernel import Entity, UniqueId


class ReservationStatus(Enum):
    RESERVED = "reserved"
    RELEASED = "released"
    CONSUMED = "consumed"


_BY_TOKEN: dict[str, ReservationStatus] = {
    "reserved": ReservationStatus.RESERVED,
    "released": ReservationStatus.RELEASED,
    "consumed": ReservationStatus.CONSUMED,
}


def parse_reservation_status(token: object) -> ReservationStatus:
    """Exact, case- and whitespace-sensitive; a `str` subclass is refused (`type(...) is str`)."""
    if type(token) is not str or token not in _BY_TOKEN:
        raise UnknownReservationStatusError(token)
    return _BY_TOKEN[token]


@dataclass(frozen=True, slots=True, kw_only=True)
class ReservationView:
    id: UniqueId
    order_reference: str
    retailer_code: str
    units: int
    status: ReservationStatus


class Reservation(Entity):
    __slots__ = ("_order_reference", "_retailer_code", "_status", "_units")

    def __init__(
        self,
        reservation_id: UniqueId,
        *,
        order_reference: str,
        retailer_code: str,
        units: int,
        status: ReservationStatus,
    ) -> None:
        super().__init__(reservation_id)
        self._order_reference = order_reference
        self._retailer_code = retailer_code
        self._units = units
        self._status = status

    @classmethod
    def create(
        cls, *, reservation_id: UniqueId, order_reference: str, retailer_code: str, units: int
    ) -> Self:
        """A new reservation, `reserved`. The caller (`StockItem.reserve`) has checked the units."""
        return cls(
            reservation_id,
            order_reference=order_reference,
            retailer_code=retailer_code,
            units=units,
            status=ReservationStatus.RESERVED,
        )

    @classmethod
    def rehydrate(
        cls,
        *,
        reservation_id: UniqueId,
        order_reference: str,
        retailer_code: str,
        units: int,
        status: ReservationStatus,
    ) -> Self:
        if type(status) is not ReservationStatus:
            raise InvalidStockItemSnapshotError(f"reservation status {status!r} is not a status")
        if type(units) is not int or units < 1:
            raise InvalidStockItemSnapshotError(f"reservation units {units!r} is not positive")
        return cls(
            reservation_id,
            order_reference=order_reference,
            retailer_code=retailer_code,
            units=units,
            status=status,
        )

    @property
    def order_reference(self) -> str:
        return self._order_reference

    @property
    def retailer_code(self) -> str:
        return self._retailer_code

    @property
    def units(self) -> int:
        return self._units

    @property
    def status(self) -> ReservationStatus:
        return self._status

    def release(self) -> None:
        self._move_to(ReservationStatus.RELEASED)

    def consume(self) -> None:
        self._move_to(ReservationStatus.CONSUMED)

    def _move_to(self, target: ReservationStatus) -> None:
        if self._status is not ReservationStatus.RESERVED:
            raise ReservationTerminalError(self._status.value, target.value)
        self._status = target

    def view(self) -> ReservationView:
        return ReservationView(
            id=self.id,
            order_reference=self._order_reference,
            retailer_code=self._retailer_code,
            units=self._units,
            status=self._status,
        )
