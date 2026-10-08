"""Every failure of a `fulfillment.stock.*` or `fulfillment.despatch.create` request becomes an
`RpcError` (`design.md` 8.5).

Every code here is a saga decision. Orders' adapter splits the twelve codes into nine TERMINAL
(`TERMINAL_RPC_ERROR_CODES`) and three transient (`TIMEOUT`, `UNAVAILABLE`, `INTERNAL_ERROR`), so:

* a transient store failure (`StoreUnavailableError`, `ConcurrentReservationChangeError`) is
  `UNAVAILABLE`, and anything unclassified is `INTERNAL_ERROR`: both are retried by the caller;
* `CONFLICT` is produced by NO input (it is terminal in Orders; #7 answered a concurrency error with
  it because #7's orchestrator retried everything), nor is `TIMEOUT` (produced by the caller);
* a business rejection (`stock.rejected.v1`) is never an `RpcError`: it is the `rejected` outcome.

`INTERNAL_ERROR` never carries the exception's text (it can hold SQL or a path); it is logged.
"""

from datetime import datetime

from otc_contracts.generated.asyncapi import Code, RpcError
from otc_fulfillment.application.despatch_creation import NoReservedStockForDespatchError
from otc_fulfillment.application.ports.stock_store import (
    ConcurrentDespatchChangeError,
    ConcurrentReservationChangeError,
    StoreUnavailableError,
)
from otc_fulfillment.application.stock_replenishment import UnknownStockItemError
from otc_fulfillment.application.stock_reservation import NoKnownStockItemError
from otc_fulfillment.domain.errors import ReservationTerminalError
from otc_fulfillment.presentation.stock_headers import InvalidStockHeadersError
from otc_fulfillment.presentation.stock_wire import InvalidStockRequestError
from otc_shared_kernel import DomainError, UniqueId


def map_error(error: Exception, occurred_at: datetime, correlation_id: UniqueId | None) -> RpcError:
    """The `RpcError` for a failure of the request path. Order matters: the specific refusals come
    before the general ones they are subclasses of."""
    correlation = None if correlation_id is None else correlation_id.value

    def rpc(code: Code, message: str, details: dict[str, object] | None = None) -> RpcError:
        return RpcError(
            code=code,
            message=message,
            details=details,
            correlation_id=correlation,
            occurred_at=occurred_at,
        )

    match error:
        case InvalidStockRequestError() | InvalidStockHeadersError():
            return rpc(Code.validation_failed, str(error))
        case NoKnownStockItemError():
            return rpc(Code.not_found, str(error), {"orderReference": error.order_reference})
        case UnknownStockItemError():
            return rpc(
                Code.not_found,
                str(error),
                {"companyCode": error.company_code, "productCode": error.product_code},
            )
        case NoReservedStockForDespatchError():
            # R36's refusal: the order and its reservations exist but none is `reserved` (never
            # reserved, or released). #7 and #8 both answer PRECONDITION_FAILED, terminal in Orders.
            return rpc(
                Code.precondition_failed, str(error), {"orderReference": error.order_reference}
            )
        case ReservationTerminalError():
            return rpc(Code.precondition_failed, error.message, {"code": error.code})
        case DomainError():
            return rpc(Code.domain_error, error.message, {"code": error.code})
        case (
            StoreUnavailableError()
            | ConcurrentReservationChangeError()
            | ConcurrentDespatchChangeError()
        ):
            return rpc(Code.unavailable, str(error))
        case _:
            return rpc(Code.internal_error, "The request could not be processed.")
