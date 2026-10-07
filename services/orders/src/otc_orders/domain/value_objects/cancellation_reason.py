"""`CancellationReason`: the closed set of `domain-model.md` section 3.1 (invariant O6)."""

from enum import Enum

from otc_orders.domain.errors import CancellationReasonRequiredError, UnknownCancellationReasonError


class CancellationReason(Enum):
    STOCK_REJECTED = "stock_rejected"
    CREDIT_REJECTED = "credit_rejected"
    OPERATOR_CANCELLED = "operator_cancelled"


_BY_TOKEN: dict[str, CancellationReason] = {
    "stock_rejected": CancellationReason.STOCK_REJECTED,
    "credit_rejected": CancellationReason.CREDIT_REJECTED,
    "operator_cancelled": CancellationReason.OPERATOR_CANCELLED,
}


def parse_cancellation_reason(token: object) -> CancellationReason:
    """`None` or a blank string is a missing reason; anything else outside the set is unknown."""
    if token is None or (type(token) is str and not token.strip()):
        raise CancellationReasonRequiredError
    if type(token) is not str or token not in _BY_TOKEN:
        raise UnknownCancellationReasonError(token)
    return _BY_TOKEN[token]
