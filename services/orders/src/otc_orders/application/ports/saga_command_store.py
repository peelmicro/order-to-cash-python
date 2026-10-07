"""The owed-command store, as two ports (`design.md` 2, 9.6).

`SagaCommandQueue.enqueue` happens INSIDE the fact's transaction and is reachable only through the
transaction object, as the repository is. The ledger's claim, mark and park are single statements
outside any fact transaction, each in its own short session; one port with both would let a caller
enqueue outside the fact's transaction.
"""

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_shared_kernel import UniqueId


class EnqueueOutcome(enum.Enum):
    ENQUEUED = "enqueued"
    # a row exists for (order, kind): pending, parked, sent or rejected
    ALREADY_OWED = "already_owed"


@dataclass(frozen=True, slots=True, kw_only=True)
class OwedCommand:
    order_id: UniqueId
    order_reference: str
    kind: SagaCommandKind
    payload: str  # the request model, serialised once by `to_wire_json`: the bytes that are sent
    triggering_event_id: UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaimedCommand:
    id: UUID
    order_id: UniqueId
    order_reference: str
    kind: SagaCommandKind
    payload: str
    attempts: int
    triggering_event_id: UniqueId


class SagaCommandQueue(Protocol):
    async def enqueue(self, command: OwedCommand) -> EnqueueOutcome:
        """Idempotent on (order, kind): a command already owed is not an error and leaves the
        existing row untouched, so the surrounding transaction stays usable."""
        ...


class SagaCommandLedger(Protocol):
    async def try_claim(self, order_id: UniqueId, kind: SagaCommandKind) -> ClaimedCommand | None:
        """Take the lease on one row; `None` when it is absent, sent, parked and not yet due, or
        leased by someone else."""
        ...

    async def claim_due(self, batch_limit: int) -> list[ClaimedCommand]:
        """Take the lease on a batch of due rows, skipping rows another claimer holds."""
        ...

    async def mark_sent(self, row_id: UUID) -> None: ...

    async def reject(self, row_id: UUID, *, total_attempts: int, last_error: str) -> None:
        """Resolve the row to the terminal `rejected` status (feature 42), clearing the lease; only
        a pending or parked row. Nothing claims, parks or marks it sent afterwards."""
        ...

    async def park(
        self, row_id: UUID, *, total_attempts: int, last_error: str, retry_after_ms: int
    ) -> datetime:
        """Park the row (never a `sent` or `rejected` one); returns the next attempt instant."""
        ...
