"""`StockAvailability`: the synchronous, non-locking `fulfillment.stock.check` read (R31).

The port's failures are typed, because each one is a different answer to the caller of
`orders.create` and feature 42 classifies retries by it:

* `StockCheckTransportError`  -> no responder is subscribed (NATS "no responders"), or the reply is
  not a usable answer (not JSON, not the contract's shape, a responder code outside the wire enum).
  Diagnosable at once, so it is not a wait. RPC code `UNAVAILABLE`.
* `StockCheckTimeoutError`    -> a responder is subscribed and did not answer in time.
  RPC code `TIMEOUT`.
* `StockCheckBusinessError`   -> the responder answered with its OWN `RpcError` (#8 id 46): its code
  and message are carried unchanged.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from otc_shared_kernel import Quantity


@dataclass(frozen=True, slots=True)
class StockAvailabilityLine:
    product_code: str
    quantity: Quantity


@dataclass(frozen=True, slots=True)
class StockAvailabilityLineResult:
    product_code: str
    requested: int
    available: int
    sufficient: bool


@dataclass(frozen=True, slots=True)
class StockAvailabilityResult:
    available: bool
    lines: tuple[StockAvailabilityLineResult, ...]


class StockCheckError(Exception):
    """Base of the port's failures; `subject` is the RPC subject that failed."""

    def __init__(self, subject: str, message: str) -> None:
        super().__init__(message)
        self.subject = subject


class StockCheckTransportError(StockCheckError):
    pass


class StockCheckTimeoutError(StockCheckError):
    def __init__(self, subject: str, timeout_ms: int) -> None:
        super().__init__(subject, f"no reply from {subject} within {timeout_ms} ms.")
        self.timeout_ms = timeout_ms


class StockCheckBusinessError(StockCheckError):
    """The responder's own `RpcError`: `rpc_error_code` is the code exactly as it arrived."""

    def __init__(self, subject: str, rpc_error_code: str, responder_message: str) -> None:
        super().__init__(subject, f"{subject} answered {rpc_error_code}: {responder_message}")
        self.rpc_error_code = rpc_error_code
        self.responder_message = responder_message


class StockAvailability(Protocol):
    async def check(
        self, company_code: str, lines: Sequence[StockAvailabilityLine]
    ) -> StockAvailabilityResult: ...
