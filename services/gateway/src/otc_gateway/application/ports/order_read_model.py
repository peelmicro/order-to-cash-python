"""The read-model port: the projector's `order_timeline` documents, READ ONLY (R54).

Plain frozen dataclasses mirror the public part of a document. The three internal fields the
projector keeps (`statusRank`, `processedEventKeys`, `timelineOrderVersion`, `PR33`) are NOT
modelled here, so no application code can carry them to the wire: the adapter reads only the
fields named below (an allow-list at the query) and this module has nowhere to put anything else.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from otc_gateway.domain.issued_order_window import IssuedOrderWindow


@dataclass(frozen=True, slots=True)
class ReadModelParty:
    code: str | None
    name: str | None
    gln: str | None


@dataclass(frozen=True, slots=True)
class ReadModelTotals:
    initial_amount: int | None
    initial_discount: int | None
    total_amount: int | None


@dataclass(frozen=True, slots=True)
class ReadModelItem:
    product_code: str
    name: str | None
    quantity: int
    unit_price: int
    line_discount: int


@dataclass(frozen=True, slots=True)
class ReadModelReferences:
    despatch_reference: str | None
    invoice_reference: str | None
    payment_reference: str | None


@dataclass(frozen=True, slots=True)
class ReadModelEvent:
    event_id: UUID
    causation_id: UUID | None
    event_type: str
    occurred_at: datetime
    summary: str
    detail: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class ReadModelSummary:
    """The header of an order (what the list shows)."""

    order_id: UUID
    order_reference: str | None
    order_date: datetime | None
    retailer: ReadModelParty
    company: ReadModelParty
    status: str
    cancellation_reason: str | None
    currency: str | None
    totals: ReadModelTotals
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReadModelOrder:
    """The whole document (what the detail shows)."""

    header: ReadModelSummary
    items: tuple[ReadModelItem, ...]
    references: ReadModelReferences
    events: tuple[ReadModelEvent, ...]
    header_complete: bool


@dataclass(frozen=True, slots=True)
class OrderListFilter:
    statuses: tuple[str, ...]
    retailer_code: str | None
    company_code: str | None
    order_reference: str | None
    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class ReadModelPage:
    items: tuple[ReadModelSummary, ...]
    total: int


class OrderReadModel(Protocol):
    async def find_by_id(self, order_id: UUID) -> ReadModelOrder | None: ...

    async def find_order_id_by_reference(self, order_reference: str) -> UUID | None: ...

    async def list_orders(self, order_filter: OrderListFilter) -> ReadModelPage:
        """Orders whose header is complete (R53: a placeholder has no `orderReference`, which
        `OrderSummary` requires), newest `orderDate` first. `total` counts the SAME set."""
        ...


class OrderReadScope(Protocol):
    """The ONLY thing the list and detail handlers receive: the read model and the window that
    turns a miss into 202 or 404. It names no RPC client and no write model, so those handlers
    cannot reach one (import-linter `gateway-order-queries-read-model-only`)."""

    @property
    def read_model(self) -> OrderReadModel: ...

    @property
    def issued_orders(self) -> IssuedOrderWindow: ...
