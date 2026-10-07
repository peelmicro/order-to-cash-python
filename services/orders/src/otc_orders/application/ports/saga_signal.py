"""`SagaCommandSignal`: the in-process hop from "a command is owed" to "issue it now".

Design: `design.md` 8.

The durable `saga_commands` row is the delivery guarantee; this signal is an optimisation over it.
"""

from dataclasses import dataclass
from typing import Protocol

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_shared_kernel import UniqueId


@dataclass(frozen=True, slots=True)
class SagaCommandRef:
    order_id: UniqueId
    kind: SagaCommandKind


class SagaCommandSignal(Protocol):
    def signal(self, ref: SagaCommandRef) -> None:
        """Ask for `ref` to be issued now. NEVER blocks and NEVER raises: a signal that cannot be
        honoured (not running, full) is dropped, and the sweeper issues the row from the table."""
        ...
