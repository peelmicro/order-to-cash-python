"""`x-correlation-id` and `x-request-id` (FS3): required, well-formed, on `stock.reserve` and
`stock.release` only.

The saga sends the order id as `x-correlation-id` and the id of the durable `saga_commands` row as
`x-request-id` (FS2). They become the `correlationId` and `causationId` of the emitted fact (R12),
so an absent or malformed one is `VALIDATION_FAILED` with nothing dispatched. `stock.check`,
`stock.list` and `stock.replenish` need neither.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from otc_shared_kernel import DomainError, UniqueId

CORRELATION_HEADER = "x-correlation-id"
REQUEST_HEADER = "x-request-id"


class InvalidStockHeadersError(Exception):
    """A required request header is absent or is not a well-formed `UniqueId`."""


@dataclass(frozen=True, slots=True)
class RpcCorrelation:
    correlation_id: UniqueId
    request_id: UniqueId


def _lookup(headers: Mapping[str, str] | None, name: str) -> str | None:
    if headers is None:
        return None
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _identifier(headers: Mapping[str, str] | None, name: str) -> UniqueId:
    raw = _lookup(headers, name)
    if raw is None:
        raise InvalidStockHeadersError(f"the {name} header is required")
    try:
        return UniqueId.parse(raw)
    except DomainError:
        raise InvalidStockHeadersError(f"the {name} header is not a well-formed id") from None


def required_correlation(headers: Mapping[str, str] | None) -> RpcCorrelation:
    return RpcCorrelation(
        correlation_id=_identifier(headers, CORRELATION_HEADER),
        request_id=_identifier(headers, REQUEST_HEADER),
    )


def optional_correlation_id(headers: Mapping[str, str] | None) -> UniqueId | None:
    """The `x-correlation-id` when present and well formed (it labels an `RpcError`); else None."""
    try:
        return _identifier(headers, CORRELATION_HEADER)
    except InvalidStockHeadersError:
        return None
