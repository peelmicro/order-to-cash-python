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
    # Only the operator's `stock.release` carries one (feature 41): the note of the accepted
    # cancellation, kept beside the row because the request itself declares no `note`.
    operator_note: str | None = None
    # What the fact that owes this command was, as received (`R29`, `OR3`): the bytes and the topic
    # they came from. Both `None` for a command no fact triggered (the operator cancel's release).
    triggering_event_envelope: bytes | None = None
    triggering_event_topic: str | None = None


@dataclass(frozen=True, slots=True)
class FirstParkClaim:
    """What the one claim of a command's first park returns (`R29`, `OR3`): the received bytes of
    the fact that owed the command and the topic they came from, both `None` when no fact owed it
    (the operator cancel's release, gate G1) or the row predates migration 0003."""

    envelope: bytes | None
    topic: str | None
    # The instant the row's FIRST failed attempt was recorded (SA-3 `x-first-failed-at`). A row
    # that carries an envelope was parked by a build that records it, so it is set whenever
    # `envelope` is.
    first_failed_at: datetime | None


@dataclass(frozen=True, slots=True)
class AcceptedOperatorCancel:
    """An operator cancellation accepted for an order whose cancellation has not completed (or has
    completed through the saga): the `stock.release` row the cancel enqueued. `note` is the
    operator's note, or `None` when none was given."""

    note: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaimedCommand:
    id: UUID
    order_id: UniqueId
    order_reference: str
    kind: SagaCommandKind
    payload: str
    attempts: int
    triggering_event_id: UniqueId
    # The `traceparent` recorded when the command was enqueued (`OR4`, `OR10`): the sweeper has no
    # live trace of its own, so the dispatch span restores this one. `None` when none was recorded.
    trace_parent: str | None


class SagaCommandQueue(Protocol):
    async def enqueue(self, command: OwedCommand) -> EnqueueOutcome:
        """Idempotent on (order, kind): a command already owed is not an error and leaves the
        existing row untouched, so the surrounding transaction stays usable."""
        ...

    async def claim_first_park(self, row_id: UUID, *, at: datetime) -> FirstParkClaim | None:
        """ONE statement (`UPDATE ... WHERE id AND status = 'parked' AND dead_lettered_at IS NULL
        RETURNING ...`) whose returned row IS the answer: a claim is won by exactly one caller, and
        a row already claimed (or not parked) answers `None`. Never select-then-update (#8 L16)."""
        ...

    async def find_accepted_operator_cancel(
        self, order_id: UniqueId
    ) -> AcceptedOperatorCancel | None:
        """The operator cancellation accepted for `order_id`, if any: the order's `stock.release`
        row whose request carries the reason `order_cancelled` (the saga's own `stock.release`,
        after a credit rejection, carries `credit_rejected` and is NOT one). Whatever the row's
        status: a `sent` row still means the cancellation was requested. Read inside the caller's
        transaction, after the caller holds the order row (SO17)."""
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

    async def reject(
        self, row_id: UUID, *, total_attempts: int, last_error: str, first_failed_at: datetime
    ) -> None:
        """Resolve the row to the terminal `rejected` status (feature 42), clearing the lease; only
        a pending or parked row. Nothing claims, parks or marks it sent afterwards.
        `first_failed_at` is kept only if the row has none yet (`COALESCE`)."""
        ...

    async def park(
        self,
        row_id: UUID,
        *,
        total_attempts: int,
        last_error: str,
        retry_after_ms: int,
        first_failed_at: datetime,
    ) -> datetime:
        """Park the row (never a `sent` or `rejected` one); returns the next attempt instant.
        `first_failed_at` is the instant of this dispatch's first failed attempt, kept only if the
        row has none yet (`COALESCE`): the first failure of the row's life, never overwritten."""
        ...
