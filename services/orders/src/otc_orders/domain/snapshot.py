"""What `Order.rehydrate` takes: a stored order as business values, with no totals (L16).

Built by the repository's row mapper (feature 15); keyword-constructed. The three totals are
derived from the lines on every load, so no field for them exists.
"""

from dataclasses import dataclass
from datetime import datetime

from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import GLN, Money, OrderNumber, Quantity, UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderLineSnapshot:
    id: UniqueId
    product_code: str
    description: str | None
    quantity: Quantity
    unit_price: Money
    line_discount: Money


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderSnapshot:
    id: UniqueId
    order_reference: OrderNumber
    order_date: datetime
    retailer_code: str
    buyer_gln: GLN
    company_code: str
    supplier_gln: GLN
    currency: str
    status: OrderStatus
    cancellation_reason: CancellationReason | None
    notes: str | None
    lines: tuple[OrderLineSnapshot, ...]
    created_at: datetime
    updated_at: datetime
