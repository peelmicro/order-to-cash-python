"""The twelve domain errors of the Order aggregate (`specs/orders_aggregate/design.md` section 10).

Codes are `<subject>.<snake_case_reason>`, the convention #9's kernel inherited from #8. A message
carries the specifics (the status pair, the line id, the currencies, the money text); `code` is
what machines branch on. This module imports no other module of the domain, so the vocabularies
can raise from their parse functions without a cycle: statuses and reasons arrive as their string
tokens.
"""

from otc_shared_kernel import DomainError, Money, UniqueId, format_money


class OrderMustHaveAtLeastOneLineError(DomainError):
    CODE = "order.must_have_at_least_one_line"

    def __init__(self) -> None:
        super().__init__(self.CODE, "An order must have at least one line.")


class OrderTotalMustNotBeNegativeError(DomainError):
    CODE = "order.total_must_not_be_negative"

    def __init__(self, candidate_total: Money) -> None:
        super().__init__(
            self.CODE,
            "The resulting total amount would be negative: "
            f"{format_money(candidate_total.amount, candidate_total.currency)}.",
        )
        self.candidate_total = candidate_total


class OrderLinesAreFrozenError(DomainError):
    CODE = "order.lines_are_frozen"

    def __init__(self, status: str) -> None:
        super().__init__(
            self.CODE,
            f"The lines of an order in status '{status}' can no longer be added, removed or "
            "changed.",
        )
        self.status = status


class OrderLineNotFoundError(DomainError):
    CODE = "order.line_not_found"

    def __init__(self, line_id: UniqueId) -> None:
        super().__init__(self.CODE, f"The order has no line with id {line_id}.")
        self.line_id = line_id


class OrderLineCurrencyMismatchError(DomainError):
    CODE = "order.line_currency_mismatch"

    def __init__(self, field: str, order_currency: str, offending_currency: str) -> None:
        super().__init__(
            self.CODE,
            f"The line's {field} is in {offending_currency!r} but the order is in "
            f"{order_currency!r}: every amount of an order is in the order's currency.",
        )
        self.field = field
        self.order_currency = order_currency
        self.offending_currency = offending_currency


class IllegalOrderTransitionError(DomainError):
    CODE = "order.illegal_transition"

    def __init__(self, source: str, target: str) -> None:
        super().__init__(
            self.CODE,
            f"An order cannot move from '{source}' to '{target}': that edge is not in Table T-1.",
        )
        self.source = source
        self.target = target


class OrderNotCancellableError(IllegalOrderTransitionError):
    CODE = "order.not_cancellable"

    def __init__(self, status: str) -> None:
        DomainError.__init__(
            self,
            self.CODE,
            f"An order in status '{status}' cannot be cancelled.",
        )
        self.source = status
        self.target = "cancelled"


class CancellationReasonRequiredError(DomainError):
    CODE = "order.cancellation_reason_required"

    def __init__(self) -> None:
        super().__init__(self.CODE, "A cancellation reason is required.")


class UnknownCancellationReasonError(DomainError):
    CODE = "order.cancellation_reason_unknown"

    def __init__(self, offending: object) -> None:
        super().__init__(
            self.CODE,
            f"{offending!r} is not a cancellation reason: expected one of "
            "'stock_rejected', 'credit_rejected', 'operator_cancelled'.",
        )
        self.offending = offending


class CancellationReasonNotApplicableError(DomainError):
    CODE = "order.cancellation_reason_not_applicable"

    def __init__(self, reason: str, status: str) -> None:
        super().__init__(
            self.CODE,
            f"The cancellation reason '{reason}' does not apply to an order in status '{status}'.",
        )
        self.reason = reason
        self.status = status


class InvalidOrderSnapshotError(DomainError):
    CODE = "order.snapshot_invalid"

    def __init__(self, detail: str) -> None:
        super().__init__(self.CODE, f"The stored order cannot be restored: {detail}.")
        self.detail = detail


class InstantNotUtcError(DomainError):
    CODE = "order.instant_not_utc"

    def __init__(self, field: str, offending: object) -> None:
        super().__init__(
            self.CODE,
            f"{field} must be a timezone-aware instant in UTC, got {offending!r}.",
        )
        self.field = field
