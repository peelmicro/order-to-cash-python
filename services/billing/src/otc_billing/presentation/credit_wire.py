"""The three `billing.credit.*` requests and replies on the wire (`design.md` 8.4).

Requests are parsed by the generated models through `from_wire_json` (strict integers, lengths,
patterns, enums); a request that fails is `InvalidCreditRequestError` -> `VALIDATION_FAILED`, with
nothing dispatched. Two checks the schema cannot express are made here (BC33): `orderReference` at
most 20 characters (the wire pattern has no maximum and the column is `varchar(20)`), and a hold
`amount` that is not negative (the shared `Money` admits a negative amount, which would INCREASE the
available credit; zero is allowed, BC38). The order reference stays a `str` from the wire to the
column: the kernel's canonical `OrderNumber` is NEVER applied on this path.

Replies are application results mapped to the generated reply models and written by the one
serializer (`to_wire_json`; `None` fields are omitted): an `approved` reply carries `heldAmount` and
no `reason`; a `rejected` one a `reason` and no `heldAmount`; `already_held` the RECORDED
`heldAmount` and the CURRENT `availableCredit`; a `released: false` reply no `releasedAmount`.
"""

from otc_billing.application.messages import (
    CreditPage,
    CreditViewData,
    HoldCreditCommand,
    HoldResult,
    ListCreditQuery,
    ReleaseCreditCommand,
    ReleaseResult,
)
from otc_billing.presentation.credit_headers import RpcCorrelation
from otc_contracts import from_wire_json, to_wire_json
from otc_contracts.generated import asyncapi
from otc_contracts.wire import WireModel
from otc_shared_kernel import Money

ORDER_REFERENCE_MAX_LENGTH = 20  # credit_items.order_reference is varchar(20)


class InvalidCreditRequestError(Exception):
    """The request does not satisfy the wire schema (or a check the schema cannot express)."""


def _parse[M: WireModel](model: type[M], body: bytes, subject: str) -> M:
    try:
        return from_wire_json(model, body)
    except ValueError as error:  # pydantic's ValidationError and JSONDecodeError are ValueErrors
        raise InvalidCreditRequestError(f"{subject} request is invalid: {error}") from None


def _order_reference(value: str) -> str:
    if len(value) > ORDER_REFERENCE_MAX_LENGTH:
        raise InvalidCreditRequestError(
            f"orderReference is longer than {ORDER_REFERENCE_MAX_LENGTH} characters"
        )
    return value


# ------------------------------------------------------------------------------------ requests


def decode_hold(body: bytes, correlation: RpcCorrelation) -> HoldCreditCommand:
    request = _parse(asyncapi.CreditHoldRequestPayload, body, "credit.hold")
    if request.amount.amount < 0:
        raise InvalidCreditRequestError("amount.amount must not be negative")
    return HoldCreditCommand(
        order_reference=_order_reference(request.order_reference),
        retailer_code=request.retailer_code,
        company_code=request.company_code,
        amount=Money(request.amount.amount, request.amount.currency),
        correlation_id=correlation.correlation_id,
        request_id=correlation.request_id,
    )


def decode_release(body: bytes, correlation: RpcCorrelation) -> ReleaseCreditCommand:
    request = _parse(asyncapi.CreditReleaseRequestPayload, body, "credit.release")
    return ReleaseCreditCommand(
        order_reference=_order_reference(request.order_reference),
        retailer_code=request.retailer_code,
        company_code=request.company_code,
        correlation_id=correlation.correlation_id,
        request_id=correlation.request_id,
    )


def decode_list(body: bytes) -> ListCreditQuery:
    request = _parse(asyncapi.CreditListRequestPayload, body, "credit.list")
    return ListCreditQuery(
        page=1 if request.page is None else request.page,
        page_size=25 if request.page_size is None else request.page_size,
        retailer_code=request.retailer_code,
        company_code=request.company_code,
    )


# -------------------------------------------------------------------------------------- replies


def hold_reply(result: HoldResult) -> asyncapi.CreditHoldReplyPayload:
    return asyncapi.CreditHoldReplyPayload(
        outcome=asyncapi.Outcome2(result.outcome.value),
        order_reference=result.order_reference,
        credit_code=result.credit_code,
        currency=result.currency,
        held_amount=result.held_amount,
        available_credit=result.available_credit,
        reason=None if result.reason is None else asyncapi.Reason5(result.reason.value),
    )


def release_reply(result: ReleaseResult) -> asyncapi.CreditReleaseReplyPayload:
    return asyncapi.CreditReleaseReplyPayload(
        released=result.released,
        order_reference=result.order_reference,
        credit_code=result.credit_code,
        currency=result.currency,
        released_amount=result.released_amount,
        available_credit_after=result.available_credit_after,
    )


def _view(view: CreditViewData) -> asyncapi.CreditView:
    return asyncapi.CreditView(
        credit_code=view.credit_code,
        retailer_code=view.retailer_code,
        company_code=view.company_code,
        currency=view.currency,
        credit_limit=view.credit_limit,
        active_holds=view.active_holds,
        open_exposure=view.open_exposure,
        available_credit=view.available_credit,
    )


def list_reply(result: CreditPage) -> asyncapi.CreditListReplyPayload:
    return asyncapi.CreditListReplyPayload(
        items=[_view(v) for v in result.items],
        page=asyncapi.PageInfo(page=result.page, page_size=result.page_size, total=result.total),
    )


def encode(model: WireModel) -> bytes:
    return to_wire_json(model).encode("utf-8")
