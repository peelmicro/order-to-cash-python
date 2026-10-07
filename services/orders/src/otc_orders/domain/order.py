"""The `Order` aggregate root (`specs/orders_aggregate/design.md`).

Synchronous and pure: no I/O, no `async def`, no clock read (every instant is a parameter). Python
has no compiler-enforced privacy, so the single-writer properties (design.md L4, L5) are held by a
read-only `@property` per field, `__slots__`, and a structural test over this file
(`test_private_state_has_exactly_the_literal_writers`): `_status` is written only by `__init__` and
`_transition_to`, the lines and totals only by `__init__` and `_commit_lines`.
"""

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Self, assert_never

from otc_orders.domain.errors import (
    CancellationReasonNotApplicableError,
    CancellationReasonRequiredError,
    IllegalOrderTransitionError,
    InvalidOrderSnapshotError,
    OrderLineCurrencyMismatchError,
    OrderLineNotFoundError,
    OrderLinesAreFrozenError,
    OrderMustHaveAtLeastOneLineError,
    OrderNotCancellableError,
    OrderTotalMustNotBeNegativeError,
    UnknownCancellationReasonError,
)
from otc_orders.domain.events import (
    OrderCancelled,
    OrderCompleted,
    OrderConfirmed,
    OrderEvent,
    OrderPlaced,
    OrderPlacedLine,
)
from otc_orders.domain.instants import require_utc
from otc_orders.domain.order_line import OrderLine, OrderLineInput
from otc_orders.domain.snapshot import OrderSnapshot
from otc_orders.domain.state_machine import (
    CANCELLED,
    COMPLETED,
    CONFIRMED,
    CREDIT_APPROVED,
    DESPATCHED,
    INVOICED,
    PAID,
    PLACED,
    STOCK_RESERVED,
    is_legal,
)
from otc_orders.domain.totals import OrderTotals, compute_totals
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.compensation_step import CompensationStep
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import (
    GLN,
    AggregateRoot,
    Money,
    OrderNumber,
    Quantity,
    UniqueId,
)

# R7 (invariant O4) as an allow-list: a status added later is frozen by default.
LINES_MUTABLE_IN: frozenset[OrderStatus] = frozenset({PLACED, STOCK_RESERVED, CREDIT_APPROVED})


def _sources_for(reason: CancellationReason) -> frozenset[OrderStatus]:
    """The statuses a reason pairs with (Table T-1's Trigger column; #7 OA4)."""
    match reason:
        case CancellationReason.STOCK_REJECTED:
            return frozenset({PLACED})
        case CancellationReason.CREDIT_REJECTED:
            return frozenset({STOCK_RESERVED})
        case CancellationReason.OPERATOR_CANCELLED:
            return frozenset({PLACED, STOCK_RESERVED, CREDIT_APPROVED, CONFIRMED})
        case _:
            assert_never(reason)


class Order(AggregateRoot):
    __slots__ = (
        "_buyer_gln",
        "_cancellation_reason",
        "_company_code",
        "_created_at",
        "_currency",
        "_initial_amount",
        "_initial_discount",
        "_lines",
        "_notes",
        "_order_date",
        "_order_reference",
        "_retailer_code",
        "_status",
        "_supplier_gln",
        "_total_amount",
        "_updated_at",
    )

    def __init__(
        self,
        *,
        order_id: UniqueId,
        order_reference: OrderNumber,
        order_date: datetime,
        retailer_code: str,
        buyer_gln: GLN,
        company_code: str,
        supplier_gln: GLN,
        currency: str,
        status: OrderStatus,
        cancellation_reason: CancellationReason | None,
        notes: str | None,
        lines: tuple[OrderLine, ...],
        totals: OrderTotals,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        """The only constructor path: use `place` or `rehydrate`, which validate."""
        super().__init__(order_id)
        self._order_reference = order_reference
        self._order_date = order_date
        self._retailer_code = retailer_code
        self._buyer_gln = buyer_gln
        self._company_code = company_code
        self._supplier_gln = supplier_gln
        self._currency = currency
        self._status = status
        self._cancellation_reason = cancellation_reason
        self._notes = notes
        self._lines = lines
        self._initial_amount = totals.initial_amount
        self._initial_discount = totals.initial_discount
        self._total_amount = totals.total_amount
        self._created_at = created_at
        self._updated_at = updated_at

    # ------------------------------------------------------------------------------ read model

    @property
    def order_reference(self) -> OrderNumber:
        return self._order_reference

    @property
    def order_date(self) -> datetime:
        return self._order_date

    @property
    def retailer_code(self) -> str:
        return self._retailer_code

    @property
    def buyer_gln(self) -> GLN:
        return self._buyer_gln

    @property
    def company_code(self) -> str:
        return self._company_code

    @property
    def supplier_gln(self) -> GLN:
        return self._supplier_gln

    @property
    def currency(self) -> str:
        return self._currency

    @property
    def status(self) -> OrderStatus:
        return self._status

    @property
    def cancellation_reason(self) -> CancellationReason | None:
        return self._cancellation_reason

    @property
    def notes(self) -> str | None:
        return self._notes

    @property
    def lines(self) -> tuple[OrderLine, ...]:
        return self._lines

    @property
    def initial_amount(self) -> Money:
        return self._initial_amount

    @property
    def initial_discount(self) -> Money:
        return self._initial_discount

    @property
    def total_amount(self) -> Money:
        return self._total_amount

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    # ----------------------------------------------------------------------------------- create

    @classmethod
    def place(
        cls,
        *,
        order_reference: OrderNumber,
        order_date: datetime,
        retailer_code: str,
        buyer_gln: GLN,
        company_code: str,
        supplier_gln: GLN,
        currency: str,
        lines: Sequence[OrderLineInput],
        notes: str | None,
        occurred_at: datetime,
        causation_id: UniqueId,
    ) -> Self:
        """T-1 row 1: creation. Checks, in order: O1, currency format, instants, O2, totals, O3."""
        requested = tuple(lines)
        if not requested:
            raise OrderMustHaveAtLeastOneLineError
        Money.zero(currency)  # refuses a malformed currency code before anything is built
        require_utc(order_date, field="order_date")
        require_utc(occurred_at, field="occurred_at")
        order_lines: list[OrderLine] = []
        for request in requested:
            cls._require_line_currency(currency, request.unit_price, request.line_discount)
            order_lines.append(
                OrderLine(
                    UniqueId.new(),
                    product_code=request.product_code,
                    description=request.description,
                    quantity=request.quantity,
                    unit_price=request.unit_price,
                    line_discount=request.line_discount,
                )
            )
        placed_lines = tuple(order_lines)
        totals = compute_totals(placed_lines, currency)
        if totals.total_amount.is_negative:
            raise OrderTotalMustNotBeNegativeError(totals.total_amount)
        order = cls(
            order_id=UniqueId.new(),
            order_reference=order_reference,
            order_date=order_date,
            retailer_code=retailer_code,
            buyer_gln=buyer_gln,
            company_code=company_code,
            supplier_gln=supplier_gln,
            currency=currency,
            status=PLACED,
            cancellation_reason=None,
            notes=notes,
            lines=placed_lines,
            totals=totals,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        order._raise_event(
            OrderPlaced(
                event_id=UniqueId.new(),
                aggregate_id=order.id,
                correlation_id=order.id,
                causation_id=causation_id,
                occurred_at=occurred_at,
                order_reference=order_reference,
                retailer_code=retailer_code,
                company_code=company_code,
                buyer_gln=buyer_gln,
                supplier_gln=supplier_gln,
                currency=currency,
                order_date=order_date,
                lines=tuple(
                    OrderPlacedLine(
                        product_code=line.product_code,
                        description=line.description,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                        line_discount=line.line_discount,
                    )
                    for line in placed_lines
                ),
                initial_amount=totals.initial_amount,
                initial_discount=totals.initial_discount,
                total_amount=totals.total_amount,
                notes=notes,
            )
        )
        return order

    # --------------------------------------------------------------------------------- rehydrate

    @classmethod
    def rehydrate(cls, snapshot: OrderSnapshot) -> Self:
        """Restore a stored order. Bypasses the state machine and raises no event.

        Nine checks, each with its own test (design.md 8.2). The totals are derived, never read.
        """
        if type(snapshot.status) is not OrderStatus:  # check 1
            raise InvalidOrderSnapshotError(f"status {snapshot.status!r} is not an OrderStatus")
        reason = snapshot.cancellation_reason
        if reason is not None and type(reason) is not CancellationReason:  # check 2
            raise InvalidOrderSnapshotError(f"{reason!r} is not a CancellationReason")
        if snapshot.status is CANCELLED and reason is None:  # check 3 (O6)
            raise InvalidOrderSnapshotError("a cancelled order has no cancellation reason")
        if snapshot.status is not CANCELLED and reason is not None:  # check 4 (O6)
            raise InvalidOrderSnapshotError(
                "an order that is not cancelled has a cancellation reason"
            )
        if not snapshot.lines:  # check 5 (O1)
            raise OrderMustHaveAtLeastOneLineError
        for stored in snapshot.lines:  # check 6 (O2)
            cls._require_currency("unit_price", snapshot.currency, stored.unit_price)
        for stored in snapshot.lines:  # check 7 (O2)
            cls._require_currency("line_discount", snapshot.currency, stored.line_discount)
        require_utc(snapshot.order_date, field="order_date")  # check 8
        require_utc(snapshot.created_at, field="created_at")
        require_utc(snapshot.updated_at, field="updated_at")
        restored = tuple(
            sorted(
                (
                    OrderLine(
                        stored.id,
                        product_code=stored.product_code,
                        description=stored.description,
                        quantity=stored.quantity,
                        unit_price=stored.unit_price,
                        line_discount=stored.line_discount,
                    )
                    for stored in snapshot.lines
                ),
                key=lambda line: line.id.value.int,
            )
        )
        totals = compute_totals(restored, snapshot.currency)
        if totals.total_amount.is_negative:  # check 9 (O3)
            raise OrderTotalMustNotBeNegativeError(totals.total_amount)
        return cls(
            order_id=snapshot.id,
            order_reference=snapshot.order_reference,
            order_date=snapshot.order_date,
            retailer_code=snapshot.retailer_code,
            buyer_gln=snapshot.buyer_gln,
            company_code=snapshot.company_code,
            supplier_gln=snapshot.supplier_gln,
            currency=snapshot.currency,
            status=snapshot.status,
            cancellation_reason=reason,
            notes=snapshot.notes,
            lines=restored,
            totals=totals,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
        )

    # ---------------------------------------------------------------------------- transitions

    def mark_stock_reserved(self, *, occurred_at: datetime) -> None:
        """T-1 row 2: silent (no fact is catalogued for this edge)."""
        require_utc(occurred_at, field="occurred_at")
        self._transition_to(STOCK_RESERVED, occurred_at=occurred_at)

    def approve_credit(self, *, occurred_at: datetime) -> None:
        """T-1 row 3: silent."""
        require_utc(occurred_at, field="occurred_at")
        self._transition_to(CREDIT_APPROVED, occurred_at=occurred_at)

    def confirm(self, *, occurred_at: datetime, causation_id: UniqueId) -> None:
        """T-1 row 4: raises `order.confirmed.v1`."""
        require_utc(occurred_at, field="occurred_at")

        def build() -> OrderEvent:
            return OrderConfirmed(
                event_id=UniqueId.new(),
                aggregate_id=self.id,
                correlation_id=self.id,
                causation_id=causation_id,
                occurred_at=occurred_at,
                order_reference=self._order_reference,
                retailer_code=self._retailer_code,
                company_code=self._company_code,
                currency=self._currency,
                total_amount=self._total_amount,
                confirmed_at=occurred_at,
            )

        self._transition_to(CONFIRMED, occurred_at=occurred_at, build_event=build)

    def mark_despatched(self, *, occurred_at: datetime) -> None:
        """T-1 row 5: silent."""
        require_utc(occurred_at, field="occurred_at")
        self._transition_to(DESPATCHED, occurred_at=occurred_at)

    def mark_invoiced(self, *, occurred_at: datetime) -> None:
        """T-1 row 6: silent."""
        require_utc(occurred_at, field="occurred_at")
        self._transition_to(INVOICED, occurred_at=occurred_at)

    def mark_paid(self, *, occurred_at: datetime) -> None:
        """T-1 row 7: silent."""
        require_utc(occurred_at, field="occurred_at")
        self._transition_to(PAID, occurred_at=occurred_at)

    def complete(self, *, occurred_at: datetime, causation_id: UniqueId) -> None:
        """T-1 row 8: raises `order.completed.v1`."""
        require_utc(occurred_at, field="occurred_at")

        def build() -> OrderEvent:
            return OrderCompleted(
                event_id=UniqueId.new(),
                aggregate_id=self.id,
                correlation_id=self.id,
                causation_id=causation_id,
                occurred_at=occurred_at,
                order_reference=self._order_reference,
                retailer_code=self._retailer_code,
                company_code=self._company_code,
                currency=self._currency,
                total_amount=self._total_amount,
                completed_at=occurred_at,
            )

        self._transition_to(COMPLETED, occurred_at=occurred_at, build_event=build)

    def cancel(
        self,
        *,
        reason: CancellationReason,
        compensation_steps: Sequence[CompensationStep],
        occurred_at: datetime,
        causation_id: UniqueId,
        note: str | None = None,
    ) -> None:
        """T-1 rows 9-12: raises `order.cancelled.v1`. Every refusal precedes every mutation."""
        # An annotation does not stop `None` or a bare `str` at run time (design.md L12).
        if reason is None:
            raise CancellationReasonRequiredError
        if type(reason) is not CancellationReason:
            raise UnknownCancellationReasonError(reason)
        require_utc(occurred_at, field="occurred_at")
        if not is_legal(self._status, CANCELLED):
            raise OrderNotCancellableError(self._status.value)
        if self._status not in _sources_for(reason):
            raise CancellationReasonNotApplicableError(reason.value, self._status.value)
        steps = tuple(compensation_steps)

        def build() -> OrderEvent:
            recorded = self._cancellation_reason
            if recorded is None:  # pragma: no cover - `_transition_to` records it first
                raise InvalidOrderSnapshotError("the cancellation reason was not recorded")
            return OrderCancelled(
                event_id=UniqueId.new(),
                aggregate_id=self.id,
                correlation_id=self.id,
                causation_id=causation_id,
                occurred_at=occurred_at,
                order_reference=self._order_reference,
                retailer_code=self._retailer_code,
                company_code=self._company_code,
                cancellation_reason=recorded,
                cancelled_at=occurred_at,
                compensation_steps=steps,
                note=note,
            )

        self._transition_to(
            CANCELLED, occurred_at=occurred_at, build_event=build, cancellation_reason=reason
        )

    def _transition_to(
        self,
        target: OrderStatus,
        *,
        occurred_at: datetime,
        build_event: Callable[[], OrderEvent] | None = None,
        cancellation_reason: CancellationReason | None = None,
    ) -> None:
        """The one funnel: the legality check is the first statement, every mutation is below it."""
        if not is_legal(self._status, target):
            raise IllegalOrderTransitionError(self._status.value, target.value)
        self._status = target
        if cancellation_reason is not None:
            self._cancellation_reason = cancellation_reason
        self._updated_at = occurred_at
        if build_event is not None:
            self._raise_event(build_event())

    # ----------------------------------------------------------------------------------- lines

    def add_line(
        self,
        *,
        product_code: str,
        description: str | None,
        quantity: Quantity,
        unit_price: Money,
        line_discount: Money,
        occurred_at: datetime,
    ) -> UniqueId:
        self._ensure_lines_mutable()
        require_utc(occurred_at, field="occurred_at")
        self._require_line_currency(self._currency, unit_price, line_discount)
        added = OrderLine(
            UniqueId.new(),
            product_code=product_code,
            description=description,
            quantity=quantity,
            unit_price=unit_price,
            line_discount=line_discount,
        )
        candidate = (*self._lines, added)
        totals = compute_totals(candidate, self._currency)
        if totals.total_amount.is_negative:
            raise OrderTotalMustNotBeNegativeError(totals.total_amount)
        self._commit_lines(candidate, totals, occurred_at)
        return added.id

    def remove_line(self, *, line_id: UniqueId, occurred_at: datetime) -> None:
        self._ensure_lines_mutable()
        require_utc(occurred_at, field="occurred_at")
        self._find_line(line_id)
        candidate = tuple(line for line in self._lines if line.id != line_id)
        totals = compute_totals(candidate, self._currency)
        if not candidate:
            raise OrderMustHaveAtLeastOneLineError
        if totals.total_amount.is_negative:
            raise OrderTotalMustNotBeNegativeError(totals.total_amount)
        self._commit_lines(candidate, totals, occurred_at)

    def change_line(
        self,
        *,
        line_id: UniqueId,
        quantity: Quantity,
        unit_price: Money,
        line_discount: Money,
        occurred_at: datetime,
    ) -> None:
        self._ensure_lines_mutable()
        require_utc(occurred_at, field="occurred_at")
        self._require_line_currency(self._currency, unit_price, line_discount)
        existing = self._find_line(line_id)
        replacement = OrderLine(
            line_id,
            product_code=existing.product_code,
            description=existing.description,
            quantity=quantity,
            unit_price=unit_price,
            line_discount=line_discount,
        )
        candidate = tuple(replacement if line.id == line_id else line for line in self._lines)
        totals = compute_totals(candidate, self._currency)
        if totals.total_amount.is_negative:
            raise OrderTotalMustNotBeNegativeError(totals.total_amount)
        self._commit_lines(candidate, totals, occurred_at)

    def _commit_lines(
        self, candidate: tuple[OrderLine, ...], totals: OrderTotals, occurred_at: datetime
    ) -> None:
        """The only place lines and totals change after construction (candidate-then-commit)."""
        self._lines = candidate
        self._initial_amount = totals.initial_amount
        self._initial_discount = totals.initial_discount
        self._total_amount = totals.total_amount
        self._updated_at = occurred_at

    def _ensure_lines_mutable(self) -> None:
        if self._status not in LINES_MUTABLE_IN:
            raise OrderLinesAreFrozenError(self._status.value)

    def _find_line(self, line_id: UniqueId) -> OrderLine:
        for line in self._lines:
            if line.id == line_id:
                return line
        raise OrderLineNotFoundError(line_id)

    @staticmethod
    def _require_currency(field: str, order_currency: str, amount: Money) -> None:
        if amount.currency != order_currency:
            raise OrderLineCurrencyMismatchError(field, order_currency, amount.currency)

    @staticmethod
    def _require_line_currency(
        order_currency: str, unit_price: Money, line_discount: Money
    ) -> None:
        """O2, one field at a time, so the caller sees the order invariant (not the kernel's)."""
        Order._require_currency("unit_price", order_currency, unit_price)
        Order._require_currency("line_discount", order_currency, line_discount)
