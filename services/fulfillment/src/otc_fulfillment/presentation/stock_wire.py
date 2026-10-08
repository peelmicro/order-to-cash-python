"""The five `fulfillment.stock.*` requests and replies and the `fulfillment.despatch.create` pair
on the wire (`design.md` 8.4; the despatch pair is feature 18).

Requests are parsed by the generated models through `from_wire_json` (strict integers, lengths,
patterns, enums, `minItems`); a request that fails is `InvalidStockRequestError` ->
`VALIDATION_FAILED`, with nothing dispatched. Two checks the schema cannot express are made here:
`orderReference` at most 20 characters (FS28: the wire pattern has no maximum and the column is
`varchar(20)`). The order reference stays a `str` from the wire to the column (L23): the kernel's
canonical `OrderNumber`, which refuses `ORD-000000`, is NEVER applied on this path.

Replies are application results mapped to the generated reply models and written by the one
serializer (`to_wire_json`). `StockReleaseReplyPayload.released` is written as an EMPTY LIST for
`already_released` (a `None` would be omitted).
"""

from otc_contracts import from_wire_json, to_wire_json
from otc_contracts.generated import asyncapi
from otc_contracts.wire import WireModel
from otc_fulfillment.application.messages import (
    CheckLine,
    CheckStockQuery,
    CreateDespatchCommand,
    DespatchResult,
    ListStockQuery,
    ReleaseResult,
    ReleaseStockCommand,
    ReplenishResult,
    ReplenishStockCommand,
    ReserveResult,
    ReserveStockCommand,
    StockAvailability,
    StockLine,
    StockPage,
    StockViewData,
)
from otc_fulfillment.domain.events import ReleaseReason, ReservationRef, Shortage
from otc_fulfillment.presentation.stock_headers import RpcCorrelation
from otc_shared_kernel import Quantity

ORDER_REFERENCE_MAX_LENGTH = 20  # reservations.order_reference is varchar(20)


class InvalidStockRequestError(Exception):
    """The request does not satisfy the wire schema (or a check the schema cannot express)."""


def _parse[M: WireModel](model: type[M], body: bytes, subject: str) -> M:
    try:
        return from_wire_json(model, body)
    except ValueError as error:  # pydantic's ValidationError and JSONDecodeError are ValueErrors
        raise InvalidStockRequestError(f"{subject} request is invalid: {error}") from None


def _order_reference(value: str) -> str:
    if len(value) > ORDER_REFERENCE_MAX_LENGTH:
        raise InvalidStockRequestError(
            f"orderReference is longer than {ORDER_REFERENCE_MAX_LENGTH} characters"
        )
    return value


# ------------------------------------------------------------------------------------ requests


def decode_check(body: bytes) -> CheckStockQuery:
    request = _parse(asyncapi.StockCheckRequestPayload, body, "stock.check")
    return CheckStockQuery(
        company_code=request.company_code,
        lines=tuple(CheckLine(l.product_code, l.quantity) for l in request.lines),  # noqa: E741
    )


def decode_list(body: bytes) -> ListStockQuery:
    request = _parse(asyncapi.StockListRequestPayload, body, "stock.list")
    return ListStockQuery(
        page=1 if request.page is None else request.page,
        page_size=25 if request.page_size is None else request.page_size,
        company_code=request.company_code,
        product_code=request.product_code,
        below_threshold=request.below_threshold,
    )


def decode_reserve(body: bytes, correlation: RpcCorrelation) -> ReserveStockCommand:
    request = _parse(asyncapi.StockReserveRequestPayload, body, "stock.reserve")
    return ReserveStockCommand(
        order_reference=_order_reference(request.order_reference),
        company_code=request.company_code,
        retailer_code=request.retailer_code,
        lines=tuple(StockLine(l.product_code, Quantity(l.units)) for l in request.lines),  # noqa: E741
        correlation_id=correlation.correlation_id,
        request_id=correlation.request_id,
    )


def decode_release(body: bytes, correlation: RpcCorrelation) -> ReleaseStockCommand:
    request = _parse(asyncapi.StockReleaseRequestPayload, body, "stock.release")
    return ReleaseStockCommand(
        order_reference=_order_reference(request.order_reference),
        reason=ReleaseReason(request.reason.value),
        correlation_id=correlation.correlation_id,
        request_id=correlation.request_id,
    )


def decode_replenish(body: bytes) -> ReplenishStockCommand:
    request = _parse(asyncapi.StockReplenishRequestPayload, body, "stock.replenish")
    return ReplenishStockCommand(
        company_code=request.company_code,
        lines=tuple(StockLine(l.product_code, Quantity(l.units)) for l in request.lines),  # noqa: E741
    )


def decode_despatch(body: bytes, correlation: RpcCorrelation) -> CreateDespatchCommand:
    request = _parse(asyncapi.DespatchCreateRequestPayload, body, "despatch.create")
    return CreateDespatchCommand(
        order_reference=_order_reference(request.order_reference),
        correlation_id=correlation.correlation_id,
        request_id=correlation.request_id,
    )


# -------------------------------------------------------------------------------------- replies


def _refs(refs: tuple[ReservationRef, ...]) -> list[asyncapi.ReservationRef]:
    return [
        asyncapi.ReservationRef(
            reservation_id=r.reservation_id.value, product_code=r.product_code, units=r.units
        )
        for r in refs
    ]


def _shortages(shortages: tuple[Shortage, ...]) -> list[asyncapi.Shortage]:
    return [
        asyncapi.Shortage(product_code=s.product_code, requested=s.requested, available=s.available)
        for s in shortages
    ]


def _view(view: StockViewData) -> asyncapi.StockView:
    return asyncapi.StockView(
        company_code=view.company_code,
        product_code=view.product_code,
        units=view.units,
        reserved_units=view.reserved_units,
        available_units=view.available_units,
        low_stock_threshold=view.low_stock_threshold,
    )


def check_reply(result: StockAvailability) -> asyncapi.StockCheckReplyPayload:
    return asyncapi.StockCheckReplyPayload(
        available=result.available,
        lines=[
            asyncapi.Line2(
                product_code=l.product_code,
                requested=l.requested,
                available=l.available,
                sufficient=l.sufficient,
            )
            for l in result.lines  # noqa: E741
        ],
    )


def list_reply(result: StockPage) -> asyncapi.StockListReplyPayload:
    return asyncapi.StockListReplyPayload(
        items=[_view(v) for v in result.items],
        page=asyncapi.PageInfo(page=result.page, page_size=result.page_size, total=result.total),
    )


def reserve_reply(result: ReserveResult) -> asyncapi.StockReserveReplyPayload:
    return asyncapi.StockReserveReplyPayload(
        outcome=asyncapi.Outcome(result.outcome.value),
        order_reference=result.order_reference,
        reservations=None if result.reservations is None else _refs(result.reservations),
        shortages=None if result.shortages is None else _shortages(result.shortages),
    )


def release_reply(result: ReleaseResult) -> asyncapi.StockReleaseReplyPayload:
    return asyncapi.StockReleaseReplyPayload(
        outcome=asyncapi.Outcome1(result.outcome.value),
        order_reference=result.order_reference,
        released=_refs(result.released),
    )


def replenish_reply(result: ReplenishResult) -> asyncapi.StockReplenishReplyPayload:
    return asyncapi.StockReplenishReplyPayload(items=[_view(v) for v in result.items])


def despatch_reply(result: DespatchResult) -> asyncapi.DespatchCreateReplyPayload:
    advice = result.despatch
    return asyncapi.DespatchCreateReplyPayload(
        order_reference=advice.order_reference,
        despatch_reference=advice.despatch_reference.value,
        despatch_date=advice.despatch_date,
        created=result.created,
        lines=[
            asyncapi.DespatchLine(product_code=line.product_code, units=line.units)
            for line in advice.lines
        ],
    )


def encode(model: WireModel) -> bytes:
    return to_wire_json(model).encode("utf-8")


__all__ = [
    "InvalidStockRequestError",
    "check_reply",
    "decode_check",
    "decode_despatch",
    "decode_list",
    "decode_release",
    "decode_replenish",
    "decode_reserve",
    "despatch_reply",
    "encode",
    "list_reply",
    "release_reply",
    "replenish_reply",
    "reserve_reply",
]
