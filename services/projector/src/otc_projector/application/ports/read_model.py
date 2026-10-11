"""`ReadModelWriter`: the port through which a fact's `ProjectionDelta` reaches the read model.

`AppliedDocument` is the typed view of the POST-apply document that the update signal is built from
(`PR18`, `PR42`): the adapter converts the store's mapping into it, so no untyped document crosses
this port (ledger L30: no `typing.Any` in `domain` or `application/ports`).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from otc_projector.application.outcome import ProjectionOutcome
from otc_projector.domain.projection_delta import ProjectionDelta


@dataclass(frozen=True, slots=True)
class AppliedTotals:
    initial_amount: int
    initial_discount: int
    total_amount: int


@dataclass(frozen=True, slots=True)
class AppliedDocument:
    order_id: str
    order_reference: str | None
    status: str
    cancellation_reason: str | None
    despatch_reference: str | None
    invoice_reference: str | None
    payment_reference: str | None
    totals: AppliedTotals | None  # None while the header is unknown (a placeholder)


type AfterApplied = Callable[[AppliedDocument], Awaitable[None]]


class ReadModelWriter(Protocol):
    async def apply(
        self, delta: ProjectionDelta, *, after_applied: AfterApplied
    ) -> ProjectionOutcome:
        """Apply the fact atomically and exactly once.

        `after_applied` runs exactly once, with the post-apply document, when the fact was applied
        (`PROCESSED`), and never when it had been applied before (`DUPLICATE`).
        """
        ...
