"""The five domain errors of the stock aggregate (`specs/fulfillment_stock/design.md` 5.4).

Codes are `<subject>.<snake_case_reason>` (Orders' convention, inherited from the kernel). A message
carries the specifics; `code` is what machines branch on. There is no overflow error here: Python's
`int` cannot wrap, and the width of the `integer` column is the write boundary's concern (L5, FS20).
"""

from otc_shared_kernel import DomainError


class InsufficientStockError(DomainError):
    CODE = "stock.insufficient"

    def __init__(self, product_code: str, requested: int, available: int) -> None:
        super().__init__(
            self.CODE,
            f"{requested} unit(s) of {product_code!r} were requested but only {available} are "
            "available.",
        )
        self.product_code = product_code
        self.requested = requested
        self.available = available


class ReservationTerminalError(DomainError):
    CODE = "reservation.terminal"

    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(
            self.CODE,
            f"A reservation that is '{from_status}' cannot become '{to_status}': 'released' and "
            "'consumed' are terminal.",
        )
        self.from_status = from_status
        self.to_status = to_status


class InvalidStockItemSnapshotError(DomainError):
    CODE = "stock_item.invalid_snapshot"

    def __init__(self, reason: str) -> None:
        super().__init__(self.CODE, f"The stored stock item cannot be restored: {reason}.")
        self.reason = reason


class FactAggregateMismatchError(DomainError):
    CODE = "stock.fact_aggregate_mismatch"

    def __init__(self, item_id: object, fact_aggregate_id: object) -> None:
        super().__init__(
            self.CODE,
            f"A fact about aggregate {fact_aggregate_id} cannot be recorded on stock item "
            f"{item_id}.",
        )


class UnknownReservationStatusError(DomainError):
    CODE = "reservation.unknown_status"

    def __init__(self, token: object) -> None:
        super().__init__(self.CODE, f"{token!r} is not a reservation status.")


class EmptyDespatchLinesError(DomainError):
    CODE = "despatch.empty_lines"

    def __init__(self, order_reference: str) -> None:
        super().__init__(
            self.CODE,
            f"The despatch advice for order {order_reference} has no line: a despatch advice has "
            "at least one (F6).",
        )
        self.order_reference = order_reference
