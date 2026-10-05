# GENERATED FILE - DO NOT EDIT.
# Regenerate with `uv run python scripts/generate_contracts.py`.
# Source: specs/shared/openapi.yaml sha256-prefix16=8dd55cf5f16f2b50
# Generator: datamodel-code-generator 0.83.0, generate_contracts.py
# `quality.sh` section 5 fails when this file differs from a fresh generation.

from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, RootModel

from otc_contracts.wire import WireModel


class Money(WireModel):
    amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]


class DespatchReference(RootModel[str]):
    root: Annotated[str, Field(pattern="^DES-[0-9]{6,}$")]


class InvoiceReference(RootModel[str]):
    root: Annotated[str, Field(pattern="^INV-[0-9]{6,}$")]


class PaymentReference(RootModel[str]):
    root: Annotated[str, Field(max_length=30, min_length=1)]


class OrderStatus(StrEnum):
    placed = "placed"
    stock_reserved = "stock_reserved"
    credit_approved = "credit_approved"
    confirmed = "confirmed"
    despatched = "despatched"
    invoiced = "invoiced"
    paid = "paid"
    completed = "completed"
    cancelled = "cancelled"


class CancellationReason(StrEnum):
    stock_rejected = "stock_rejected"
    credit_rejected = "credit_rejected"
    operator_cancelled = "operator_cancelled"


class InvoiceStatus(StrEnum):
    issued = "issued"
    paid = "paid"


class PaymentSource(StrEnum):
    operator = "operator"
    robot = "robot"
    test = "test"


class Party(WireModel):
    code: Annotated[str, Field(max_length=20, min_length=1)]
    name: str
    country: Annotated[str, Field(pattern="^[A-Z]{2}$")]
    vat: str | None = None
    gln: Annotated[str, Field(pattern="^[0-9]{13}$")]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    enabled: bool


class Product(WireModel):
    code: Annotated[str, Field(max_length=30, min_length=1)]
    ean: Annotated[str | None, Field(pattern="^[0-9]{13}$")] = None
    name: str
    description: str | None = None
    price: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    enabled: bool


class PageInfo(WireModel):
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1)]
    total: Annotated[int, Field(ge=0)]


class LoginRequest(WireModel):
    username: str
    password: str


class LoginResponse(WireModel):
    access_token: str
    token_type: Literal["Bearer"]
    expires_in: Annotated[int, Field(ge=1)]


class CurrentUser(WireModel):
    username: str
    display_name: str | None = None
    roles: list[str]


class PlaceOrderLine(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    quantity: Annotated[int, Field(ge=1)]
    unit_price: Annotated[int | None, Field(ge=-9223372036854775808, le=9223372036854775807)] = None
    line_discount: Annotated[int | None, Field(ge=-9223372036854775808, le=9223372036854775807)] = (
        None
    )


class PlaceOrderResponse(WireModel):
    order_id: UUID
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    status: Literal["placed"]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    initial_amount: Annotated[
        int | None, Field(ge=-9223372036854775808, le=9223372036854775807)
    ] = None
    initial_discount: Annotated[
        int | None, Field(ge=-9223372036854775808, le=9223372036854775807)
    ] = None
    total_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    order_date: AwareDatetime
    projection_pending: bool | None = None


class CancelOrderRequest(WireModel):
    note: str | None = None


class CompensationPlannedEnum(StrEnum):
    credit_release = "credit_release"
    stock_release = "stock_release"


class CancelOrderResponse(WireModel):
    order_id: UUID
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    status: OrderStatus
    cancellation_reason: Literal["operator_cancelled"] | None = None
    compensation_planned: list[CompensationPlannedEnum]


class PartyRef(WireModel):
    code: Annotated[str, Field(max_length=20, min_length=1)]
    name: str | None = None
    gln: Annotated[str, Field(pattern="^[0-9]{13}$")]


class OrderTotals(WireModel):
    initial_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    initial_discount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    total_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]


class OrderItem(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    name: str | None = None
    quantity: Annotated[int, Field(ge=1)]
    unit_price: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    line_discount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]


class OrderReferences(WireModel):
    despatch_reference: DespatchReference | None = None
    invoice_reference: InvoiceReference | None = None
    payment_reference: PaymentReference | None = None


class TimelineEntry(WireModel):
    event_id: UUID
    causation_id: UUID | None = None
    event_type: str
    occurred_at: AwareDatetime
    summary: str
    detail: dict[str, Any] | None = None


class OrderDetail(WireModel):
    order_id: UUID
    order_reference: Annotated[str | None, Field(pattern="^ORD-[0-9]{6,}$")] = None
    order_date: AwareDatetime | None = None
    retailer: PartyRef | None = None
    company: PartyRef | None = None
    status: OrderStatus
    cancellation_reason: CancellationReason | None = None
    currency: Annotated[str | None, Field(pattern="^[A-Z]{3}$")] = None
    totals: OrderTotals | None = None
    items: list[OrderItem] | None = None
    references: OrderReferences | None = None
    events: list[TimelineEntry]
    header_complete: bool | None = None
    updated_at: AwareDatetime


class ProjectionPending(WireModel):
    order_id: UUID
    status: Literal["projection_pending"]
    message: str | None = None
    retry_after_ms: Annotated[int | None, Field(ge=0)] = None


class OrderStreamUpdate(WireModel):
    event_id: UUID
    order_id: UUID
    order_reference: Annotated[str | None, Field(pattern="^ORD-[0-9]{6,}$")] = None
    status: OrderStatus
    cancellation_reason: CancellationReason | None = None
    references: OrderReferences | None = None
    totals: OrderTotals | None = None
    occurred_at: AwareDatetime


class TimelineStreamEntry(WireModel):
    event_id: UUID
    causation_id: UUID | None = None
    order_id: UUID
    order_reference: Annotated[str | None, Field(pattern="^ORD-[0-9]{6,}$")] = None
    event_type: str
    occurred_at: AwareDatetime
    summary: str


class StreamReady(WireModel):
    cursor: str
    resumed: bool
    order_id: UUID | None = None


class StreamPing(WireModel):
    at: AwareDatetime


class StockItem(WireModel):
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    product_name: str | None = None
    units: Annotated[int, Field(ge=0)]
    reserved_units: Annotated[int, Field(ge=0)]
    available_units: Annotated[int, Field(ge=0)]
    low_stock_threshold: Annotated[int, Field(ge=0)]


class StockPage(WireModel):
    items: list[StockItem]
    page: PageInfo


class Line(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    units: Annotated[int, Field(ge=1)]


class ReplenishStockRequest(WireModel):
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    lines: Annotated[list[Line], Field(min_length=1)]


class ReplenishStockResponse(WireModel):
    items: list[StockItem]


class Line1(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    units: Annotated[int, Field(ge=1)]
    unit_price: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]


class Invoice(WireModel):
    invoice_id: UUID
    invoice_reference: Annotated[str, Field(pattern="^INV-[0-9]{6,}$")]
    invoice_date: AwareDatetime
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    discount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    total_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    status: InvoiceStatus
    paid_at: AwareDatetime | None = None
    lines: list[Line1] | None = None


class InvoicePage(WireModel):
    items: list[Invoice]
    page: PageInfo


class RegisterPaymentRequest(WireModel):
    payment_reference: Annotated[str, Field(max_length=30, min_length=1)]
    amount: Money
    value_date: AwareDatetime
    source: PaymentSource


class Outcome(StrEnum):
    accepted = "accepted"
    duplicate = "duplicate"


class RegisterPaymentResponse(WireModel):
    outcome: Outcome
    payment_reference: Annotated[str, Field(max_length=30, min_length=1)]
    invoice_reference: Annotated[str, Field(pattern="^INV-[0-9]{6,}$")]
    order_reference: Annotated[str | None, Field(pattern="^ORD-[0-9]{6,}$")] = None
    invoice_status: InvoiceStatus
    paid_at: AwareDatetime | None = None


class Credit(WireModel):
    credit_code: Annotated[str, Field(pattern="^CR-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    credit_limit: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    active_holds: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    open_exposure: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    available_credit: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]


class CreditPage(WireModel):
    items: list[Credit]
    page: PageInfo


class Status(StrEnum):
    up = "up"
    down = "down"


class Checks(WireModel):
    status: Status
    detail: str | None = None


class HealthResponse(WireModel):
    status: Status
    checks: dict[str, Checks] | None = None


class Problem(WireModel):
    type: str | None = "about:blank"
    title: str
    status: Annotated[int, Field(ge=100, le=599)]
    detail: str | None = None
    instance: str | None = None
    code: str
    correlation_id: UUID | None = None
    occurred_at: AwareDatetime | None = None


class Error(WireModel):
    field: str
    message: str


class ValidationProblem(WireModel):
    type: str | None = "about:blank"
    title: str
    status: Annotated[int, Field(ge=100, le=599)]
    detail: str | None = None
    instance: str | None = None
    code: str
    correlation_id: UUID | None = None
    occurred_at: AwareDatetime | None = None
    errors: list[Error] | None = None


class Shortage(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    requested: Annotated[int, Field(ge=1)]
    available: Annotated[int, Field(ge=0)]


class StockUnavailableProblem(WireModel):
    type: str | None = "about:blank"
    title: str
    status: Annotated[int, Field(ge=100, le=599)]
    detail: str | None = None
    instance: str | None = None
    code: str
    correlation_id: UUID | None = None
    occurred_at: AwareDatetime | None = None
    shortages: list[Shortage] | None = None


class PlaceOrderRequest(WireModel):
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    lines: Annotated[list[PlaceOrderLine], Field(min_length=1)]
    order_discount: Annotated[
        int | None, Field(ge=-9223372036854775808, le=9223372036854775807)
    ] = None
    notes: str | None = None


class OrderSummary(WireModel):
    order_id: UUID
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    order_date: AwareDatetime
    retailer: PartyRef
    company: PartyRef
    status: OrderStatus
    cancellation_reason: CancellationReason | None = None
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    totals: OrderTotals
    updated_at: AwareDatetime


class OrderSummaryPage(WireModel):
    items: list[OrderSummary]
    page: PageInfo
