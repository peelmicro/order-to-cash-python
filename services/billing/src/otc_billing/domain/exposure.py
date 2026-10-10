"""`summarise`: the crux, one pure function (`design.md` 5.3).

The one place `BC5` / `BC6` are computed, by the aggregate and by the list view alike (#7's
`credit-exposure.ts`, #8's `CreditExposure.Summarise`):

    exposure(order)      = sum hold(order) - sum release(order)
    open_exposure(order) = min(sum consume(order), exposure(order))
    active_hold(order)   = exposure(order) - open_exposure(order)
    committed_exposure   = sum over orders of exposure(order)

so `sum active_hold + sum open_exposure = committed_exposure` on every ledger shape, and a consume
entry appears in neither term of the committed exposure (R40's neutrality is a property of this
function, not a rule). The naive reading (`sum consume - sum release`) goes negative for an order
cancelled before invoicing; this one does not.

Grouping is a `dict` keyed by the STORED `order_reference`, in first-seen order (L17): exact `==`
agrees with PostgreSQL's case-sensitive collation. Python's `int` never wraps, so "not wrapped" is
free; the RAISE is not: every accumulated value is checked against the signed 64-bit range as it is
produced, and an out-of-range one raises `CreditLedgerOverflowError` (`BC30`, L25).
"""

from collections.abc import Iterable
from dataclasses import dataclass

from otc_billing.domain.credit_entry_type import CreditEntryType
from otc_billing.domain.errors import CreditLedgerOverflowError

INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1


@dataclass(frozen=True, slots=True)
class LedgerLine:
    """What the summary needs of an entry: the order, the kind and the minor-unit amount."""

    order_reference: str
    type: CreditEntryType
    amount: int


@dataclass(frozen=True, slots=True)
class OrderExposure:
    order_reference: str
    exposure: int
    open_exposure: int
    active_hold: int
    has_hold_entry: bool
    has_consume_entry: bool
    has_release_entry: bool


@dataclass(frozen=True, slots=True)
class LedgerSummary:
    by_order: tuple[OrderExposure, ...]
    committed_exposure: int
    active_holds: int
    open_exposure: int


def _checked(value: int, what: str) -> int:
    if not INT64_MIN <= value <= INT64_MAX:
        raise CreditLedgerOverflowError(what)
    return value


@dataclass(slots=True)
class _Totals:
    hold: int = 0
    consume: int = 0
    release: int = 0
    has_hold: bool = False
    has_consume: bool = False
    has_release: bool = False


def summarise(lines: Iterable[LedgerLine]) -> LedgerSummary:
    totals: dict[str, _Totals] = {}
    for line in lines:
        order = totals.setdefault(line.order_reference, _Totals())
        label = f"ledger total of order {line.order_reference}"
        match line.type:
            case CreditEntryType.HOLD:
                order.hold = _checked(order.hold + line.amount, f"hold {label}")
                order.has_hold = True
            case CreditEntryType.CONSUME:
                order.consume = _checked(order.consume + line.amount, f"consume {label}")
                order.has_consume = True
            case CreditEntryType.RELEASE:
                order.release = _checked(order.release + line.amount, f"release {label}")
                order.has_release = True
    by_order: list[OrderExposure] = []
    committed = 0
    active_holds = 0
    open_total = 0
    for reference, order in totals.items():
        exposure = _checked(order.hold - order.release, f"exposure of order {reference}")
        open_exposure = min(order.consume, exposure)
        active_hold = _checked(exposure - open_exposure, f"active hold of order {reference}")
        committed = _checked(committed + exposure, "committed exposure of the credit line")
        active_holds = _checked(active_holds + active_hold, "active holds of the credit line")
        open_total = _checked(open_total + open_exposure, "open exposure of the credit line")
        by_order.append(
            OrderExposure(
                order_reference=reference,
                exposure=exposure,
                open_exposure=open_exposure,
                active_hold=active_hold,
                has_hold_entry=order.has_hold,
                has_consume_entry=order.has_consume,
                has_release_entry=order.has_release,
            )
        )
    return LedgerSummary(
        by_order=tuple(by_order),
        committed_exposure=committed,
        active_holds=active_holds,
        open_exposure=open_total,
    )
