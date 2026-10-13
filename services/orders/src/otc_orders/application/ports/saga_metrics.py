"""`SagaMetrics`: the port through which the saga reports how long an order took to close.

The application layer may not import OpenTelemetry, so the handler talks to this port and the
composition root binds an adapter over the `otc_saga_completion_ms` histogram (`R59`, `design.md`
6.2). `outcome` is the saga's terminal status token, `completed` or `cancelled`.
"""

from typing import Literal, Protocol

type SagaOutcome = Literal["completed", "cancelled"]


class SagaMetrics(Protocol):
    def closed(self, outcome: SagaOutcome, milliseconds: float) -> None:
        """One order's saga reached `outcome`, `milliseconds` after its `order_date`. Called ONLY
        after the step's transaction committed, and never raises into the saga."""
        ...


class NoSagaMetrics:
    """The scope of a runtime that exports no saga metric."""

    def closed(self, outcome: SagaOutcome, milliseconds: float) -> None:
        return None
