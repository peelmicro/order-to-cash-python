"""`PlaceOrderCommand` and its handler (saga.md 3.1 step 0; `orders_aggregate` design 5.4, 10).

The handler's order is the design: refuse an order discount, resolve reference data, make the
synchronous stock check, and ONLY THEN open the unit of work. Everything before `begin()` holds no
transaction, so a refusal there leaves nothing to roll back and emits no fact. Inside the
transaction: allocate the `ORD-######` (so a rollback returns the number), one aggregate call
(`Order.place`), one `save`. It validates nothing the aggregate validates (currency format, line
currencies, totals): those refusals are the aggregate's `DomainError`s, mapped by the presentation.

Three error vocabularies coexist here on purpose (#8 A5): this module's `PlaceOrderError.code`
values (`SCREAMING_CASE`) are internal discriminators that never reach the wire (the presentation
maps by TYPE); the domain's `<subject>.<snake_case>` codes reach the wire only as
`RpcError.details.code`; the wire's own `code` is the closed `RpcError` enum of `asyncapi.yaml`.

Clock and causation are supplied here, never read by the domain.

`request_id` makes the command idempotent (R62, `observability_reliability` design 3). A known one
is answered from the stored order before any reference data or stock is touched (RI2); a first one
is stored under `uq_orders_request_id` (RI1) and becomes the `causationId` of `order.placed.v1`
(RI5); a concurrent first request that loses the race meets the unit of work's
`RequestIdAlreadyPlacedError` AFTER its rollback (PostgreSQL aborts the whole transaction on any
error, so the collision cannot be caught inside it) and is resolved here, outside the block, to the
winner's reply (RI3). With no `request_id` nothing is looked up (RI4).
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from otc_cqrs import Command
from otc_orders.application.ports.stock_availability import (
    StockAvailabilityLine,
    StockAvailabilityLineResult,
)
from otc_orders.application.ports.unit_of_work import RequestIdAlreadyPlacedError
from otc_orders.application.scope import OrdersScope
from otc_orders.domain.order import Order
from otc_orders.domain.order_line import OrderLineInput
from otc_shared_kernel import Money, OrderNumber, Quantity, UniqueId, format_money


@dataclass(frozen=True, slots=True)
class PlaceOrderLine:
    product_code: str
    quantity: Quantity
    unit_price: int | None  # minor units; None -> the catalogue price is snapshotted
    line_discount: int | None  # minor units; None -> zero


@dataclass(frozen=True, slots=True)
class PlaceOrderResult:
    order_id: UniqueId
    order_reference: OrderNumber
    currency: str
    initial_amount: Money
    initial_discount: Money
    total_amount: Money
    order_date: datetime


@dataclass(frozen=True, slots=True)
class PlaceOrderCommand(Command[PlaceOrderResult]):
    request_id: UUID | None
    retailer_code: str
    company_code: str
    currency: str
    lines: tuple[PlaceOrderLine, ...]
    order_discount: int | None
    notes: str | None


class PlaceOrderError(Exception):
    """An application-layer refusal of a request; `code` is stable."""

    code = "PLACE_ORDER_REFUSED"


class ReferenceDataNotFoundError(PlaceOrderError):
    code = "REFERENCE_DATA_NOT_FOUND"

    def __init__(self, field: str, value: str) -> None:
        super().__init__(f'{field} "{value}" does not resolve to a known reference row.')
        self.field = field
        self.value = value


class StockUnavailableError(PlaceOrderError):
    code = "STOCK_UNAVAILABLE"

    def __init__(self, shortages: tuple[StockAvailabilityLineResult, ...]) -> None:
        listed = ", ".join(
            f"{s.product_code} (requested {s.requested}, available {s.available})"
            for s in shortages
        )
        super().__init__(f"Stock check reports {len(shortages)} short line(s): {listed}")
        self.shortages = shortages


class OrderDiscountNotSupportedError(PlaceOrderError):
    code = "ORDER_DISCOUNT_NOT_SUPPORTED"

    def __init__(self, order_discount: int, currency: str) -> None:
        # Human text scales by the currency's ISO 4217 exponent (SA-5): never `500` for 5.00 EUR.
        super().__init__(
            f"orderDiscount {format_money(order_discount, currency)} was supplied, but the Order "
            "aggregate carries no order-level discount: use a per-line lineDiscount instead."
        )
        self.order_discount = order_discount


def _result_of(order: Order) -> PlaceOrderResult:
    """The reply, built from the aggregate by the one projection both paths use (no second one)."""
    return PlaceOrderResult(
        order_id=order.id,
        order_reference=order.order_reference,
        currency=order.currency,
        initial_amount=order.initial_amount,
        initial_discount=order.initial_discount,
        total_amount=order.total_amount,
        order_date=order.order_date,
    )


class PlaceOrderCommandHandler:
    def __init__(self, scope: OrdersScope) -> None:
        self._scope = scope

    async def handle(self, command: PlaceOrderCommand, /) -> PlaceOrderResult:
        if command.order_discount is not None and command.order_discount != 0:
            raise OrderDiscountNotSupportedError(command.order_discount, command.currency)
        if command.request_id is not None:
            replay = await self._original_reply(command.request_id)
            if replay is not None:
                return replay
        try:
            return await self._place(command)
        except RequestIdAlreadyPlacedError as collision:
            # outside the rolled-back block (RI3): re-read the winner in a NEW transaction
            winner = None
            if command.request_id is not None:
                winner = await self._original_reply(command.request_id)
            if winner is None:
                # no readable winner: never a silent None, never a second order
                raise collision.__cause__ or collision from None
            return winner

    async def _original_reply(self, request_id: UUID) -> PlaceOrderResult | None:
        async with self._scope.unit_of_work.begin() as transaction:
            stored = await transaction.orders.find_by_request_id(request_id)
        return None if stored is None else _result_of(stored)

    async def _place(self, command: PlaceOrderCommand) -> PlaceOrderResult:
        scope = self._scope

        retailer = await scope.catalog.find_retailer(command.retailer_code)
        if retailer is None:
            raise ReferenceDataNotFoundError("retailerCode", command.retailer_code)
        company = await scope.catalog.find_company(command.company_code)
        if company is None:
            raise ReferenceDataNotFoundError("companyCode", command.company_code)
        if not await scope.catalog.currency_exists(command.currency):
            raise ReferenceDataNotFoundError("currency", command.currency)
        products = await scope.catalog.find_products(
            tuple(dict.fromkeys(line.product_code for line in command.lines))
        )
        for line in command.lines:
            if line.product_code not in products:
                raise ReferenceDataNotFoundError("productCode", line.product_code)

        # Before anything is persisted (R31). A transport failure, a timeout or the responder's own
        # error propagates typed and is mapped by the presentation; no transaction is open here.
        stock = await scope.stock.check(
            command.company_code,
            [StockAvailabilityLine(line.product_code, line.quantity) for line in command.lines],
        )
        if not stock.available:
            raise StockUnavailableError(tuple(s for s in stock.lines if not s.sufficient))

        async with scope.unit_of_work.begin() as transaction:
            order_reference = await transaction.order_numbers.next_number()
            now = scope.clock.now()
            inputs = []
            for line in command.lines:
                product = products[line.product_code]
                inputs.append(
                    OrderLineInput(
                        product_code=line.product_code,
                        description=product.description,
                        quantity=line.quantity,
                        unit_price=(
                            product.price
                            if line.unit_price is None
                            else Money(line.unit_price, command.currency)
                        ),
                        line_discount=Money(line.line_discount or 0, command.currency),
                    )
                )
            order = Order.place(
                order_reference=order_reference,
                order_date=now,
                retailer_code=retailer.code,
                buyer_gln=retailer.gln,
                company_code=company.code,
                supplier_gln=company.gln,
                currency=command.currency,
                lines=inputs,
                notes=command.notes,
                occurred_at=now,
                causation_id=(
                    UniqueId(command.request_id)
                    if command.request_id is not None
                    else UniqueId.new()
                ),
            )
            await transaction.orders.save(order, request_id=command.request_id)
            return _result_of(order)
