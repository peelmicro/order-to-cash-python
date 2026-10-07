"""Rows <-> the aggregate (`specs/orders_aggregate/design.md` section 9, column by column).

Codes <-> reference-table ids are resolved by the repository; this module is the pure column
mapping. An `Order` is reached ONLY through `Order.rehydrate` (a stored order is restored, never
re-placed), the totals are written but never read into the aggregate (they are derived from the
lines on every load), and every instant goes through `wire_instant` before it is assigned to a
column: `timestamptz(3)` ROUNDS, the wire TRUNCATES, so the store must receive whole milliseconds
(OI19).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from otc_contracts import wire_instant
from otc_orders.domain.order import Order
from otc_orders.domain.order_line import OrderLine
from otc_orders.domain.snapshot import OrderLineSnapshot, OrderSnapshot
from otc_orders.domain.value_objects.cancellation_reason import parse_cancellation_reason
from otc_orders.domain.value_objects.order_status import parse_order_status
from otc_orders.infrastructure.persistence.models import Order as OrderRow
from otc_orders.infrastructure.persistence.models import OrderItem as OrderItemRow
from otc_shared_kernel import GLN, Money, OrderNumber, Quantity, UniqueId


@dataclass(frozen=True, slots=True)
class OrderReferences:
    """The reference-table facts an order row points at, already resolved to codes."""

    retailer_code: str
    buyer_gln: str
    company_code: str
    supplier_gln: str
    currency: str


@dataclass(frozen=True, slots=True)
class ResolvedIds:
    """The reference-table ids an order is written with."""

    retailer_id: UUID
    company_id: UUID
    currency_id: UUID


def _unique_id(value: UUID) -> UniqueId:
    """asyncpg hands back its own `UUID` subclass (`asyncpg.pgproto.pgproto.UUID`), which the
    domain's `type(...) is uuid.UUID` check refuses (measured); rebuild a plain `uuid.UUID`."""
    return UniqueId(UUID(int=value.int))


def order_row_of(order: Order, ids: ResolvedIds) -> OrderRow:
    """A new `orders` row (insert path). `request_id` stays NULL: it is feature 15's (R62)."""
    return OrderRow(
        id=order.id.value,
        order_reference=order.order_reference.value,
        request_id=None,
        order_date=wire_instant(order.order_date),
        company_id=ids.company_id,
        retailer_id=ids.retailer_id,
        currency_id=ids.currency_id,
        initial_amount=order.initial_amount.amount,
        initial_discount=order.initial_discount.amount,
        total_amount=order.total_amount.amount,
        status=order.status.value,
        cancellation_reason=(
            None if order.cancellation_reason is None else order.cancellation_reason.value
        ),
        notes=order.notes,
        created_at=wire_instant(order.created_at),
        updated_at=wire_instant(order.updated_at),
    )


def apply_to_order_row(row: OrderRow, order: Order) -> None:
    """The columns an update can change (update path). Setting an unchanged value is a no-op."""
    row.order_date = wire_instant(order.order_date)
    row.initial_amount = order.initial_amount.amount
    row.initial_discount = order.initial_discount.amount
    row.total_amount = order.total_amount.amount
    row.status = order.status.value
    row.cancellation_reason = (
        None if order.cancellation_reason is None else order.cancellation_reason.value
    )
    row.notes = order.notes
    row.updated_at = wire_instant(order.updated_at)


def order_item_row_of(order: Order, line: OrderLine, product_id: UUID) -> OrderItemRow:
    """A new `order_items` row. The description column is NOT NULL: `None` is written as `""`."""
    stamped = wire_instant(order.updated_at)
    return OrderItemRow(
        id=line.id.value,
        order_id=order.id.value,
        product_id=product_id,
        description=line.description or "",
        price=line.unit_price.amount,
        quantity=line.quantity.value,
        discount=line.line_discount.amount,
        created_at=stamped,
        updated_at=stamped,
    )


def apply_to_order_item_row(row: OrderItemRow, order: Order, line: OrderLine) -> None:
    """The columns a line change can alter; the product of a line never changes."""
    row.description = line.description or ""
    row.price = line.unit_price.amount
    row.quantity = line.quantity.value
    row.discount = line.line_discount.amount
    row.updated_at = wire_instant(order.updated_at)


def order_of(
    row: OrderRow,
    items: Sequence[tuple[OrderItemRow, str]],
    references: OrderReferences,
) -> Order:
    """Restore an order from its rows. `items` pairs each row with its product code."""
    currency = references.currency
    lines = tuple(
        OrderLineSnapshot(
            id=_unique_id(item.id),
            product_code=product_code,
            description=item.description or None,
            quantity=Quantity(item.quantity),
            unit_price=Money(item.price, currency),
            line_discount=Money(item.discount, currency),
        )
        for item, product_code in items
    )
    return Order.rehydrate(
        OrderSnapshot(
            id=_unique_id(row.id),
            order_reference=OrderNumber.parse(row.order_reference),
            order_date=row.order_date,
            retailer_code=references.retailer_code,
            buyer_gln=GLN(references.buyer_gln),
            company_code=references.company_code,
            supplier_gln=GLN(references.supplier_gln),
            currency=currency,
            status=parse_order_status(row.status),
            cancellation_reason=(
                None
                if row.cancellation_reason is None
                else parse_cancellation_reason(row.cancellation_reason)
            ),
            notes=row.notes,
            lines=lines,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    )
