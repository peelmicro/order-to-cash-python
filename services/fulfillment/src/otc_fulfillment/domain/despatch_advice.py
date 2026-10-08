"""`DespatchAdvice`: the DESADV aggregate root (R36; F6, F7, F8's creation half).

Created once, by `order_despatch.despatch_order`, from reservations the same operation moved to
`consumed`; never mutated again. `create` refuses an empty line list (F6) and appends the ONE
`order.despatched.v1` before it returns, so no caller can hold an advice whose fact was not
recorded.

Nothing is minted here: the advice id, every line id and the fact's event id are PARAMETERS, so the
operation above supplies all of them from its `new_id` (FS24, #8 id 49: every mint site is
guarded by a test that supplies the ids and compares them).

The lines are held in the CANONICAL order `(product_code, line id)` (`line_order_key`). The line
table has no position column, so the order a stored advice comes back in must be derivable from the
rows: the repository sorts a reload with the same key, in Python (never by the database's
collation), and a repeat (F8) therefore answers with the same line order as the creation did.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from otc_fulfillment.domain.errors import EmptyDespatchLinesError
from otc_fulfillment.domain.events import DespatchedLine, OrderDespatched
from otc_fulfillment.domain.snapshot import DespatchLineSnapshot, DespatchSnapshot
from otc_shared_kernel import AggregateRoot, DespatchReference, Quantity, UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class DespatchLine:
    id: UniqueId
    product_code: str
    units: Quantity


def line_order_key(product_code: str, line_id: UniqueId) -> tuple[str, int]:
    """The canonical line order: exact product code (code-point order), then the line id."""
    return (product_code, line_id.value.int)


class DespatchAdvice(AggregateRoot):
    __slots__ = (
        "_company_code",
        "_despatch_date",
        "_despatch_reference",
        "_lines",
        "_order_reference",
        "_retailer_code",
    )

    def __init__(
        self,
        advice_id: UniqueId,
        *,
        despatch_reference: DespatchReference,
        despatch_date: datetime,
        order_reference: str,
        company_code: str,
        retailer_code: str,
        lines: tuple[DespatchLine, ...],
    ) -> None:
        super().__init__(advice_id)
        self._despatch_reference = despatch_reference
        self._despatch_date = despatch_date
        self._order_reference = order_reference
        self._company_code = company_code
        self._retailer_code = retailer_code
        self._lines = lines

    @classmethod
    def create(
        cls,
        *,
        advice_id: UniqueId,
        event_id: UniqueId,
        despatch_reference: DespatchReference,
        despatch_date: datetime,
        order_reference: str,
        company_code: str,
        retailer_code: str,
        lines: Sequence[DespatchLine],
        correlation_id: UniqueId,
        causation_id: UniqueId,
    ) -> DespatchAdvice:
        if not lines:
            raise EmptyDespatchLinesError(order_reference)  # F6
        ordered = tuple(sorted(lines, key=lambda ln: line_order_key(ln.product_code, ln.id)))
        advice = cls(
            advice_id,
            despatch_reference=despatch_reference,
            despatch_date=despatch_date,
            order_reference=order_reference,
            company_code=company_code,
            retailer_code=retailer_code,
            lines=ordered,
        )
        advice._raise_event(
            OrderDespatched(
                event_id=event_id,
                aggregate_id=advice_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                occurred_at=despatch_date,
                order_reference=order_reference,
                despatch_reference=despatch_reference,
                despatch_date=despatch_date,
                company_code=company_code,
                retailer_code=retailer_code,
                lines=tuple(
                    DespatchedLine(product_code=ln.product_code, units=ln.units.value)
                    for ln in ordered
                ),
            )
        )
        return advice

    @property
    def despatch_reference(self) -> DespatchReference:
        return self._despatch_reference

    @property
    def despatch_date(self) -> datetime:
        return self._despatch_date

    @property
    def order_reference(self) -> str:
        return self._order_reference

    @property
    def company_code(self) -> str:
        return self._company_code

    @property
    def retailer_code(self) -> str:
        return self._retailer_code

    @property
    def lines(self) -> tuple[DespatchLine, ...]:
        return self._lines

    def to_snapshot(self) -> DespatchSnapshot:
        return DespatchSnapshot(
            id=self.id,
            despatch_reference=self._despatch_reference,
            despatch_date=self._despatch_date,
            order_reference=self._order_reference,
            company_code=self._company_code,
            retailer_code=self._retailer_code,
            lines=tuple(
                DespatchLineSnapshot(id=ln.id, product_code=ln.product_code, units=ln.units.value)
                for ln in self._lines
            ),
        )
