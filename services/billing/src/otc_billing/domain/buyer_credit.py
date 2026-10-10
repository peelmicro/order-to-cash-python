"""The `BuyerCredit` aggregate root: one credit line, with the ledger entries of the ONE order being
handled (`design.md` 5.1; B1 - B5; R37 - R41).

Synchronous and pure: no I/O, no clock, no port, no minting. Every entry id and every fact's
`event_id` comes from the `new_id` parameter at each of the six sites (`BC36`).

* B1 (`committed_exposure <= credit_limit`): `evaluate_hold` decides, `approve` refuses anything but
  `Fits`, `rehydrate` refuses a stored line already over its limit.
* B2 (append-only): entries are frozen values; a reversal appends a `release`, never rewrites; the
  aggregate exposes them only as a tuple.
* B3 (currency): entries are built in the line's currency; `evaluate_hold` answers
  `CurrencyMismatch` before `OverLimit`.
* B4 (one hold per order): `AlreadyHeld` on any recorded `hold` entry, whatever happened since.
* B5: `release` releases exactly `exposure(order)`; `None` when nothing is outstanding.
* Every mutation is all-or-nothing: compute and check, THEN assign. A raised error leaves
  `to_snapshot()` unchanged.

`committed_exposure` is the WHOLE line's two-term sum (`BC5`), computed in SQL and handed in as an
exact `int`; the entries are only the named order's, so `summary` describes that order.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Self

from otc_billing.domain.credit_entry_type import CreditEntryType
from otc_billing.domain.errors import (
    CreditLimitExceededError,
    CreditRefusalMismatchError,
    CreditReleaseUnderflowError,
    FactAggregateMismatchError,
    InvalidBuyerCreditSnapshotError,
    NoActiveHoldError,
)
from otc_billing.domain.events import (
    CreditApproved,
    CreditEvent,
    CreditRejected,
    CreditReleased,
)
from otc_billing.domain.exposure import LedgerLine, LedgerSummary, OrderExposure, summarise
from otc_billing.domain.ledger_entry import CreditLedgerEntry
from otc_billing.domain.reasons import CreditRejectionReason, CreditReleaseReason
from otc_billing.domain.snapshot import BuyerCreditSnapshot, CreditLedgerEntrySnapshot
from otc_shared_kernel import AggregateRoot, Money, UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CreditContext:
    """What the application supplies besides the ids: the instant (from the clock port) and the
    `causationId` (the request's `x-request-id`)."""

    occurred_at: datetime
    causation_id: UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class HoldRequest:
    order_reference: str
    amount: Money
    correlation_id: UniqueId


@dataclass(frozen=True, slots=True)
class AlreadyHeld:
    held_amount: Money


@dataclass(frozen=True, slots=True)
class CurrencyMismatch:
    expected: str
    received: str


@dataclass(frozen=True, slots=True)
class OverLimit:
    available_credit: Money


@dataclass(frozen=True, slots=True)
class Fits:
    pass


type HoldEvaluation = AlreadyHeld | CurrencyMismatch | OverLimit | Fits


def _line(entry: CreditLedgerEntry) -> LedgerLine:
    return LedgerLine(entry.order_reference, entry.type, entry.amount.amount)


def _snapshot_of(entry: CreditLedgerEntry) -> CreditLedgerEntrySnapshot:
    return CreditLedgerEntrySnapshot(
        entry_id=entry.entry_id,
        order_reference=entry.order_reference,
        amount=entry.amount,
        type=entry.type,
        entry_date=entry.entry_date,
    )


class BuyerCredit(AggregateRoot):
    __slots__ = (
        "_appended",
        "_code",
        "_committed_exposure",
        "_company_code",
        "_credit_limit",
        "_entries",
        "_retailer_code",
    )

    def __init__(
        self,
        credit_id: UniqueId,
        *,
        code: str,
        retailer_code: str,
        company_code: str,
        credit_limit: Money,
        committed_exposure: int,
        entries: list[CreditLedgerEntry],
    ) -> None:
        super().__init__(credit_id)
        self._code = code
        self._retailer_code = retailer_code
        self._company_code = company_code
        self._credit_limit = credit_limit
        self._committed_exposure = committed_exposure
        self._entries = entries
        self._appended: list[CreditLedgerEntry] = []

    @classmethod
    def rehydrate(cls, snapshot: BuyerCreditSnapshot) -> Self:
        """Restore a stored line. Bypasses the operations and raises no event.

        Refuses: a non-`int` or negative limit, a non-`int` committed exposure, a committed
        exposure above the limit (B1, the outer bound of `BC30`), an entry whose currency differs
        from the line's (B3) and entries of more than one order.
        """
        if type(snapshot.credit_limit) is not int or snapshot.credit_limit < 0:
            raise InvalidBuyerCreditSnapshotError(
                f"credit limit {snapshot.credit_limit!r} is not a non-negative int"
            )
        if type(snapshot.committed_exposure) is not int:
            raise InvalidBuyerCreditSnapshotError(
                f"committed exposure {snapshot.committed_exposure!r} is not an int"
            )
        limit = Money(snapshot.credit_limit, snapshot.currency)
        if snapshot.committed_exposure > snapshot.credit_limit:
            raise InvalidBuyerCreditSnapshotError(
                f"committed exposure {Money(snapshot.committed_exposure, snapshot.currency)} "
                f"exceeds the credit limit {limit}"
            )
        entries: list[CreditLedgerEntry] = []
        for stored in snapshot.entries:
            if stored.amount.currency != snapshot.currency:
                raise InvalidBuyerCreditSnapshotError(
                    f"entry {stored.entry_id} is in {stored.amount.currency}, not in the "
                    f"line's {snapshot.currency}"
                )
            entries.append(
                CreditLedgerEntry(
                    entry_id=stored.entry_id,
                    order_reference=stored.order_reference,
                    amount=stored.amount,
                    type=stored.type,
                    entry_date=stored.entry_date,
                )
            )
        if len({e.order_reference for e in entries}) > 1:
            raise InvalidBuyerCreditSnapshotError("the entries belong to more than one order")
        return cls(
            snapshot.id,
            code=snapshot.code,
            retailer_code=snapshot.retailer_code,
            company_code=snapshot.company_code,
            credit_limit=limit,
            committed_exposure=snapshot.committed_exposure,
            entries=entries,
        )

    # ----------------------------------------------------------------------------------- reads

    @property
    def code(self) -> str:
        return self._code

    @property
    def retailer_code(self) -> str:
        return self._retailer_code

    @property
    def company_code(self) -> str:
        return self._company_code

    @property
    def currency(self) -> str:
        return self._credit_limit.currency

    @property
    def credit_limit(self) -> Money:
        return self._credit_limit

    @property
    def committed_exposure(self) -> Money:
        return Money(self._committed_exposure, self.currency)

    @property
    def available_credit(self) -> Money:
        """BC5: the limit minus the committed exposure; a consume entry moves it by nothing."""
        return Money(self._credit_limit.amount - self._committed_exposure, self.currency)

    @property
    def entries(self) -> tuple[CreditLedgerEntry, ...]:
        return tuple(self._entries)

    @property
    def appended_entries(self) -> tuple[CreditLedgerEntry, ...]:
        """What the repository inserts: the entries appended since `rehydrate`."""
        return tuple(self._appended)

    @property
    def summary(self) -> LedgerSummary:
        """BC6 over the loaded and appended entries (one order)."""
        return summarise(_line(e) for e in self._entries)

    def _order_exposure(self, order_reference: str) -> OrderExposure | None:
        for exposure in summarise(
            _line(e) for e in self._entries if e.order_reference == order_reference
        ).by_order:
            return exposure
        return None

    # --------------------------------------------------------------------------------- the hold

    def evaluate_hold(self, request: HoldRequest) -> HoldEvaluation:
        """Pure: no mutation, no event, no port. BC26's order: already held, currency, limit."""
        for entry in self._entries:
            if entry.order_reference == request.order_reference and (
                entry.type is CreditEntryType.HOLD
            ):
                return AlreadyHeld(held_amount=entry.amount)
        if request.amount.currency != self.currency:
            return CurrencyMismatch(expected=self.currency, received=request.amount.currency)
        available = self.available_credit
        if request.amount > available:
            return OverLimit(available_credit=available)
        return Fits()

    def approve(
        self, request: HoldRequest, context: CreditContext, new_id: Callable[[], UniqueId]
    ) -> CreditLedgerEntry:
        """Append one `hold` entry and raise one `CreditApproved` whose `available_credit_after`
        is recomputed WITH the entry (BC10). Refuses anything but `Fits` (B1 cannot be bypassed)."""
        evaluation = self.evaluate_hold(request)
        match evaluation:
            case Fits():
                pass
            case OverLimit():
                raise CreditLimitExceededError(
                    request.amount.amount, evaluation.available_credit.amount, self.currency
                )
            case AlreadyHeld() | CurrencyMismatch():
                raise CreditRefusalMismatchError(
                    "approved",
                    request.amount.amount,
                    self.available_credit.amount,
                    self.currency,
                )
        entry = CreditLedgerEntry(
            entry_id=new_id(),
            order_reference=request.order_reference,
            amount=request.amount,
            type=CreditEntryType.HOLD,
            entry_date=context.occurred_at,
        )
        committed_after = self._committed_exposure + request.amount.amount
        available_after = Money(self._credit_limit.amount - committed_after, self.currency)
        fact = CreditApproved(
            event_id=new_id(),
            aggregate_id=self.id,
            correlation_id=request.correlation_id,
            causation_id=context.causation_id,
            occurred_at=context.occurred_at,
            order_reference=request.order_reference,
            retailer_code=self._retailer_code,
            company_code=self._company_code,
            credit_code=self._code,
            currency=self.currency,
            held_amount=request.amount.amount,
            available_credit_after=available_after.amount,
        )
        self._entries.append(entry)
        self._appended.append(entry)
        self._committed_exposure = committed_after
        self._raise_event(fact)
        return entry

    def refuse(
        self,
        request: HoldRequest,
        reason: CreditRejectionReason,
        context: CreditContext,
        new_id: Callable[[], UniqueId],
    ) -> None:
        """Append NOTHING; raise one `CreditRejected` with the requested amount, the unchanged
        available credit and the reason. The ONE builder of every refusal (BC14, R44). A refusal
        may not lie: `over_limit` while the amount fits raises."""
        available = self.available_credit
        fits = request.amount.currency == self.currency and request.amount <= available
        if reason is CreditRejectionReason.OVER_LIMIT and fits:
            raise CreditRefusalMismatchError(
                reason.value, request.amount.amount, available.amount, self.currency
            )
        self._raise_event(
            CreditRejected(
                event_id=new_id(),
                aggregate_id=self.id,
                correlation_id=request.correlation_id,
                causation_id=context.causation_id,
                occurred_at=context.occurred_at,
                order_reference=request.order_reference,
                retailer_code=self._retailer_code,
                company_code=self._company_code,
                credit_code=self._code,
                currency=self.currency,
                requested_amount=request.amount.amount,
                available_credit=available.amount,
                reason=reason,
            )
        )

    # ---------------------------------------------------------------- release and consume

    def release(
        self,
        order_reference: str,
        reason: CreditReleaseReason,
        correlation_id: UniqueId,
        context: CreditContext,
        new_id: Callable[[], UniqueId],
    ) -> CreditLedgerEntry | None:
        """Release the order's OUTSTANDING exposure: a `hold` entry and no `release` entry (BC11).
        Nothing outstanding: `None`, nothing appended, nothing raised. A consumed hold is released
        like any other (`exposure` ignores `consume`)."""
        order = self._order_exposure(order_reference)
        if order is None:
            return None
        if order.exposure < 0:
            # B5: a ledger that already releases more than it held is corrupt; say so loudly
            raise CreditReleaseUnderflowError(order_reference, order.exposure, self.currency)
        if not order.has_hold_entry or order.has_release_entry:
            return None
        released = Money(order.exposure, self.currency)
        entry = CreditLedgerEntry(
            entry_id=new_id(),
            order_reference=order_reference,
            amount=released,
            type=CreditEntryType.RELEASE,
            entry_date=context.occurred_at,
        )
        committed_after = self._committed_exposure - order.exposure
        fact = CreditReleased(
            event_id=new_id(),
            aggregate_id=self.id,
            correlation_id=correlation_id,
            causation_id=context.causation_id,
            occurred_at=context.occurred_at,
            order_reference=order_reference,
            retailer_code=self._retailer_code,
            company_code=self._company_code,
            credit_code=self._code,
            currency=self.currency,
            released_amount=order.exposure,
            available_credit_after=self._credit_limit.amount - committed_after,
            reason=reason,
        )
        self._entries.append(entry)
        self._appended.append(entry)
        self._committed_exposure = committed_after
        self._raise_event(fact)
        return entry

    def consume(
        self, order_reference: str, context: CreditContext, new_id: Callable[[], UniqueId]
    ) -> CreditLedgerEntry:
        """Turn the order's ACTIVE hold into open exposure (R40): a `hold` entry and neither a
        `consume` nor a `release` entry (BC12). Appends one `consume` entry, raises NO event, and
        leaves `committed_exposure` (so the available credit) unchanged."""
        order = self._order_exposure(order_reference)
        if (
            order is None
            or not order.has_hold_entry
            or order.has_consume_entry
            or order.has_release_entry
        ):
            raise NoActiveHoldError(order_reference)
        entry = CreditLedgerEntry(
            entry_id=new_id(),
            order_reference=order_reference,
            amount=Money(order.active_hold, self.currency),
            type=CreditEntryType.CONSUME,
            entry_date=context.occurred_at,
        )
        self._entries.append(entry)
        self._appended.append(entry)
        return entry

    def record_fact(self, fact: CreditEvent) -> None:
        """Append an externally built fact on this line; refuses one about another aggregate."""
        if fact.aggregate_id != self.id:
            raise FactAggregateMismatchError(self.id, fact.aggregate_id)
        self._raise_event(fact)

    def to_snapshot(self) -> BuyerCreditSnapshot:
        return BuyerCreditSnapshot(
            id=self.id,
            code=self._code,
            retailer_code=self._retailer_code,
            company_code=self._company_code,
            currency=self.currency,
            credit_limit=self._credit_limit.amount,
            committed_exposure=self._committed_exposure,
            entries=tuple(_snapshot_of(e) for e in self._entries),
        )
