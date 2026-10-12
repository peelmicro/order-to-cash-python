"""The commands and queries of the Gateway: the closed universe `HandlerRegistry.build` checks
registrations against (zero handlers or two fail the boot)."""

from dataclasses import dataclass
from uuid import UUID

from otc_contracts.generated import openapi
from otc_cqrs import Command, Query
from otc_gateway.application.ports.order_read_model import OrderListFilter
from otc_gateway.application.ports.tokens import IssuedToken


@dataclass(frozen=True, slots=True)
class LoginCommand(Command[IssuedToken]):
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class PlaceOrderCommand(Command[openapi.PlaceOrderResponse]):
    request: openapi.PlaceOrderRequest
    idempotency_key: UUID | None


@dataclass(frozen=True, slots=True)
class CancelOrderCommand(Command[openapi.CancelOrderResponse]):
    order_id: UUID
    note: str | None


@dataclass(frozen=True, slots=True)
class PaymentRegistered:
    response: openapi.RegisterPaymentResponse
    order_id: UUID  # the invoice's order: the x-correlation-id the payment was sent under


# Named apart from Billing's own `RegisterPaymentCommand`: this is the Gateway's request to Billing,
# not Billing's command (and `services/billing/tests/unit/test_no_internal_payment_timer.py` counts
# the constructions of that one).
@dataclass(frozen=True, slots=True)
class RegisterInvoicePaymentCommand(Command[PaymentRegistered]):
    invoice_id: UUID
    request: openapi.RegisterPaymentRequest


@dataclass(frozen=True, slots=True)
class ReplenishStockCommand(Command[openapi.ReplenishStockResponse]):
    request: openapi.ReplenishStockRequest


@dataclass(frozen=True, slots=True)
class GetCurrentUserQuery(Query[openapi.CurrentUser]):
    subject: str


@dataclass(frozen=True, slots=True)
class ListOrdersQuery(Query[openapi.OrderSummaryPage]):
    order_filter: OrderListFilter


@dataclass(frozen=True, slots=True)
class GetOrderQuery(Query[openapi.OrderDetail | openapi.ProjectionPending]):
    order_id: UUID


@dataclass(frozen=True, slots=True)
class ListStockQuery(Query[openapi.StockPage]):
    page: int
    page_size: int
    company_code: str | None
    product_code: str | None
    below_threshold: bool


@dataclass(frozen=True, slots=True)
class ListInvoicesQuery(Query[openapi.InvoicePage]):
    page: int
    page_size: int
    status: str | None
    retailer_code: str | None
    company_code: str | None
    order_reference: str | None
    issued_before_minutes: int | None


@dataclass(frozen=True, slots=True)
class ListCreditsQuery(Query[openapi.CreditPage]):
    page: int
    page_size: int
    retailer_code: str | None
    company_code: str | None


@dataclass(frozen=True, slots=True)
class ListProductsQuery(Query[list[openapi.Product]]):
    include_disabled: bool


@dataclass(frozen=True, slots=True)
class ListRetailersQuery(Query[list[openapi.Party]]):
    include_disabled: bool


@dataclass(frozen=True, slots=True)
class ListCompaniesQuery(Query[list[openapi.Party]]):
    include_disabled: bool
