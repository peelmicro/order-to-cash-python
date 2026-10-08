"""The messages of the Fulfillment service and their results: the five stock ones (`design.md` 7.1)
and `despatch.create` (feature 18).

Messages subclass `otc_cqrs.Command[R]` / `Query[R]` (the registry's closed universe); results are
application dataclasses, never `otc_contracts` models: `presentation/stock_wire.py` maps them to
the wire. `ReserveStockCommand` and `ReleaseStockCommand` carry `correlation_id`
(`x-correlation-id`) and `request_id` (`x-request-id`) as `UniqueId`s (FS3); the queries and
replenish carry neither.
"""

from dataclasses import dataclass
from enum import Enum

from otc_cqrs import Command, Query
from otc_fulfillment.domain.events import ReleaseReason, ReservationRef, Shortage
from otc_fulfillment.domain.snapshot import DespatchSnapshot
from otc_shared_kernel import Quantity, UniqueId

# --------------------------------------------------------------------------------------- shared


@dataclass(frozen=True, slots=True)
class StockLine:
    product_code: str
    units: Quantity


@dataclass(frozen=True, slots=True)
class StockViewData:
    company_code: str
    product_code: str
    units: int
    reserved_units: int
    low_stock_threshold: int

    @property
    def available_units(self) -> int:
        return self.units - self.reserved_units


# ---------------------------------------------------------------------------------- stock.check


@dataclass(frozen=True, slots=True)
class CheckLine:
    product_code: str
    requested: int


@dataclass(frozen=True, slots=True)
class LineAvailability:
    product_code: str
    requested: int
    available: int
    sufficient: bool


@dataclass(frozen=True, slots=True)
class StockAvailability:
    available: bool
    lines: tuple[LineAvailability, ...]


@dataclass(frozen=True, slots=True)
class CheckStockQuery(Query[StockAvailability]):
    company_code: str
    lines: tuple[CheckLine, ...]


# ----------------------------------------------------------------------------------- stock.list


@dataclass(frozen=True, slots=True)
class StockPage:
    items: tuple[StockViewData, ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class ListStockQuery(Query[StockPage]):
    page: int
    page_size: int
    company_code: str | None
    product_code: str | None
    below_threshold: bool | None


# -------------------------------------------------------------------------------- stock.reserve


class ReserveOutcomeKind(Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ALREADY_RESERVED = "already_reserved"


@dataclass(frozen=True, slots=True)
class ReserveResult:
    outcome: ReserveOutcomeKind
    order_reference: str
    reservations: tuple[ReservationRef, ...] | None = None
    shortages: tuple[Shortage, ...] | None = None


@dataclass(frozen=True, slots=True)
class ReserveStockCommand(Command[ReserveResult]):
    order_reference: str
    company_code: str
    retailer_code: str
    lines: tuple[StockLine, ...]
    correlation_id: UniqueId
    request_id: UniqueId


# -------------------------------------------------------------------------------- stock.release


class ReleaseOutcomeKind(Enum):
    RELEASED = "released"
    ALREADY_RELEASED = "already_released"


@dataclass(frozen=True, slots=True)
class ReleaseResult:
    outcome: ReleaseOutcomeKind
    order_reference: str
    released: tuple[ReservationRef, ...]


@dataclass(frozen=True, slots=True)
class ReleaseStockCommand(Command[ReleaseResult]):
    order_reference: str
    reason: ReleaseReason
    correlation_id: UniqueId
    request_id: UniqueId


# ------------------------------------------------------------------------------ stock.replenish


@dataclass(frozen=True, slots=True)
class ReplenishResult:
    items: tuple[StockViewData, ...]


@dataclass(frozen=True, slots=True)
class ReplenishStockCommand(Command[ReplenishResult]):
    company_code: str
    lines: tuple[StockLine, ...]


# ----------------------------------------------------------------------------- despatch.create


@dataclass(frozen=True, slots=True)
class DespatchResult:
    """The despatch advice of the order and whether THIS command created it (`created`); a repeat
    (F8) carries the existing advice and `created=False`."""

    created: bool
    despatch: DespatchSnapshot


@dataclass(frozen=True, slots=True)
class CreateDespatchCommand(Command[DespatchResult]):
    order_reference: str
    correlation_id: UniqueId
    request_id: UniqueId
