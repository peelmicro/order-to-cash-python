# GENERATED FILE - DO NOT EDIT.
# Regenerate with `uv run python scripts/generate_contracts.py`.
# Source: specs/shared/asyncapi.yaml sha256-prefix16=56ec7c72229a9c61
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


class Quantity(RootModel[int]):
    root: Annotated[int, Field(ge=1)]


class ProductCode(RootModel[str]):
    root: Annotated[str, Field(max_length=30, min_length=1)]


class PartyRef(WireModel):
    code: Annotated[str, Field(max_length=20, min_length=1)]
    name: str | None = None
    gln: Annotated[str, Field(pattern="^[0-9]{13}$")]


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


class ReservationStatus(StrEnum):
    reserved = "reserved"
    released = "released"
    consumed = "consumed"


class PaymentSource(StrEnum):
    operator = "operator"
    robot = "robot"
    test = "test"


class OrderLine(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    description: str | None = None
    quantity: Annotated[int, Field(ge=1)]
    unit_price: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    line_discount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]


class ReservationRef(WireModel):
    reservation_id: UUID
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    units: Annotated[int, Field(ge=1)]


class Shortage(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    requested: Annotated[int, Field(ge=1)]
    available: Annotated[int, Field(ge=0)]


class DespatchLine(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    units: Annotated[int, Field(ge=1)]


class InvoiceLine(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    units: Annotated[int, Field(ge=1)]
    unit_price: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]


class Step(StrEnum):
    stock_released = "stock_released"
    credit_released = "credit_released"


class CompensationStep(WireModel):
    step: Step
    event_id: UUID | None = None
    event_type: str
    occurred_at: AwareDatetime
    summary: str | None = None


class Envelope(WireModel):
    event_id: UUID
    event_type: Annotated[str, Field(pattern="^[a-z]+\\.[a-z_]+\\.v[0-9]+$")]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: dict[str, Any]


class OrderPlacedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    buyer_gln: Annotated[str, Field(pattern="^[0-9]{13}$")]
    supplier_gln: Annotated[str, Field(pattern="^[0-9]{13}$")]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    order_date: AwareDatetime
    lines: Annotated[list[OrderLine], Field(min_length=1)]
    initial_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    initial_discount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    total_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    notes: str | None = None


class StockReservedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    retailer_code: Annotated[str | None, Field(max_length=20, min_length=1)] = None
    reservations: Annotated[list[ReservationRef], Field(min_length=1)]


class Reason(StrEnum):
    insufficient_stock = "insufficient_stock"
    unknown_product = "unknown_product"


class StockRejectedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    retailer_code: Annotated[str | None, Field(max_length=20, min_length=1)] = None
    shortages: Annotated[list[Shortage], Field(min_length=1)]
    reason: Reason


class Reason1(StrEnum):
    credit_rejected = "credit_rejected"
    order_cancelled = "order_cancelled"


class StockReleasedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    retailer_code: Annotated[str | None, Field(max_length=20, min_length=1)] = None
    released: Annotated[list[ReservationRef], Field(min_length=1)]
    reason: Reason1


class CreditApprovedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    credit_code: Annotated[str, Field(pattern="^CR-[0-9]{6,}$")]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    held_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    available_credit_after: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]


class Reason2(StrEnum):
    over_limit = "over_limit"
    simulated_cents_rule = "simulated_cents_rule"
    simulated_failure_rate = "simulated_failure_rate"


class CreditRejectedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    credit_code: Annotated[str | None, Field(pattern="^CR-[0-9]{6,}$")] = None
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    requested_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    available_credit: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    reason: Reason2


class Reason3(StrEnum):
    invoice_paid = "invoice_paid"
    order_cancelled = "order_cancelled"


class CreditReleasedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    credit_code: Annotated[str | None, Field(pattern="^CR-[0-9]{6,}$")] = None
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    released_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    available_credit_after: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    reason: Reason3


class OrderConfirmedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    total_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    confirmed_at: AwareDatetime


class OrderDespatchedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    despatch_reference: Annotated[str, Field(pattern="^DES-[0-9]{6,}$")]
    despatch_date: AwareDatetime
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    lines: Annotated[list[DespatchLine], Field(min_length=1)]


class InvoiceIssuedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    invoice_reference: Annotated[str, Field(pattern="^INV-[0-9]{6,}$")]
    invoice_date: AwareDatetime
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    lines: Annotated[list[InvoiceLine], Field(min_length=1)]
    amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    discount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    total_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]


class PaymentReceivedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    invoice_reference: Annotated[str, Field(pattern="^INV-[0-9]{6,}$")]
    payment_reference: Annotated[str, Field(max_length=30, min_length=1)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    value_date: AwareDatetime
    source: PaymentSource


class OrderCompletedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    total_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    completed_at: AwareDatetime


class OrderCancelledPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    cancellation_reason: CancellationReason
    cancelled_at: AwareDatetime
    compensation_steps: list[CompensationStep]
    note: str | None = None


class OrderSagaFailedPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    command: str
    attempts: Annotated[int, Field(ge=1)]
    last_error: str
    failed_at: AwareDatetime


class OrderPlacedEvent(WireModel):
    event_id: UUID
    event_type: Literal["order.placed.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: OrderPlacedPayload


class StockReservedEvent(WireModel):
    event_id: UUID
    event_type: Literal["stock.reserved.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: StockReservedPayload


class StockRejectedEvent(WireModel):
    event_id: UUID
    event_type: Literal["stock.rejected.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: StockRejectedPayload


class StockReleasedEvent(WireModel):
    event_id: UUID
    event_type: Literal["stock.released.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: StockReleasedPayload


class CreditApprovedEvent(WireModel):
    event_id: UUID
    event_type: Literal["credit.approved.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: CreditApprovedPayload


class CreditRejectedEvent(WireModel):
    event_id: UUID
    event_type: Literal["credit.rejected.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: CreditRejectedPayload


class CreditReleasedEvent(WireModel):
    event_id: UUID
    event_type: Literal["credit.released.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: CreditReleasedPayload


class OrderConfirmedEvent(WireModel):
    event_id: UUID
    event_type: Literal["order.confirmed.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: OrderConfirmedPayload


class OrderDespatchedEvent(WireModel):
    event_id: UUID
    event_type: Literal["order.despatched.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: OrderDespatchedPayload


class InvoiceIssuedEvent(WireModel):
    event_id: UUID
    event_type: Literal["invoice.issued.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: InvoiceIssuedPayload


class PaymentReceivedEvent(WireModel):
    event_id: UUID
    event_type: Literal["payment.received.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: PaymentReceivedPayload


class OrderCompletedEvent(WireModel):
    event_id: UUID
    event_type: Literal["order.completed.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: OrderCompletedPayload


class OrderCancelledEvent(WireModel):
    event_id: UUID
    event_type: Literal["order.cancelled.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: OrderCancelledPayload


class OrderSagaFailedEvent(WireModel):
    event_id: UUID
    event_type: Literal["order.saga_failed.v1"]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: OrderSagaFailedPayload


class Code(StrEnum):
    validation_failed = "VALIDATION_FAILED"
    not_found = "NOT_FOUND"
    conflict = "CONFLICT"
    precondition_failed = "PRECONDITION_FAILED"
    order_not_cancellable = "ORDER_NOT_CANCELLABLE"
    stock_unavailable = "STOCK_UNAVAILABLE"
    invoice_not_payable = "INVOICE_NOT_PAYABLE"
    payment_mismatch = "PAYMENT_MISMATCH"
    domain_error = "DOMAIN_ERROR"
    internal_error = "INTERNAL_ERROR"
    unavailable = "UNAVAILABLE"
    timeout = "TIMEOUT"


class RpcError(WireModel):
    code: Code
    message: str
    details: dict[str, Any] | None = None
    correlation_id: UUID | None = None
    occurred_at: AwareDatetime | None = None


class RpcTimeout(WireModel):
    code: Literal["TIMEOUT"]
    subject: str
    attempt: Annotated[int, Field(ge=1)]
    max_attempts: Annotated[int | None, Field(ge=1)] = None
    deadline_ms: Annotated[int | None, Field(ge=1)] = None
    order_reference: Annotated[str | None, Field(pattern="^ORD-[0-9]{6,}$")] = None


class PageRequest(WireModel):
    page: Annotated[int | None, Field(ge=1)] = 1
    page_size: Annotated[int | None, Field(ge=1, le=200)] = 25


class PageInfo(WireModel):
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1)]
    total: Annotated[int, Field(ge=0)]


class StockView(WireModel):
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    units: Annotated[int, Field(ge=0)]
    reserved_units: Annotated[int, Field(ge=0)]
    available_units: Annotated[int, Field(ge=0)]
    low_stock_threshold: Annotated[int, Field(ge=0)]


class CreditView(WireModel):
    credit_code: Annotated[str, Field(pattern="^CR-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    credit_limit: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    active_holds: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    open_exposure: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    available_credit: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]


class InvoiceView(WireModel):
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


class Product(WireModel):
    code: Annotated[str, Field(max_length=30, min_length=1)]
    ean: Annotated[str | None, Field(pattern="^[0-9]{13}$")] = None
    name: str
    description: str | None = None
    price: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    enabled: bool


class Party(WireModel):
    code: Annotated[str, Field(max_length=20, min_length=1)]
    name: str
    country: Annotated[str, Field(pattern="^[A-Z]{2}$")]
    vat: str | None = None
    gln: Annotated[str, Field(pattern="^[0-9]{13}$")]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    enabled: bool


class CurrencyView(WireModel):
    code: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    iso_number: Annotated[str | None, Field(pattern="^[0-9]{3}$")] = None
    symbol: str | None = None
    decimal_points: Annotated[int, Field(ge=0)]


class Line(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    quantity: Annotated[int, Field(ge=1)]
    unit_price: Annotated[int | None, Field(ge=-9223372036854775808, le=9223372036854775807)] = None
    line_discount: Annotated[int | None, Field(ge=-9223372036854775808, le=9223372036854775807)] = (
        None
    )


class OrdersCreateRequestPayload(WireModel):
    request_id: UUID | None = None
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    lines: Annotated[list[Line], Field(min_length=1)]
    order_discount: Annotated[
        int | None, Field(ge=-9223372036854775808, le=9223372036854775807)
    ] = None
    notes: str | None = None


class OrdersCreateReplyPayload(WireModel):
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


class OrdersCancelRequestPayload(WireModel):
    order_id: UUID | None = None
    order_reference: Annotated[str | None, Field(pattern="^ORD-[0-9]{6,}$")] = None
    reason: Literal["operator_cancelled"]
    note: str | None = None


class CompensationPlannedEnum(StrEnum):
    credit_release = "credit_release"
    stock_release = "stock_release"


class OrdersCancelReplyPayload(WireModel):
    order_id: UUID
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    status: OrderStatus
    cancellation_reason: CancellationReason | None = None
    compensation_planned: list[CompensationPlannedEnum]


class Line1(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    quantity: Annotated[int, Field(ge=1)]


class StockCheckRequestPayload(WireModel):
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    lines: Annotated[list[Line1], Field(min_length=1)]


class Line2(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    requested: Annotated[int, Field(ge=1)]
    available: Annotated[int, Field(ge=0)]
    sufficient: bool


class StockCheckReplyPayload(WireModel):
    available: bool
    lines: list[Line2]


class Line3(WireModel):
    product_code: Annotated[str, Field(max_length=30, min_length=1)]
    units: Annotated[int, Field(ge=1)]


class StockReserveRequestPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    lines: Annotated[list[Line3], Field(min_length=1)]


class Outcome(StrEnum):
    accepted = "accepted"
    rejected = "rejected"
    already_reserved = "already_reserved"


class StockReserveReplyPayload(WireModel):
    outcome: Outcome
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    reservations: list[ReservationRef] | None = None
    shortages: list[Shortage] | None = None


class Reason4(StrEnum):
    credit_rejected = "credit_rejected"
    order_cancelled = "order_cancelled"


class StockReleaseRequestPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    reason: Reason4


class Outcome1(StrEnum):
    released = "released"
    already_released = "already_released"


class StockReleaseReplyPayload(WireModel):
    outcome: Outcome1
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    released: list[ReservationRef] | None = None


class StockListRequestPayload(WireModel):
    page: Annotated[int | None, Field(ge=1)] = 1
    page_size: Annotated[int | None, Field(ge=1, le=200)] = 25
    company_code: Annotated[str | None, Field(max_length=20, min_length=1)] = None
    product_code: Annotated[str | None, Field(max_length=30, min_length=1)] = None
    below_threshold: bool | None = None


class StockListReplyPayload(WireModel):
    items: list[StockView]
    page: PageInfo


class StockReplenishRequestPayload(WireModel):
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    lines: Annotated[list[Line3], Field(min_length=1)]


class StockReplenishReplyPayload(WireModel):
    items: list[StockView]


class DespatchCreateRequestPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]


class DespatchCreateReplyPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    despatch_reference: Annotated[str, Field(pattern="^DES-[0-9]{6,}$")]
    despatch_date: AwareDatetime
    created: bool
    lines: list[DespatchLine] | None = None


class CreditHoldRequestPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    amount: Money


class Outcome2(StrEnum):
    approved = "approved"
    rejected = "rejected"
    already_held = "already_held"


class Reason5(StrEnum):
    over_limit = "over_limit"
    simulated_cents_rule = "simulated_cents_rule"
    simulated_failure_rate = "simulated_failure_rate"


class CreditHoldReplyPayload(WireModel):
    outcome: Outcome2
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    credit_code: Annotated[str | None, Field(pattern="^CR-[0-9]{6,}$")] = None
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    held_amount: Annotated[int | None, Field(ge=-9223372036854775808, le=9223372036854775807)] = (
        None
    )
    available_credit: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    reason: Reason5 | None = None


class CreditReleaseRequestPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]


class CreditReleaseReplyPayload(WireModel):
    released: bool
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    credit_code: Annotated[str | None, Field(pattern="^CR-[0-9]{6,}$")] = None
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    released_amount: Annotated[
        int | None, Field(ge=-9223372036854775808, le=9223372036854775807)
    ] = None
    available_credit_after: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]


class CreditListRequestPayload(WireModel):
    page: Annotated[int | None, Field(ge=1)] = 1
    page_size: Annotated[int | None, Field(ge=1, le=200)] = 25
    retailer_code: Annotated[str | None, Field(max_length=20, min_length=1)] = None
    company_code: Annotated[str | None, Field(max_length=20, min_length=1)] = None


class CreditListReplyPayload(WireModel):
    items: list[CreditView]
    page: PageInfo


class InvoiceIssueRequestPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    retailer_code: Annotated[str, Field(max_length=20, min_length=1)]
    company_code: Annotated[str, Field(max_length=20, min_length=1)]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    lines: Annotated[list[InvoiceLine], Field(min_length=1)]
    discount: Annotated[int | None, Field(ge=-9223372036854775808, le=9223372036854775807)] = None


class InvoiceIssueReplyPayload(WireModel):
    order_reference: Annotated[str, Field(pattern="^ORD-[0-9]{6,}$")]
    invoice_id: UUID | None = None
    invoice_reference: Annotated[str, Field(pattern="^INV-[0-9]{6,}$")]
    invoice_date: AwareDatetime
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    total_amount: Annotated[int, Field(ge=-9223372036854775808, le=9223372036854775807)]
    status: InvoiceStatus
    created: bool


class InvoiceListRequestPayload(WireModel):
    page: Annotated[int | None, Field(ge=1)] = 1
    page_size: Annotated[int | None, Field(ge=1, le=200)] = 25
    status: InvoiceStatus | None = None
    retailer_code: Annotated[str | None, Field(max_length=20, min_length=1)] = None
    company_code: Annotated[str | None, Field(max_length=20, min_length=1)] = None
    order_reference: Annotated[str | None, Field(pattern="^ORD-[0-9]{6,}$")] = None
    issued_before_minutes: Annotated[int | None, Field(ge=0)] = None


class InvoiceListReplyPayload(WireModel):
    items: list[InvoiceView]
    page: PageInfo


class PaymentRegisterRequestPayload(WireModel):
    invoice_id: UUID | None = None
    invoice_reference: Annotated[str | None, Field(pattern="^INV-[0-9]{6,}$")] = None
    payment_reference: Annotated[str, Field(max_length=30, min_length=1)]
    amount: Money
    value_date: AwareDatetime
    source: PaymentSource


class Outcome3(StrEnum):
    accepted = "accepted"
    duplicate = "duplicate"


class PaymentRegisterReplyPayload(WireModel):
    outcome: Outcome3
    payment_reference: Annotated[str, Field(max_length=30, min_length=1)]
    invoice_reference: Annotated[str, Field(pattern="^INV-[0-9]{6,}$")]
    order_reference: Annotated[str | None, Field(pattern="^ORD-[0-9]{6,}$")] = None
    invoice_status: InvoiceStatus
    paid_at: AwareDatetime | None = None


class Kind(StrEnum):
    products = "products"
    retailers = "retailers"
    companies = "companies"
    currencies = "currencies"


class CatalogReferenceListRequestPayload(WireModel):
    kinds: Annotated[list[Kind] | None, Field(min_length=1)] = None
    include_disabled: bool | None = False


class CatalogReferenceListReplyPayload(WireModel):
    products: list[Product] | None = None
    retailers: list[Party] | None = None
    companies: list[Party] | None = None
    currencies: list[CurrencyView] | None = None
