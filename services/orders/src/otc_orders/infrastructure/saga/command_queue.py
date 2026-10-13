"""`SqlAlchemySagaCommandQueue`: enqueue an owed command inside the fact's transaction (`design.md`
7.5).

`INSERT ... ON CONFLICT (order_id, command) DO NOTHING RETURNING id`: no row back means the command
is already owed or already sent, which is not an error. The engine differs from #7's and #8's: any
error aborts a PostgreSQL transaction, so a caught unique violation would leave nothing usable; `ON
CONFLICT DO NOTHING` returns normally and the transaction stays usable (#7 D1: a duplicate enqueue
that poisoned the partition).

`attempts` is not written (the server default is `0`), so this ORM-enabled insert writes no guarded
integer column. The payload is the request model serialised once by the caller (`to_wire_json`) and
stored as the text that will be sent (L21).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from otc_orders.application.ports.clock import Clock
from otc_orders.application.ports.saga_command_store import (
    AcceptedOperatorCancel,
    EnqueueOutcome,
    FirstParkClaim,
    OwedCommand,
)
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.infrastructure.observability.trace_context import current_traceparent
from otc_orders.infrastructure.persistence.models import SagaCommand
from otc_shared_kernel import UniqueId

# The `stock.release` request's `reason` that marks an accepted operator cancellation
# (`asyncapi.yaml` `StockReleaseRequestPayload`; the saga's own release carries `credit_rejected`).
OPERATOR_CANCEL_RELEASE_REASON = "order_cancelled"


class SqlAlchemySagaCommandQueue:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    async def enqueue(self, command: OwedCommand) -> EnqueueOutcome:
        now = self._clock.now()
        inserted = (
            await self._session.execute(
                pg_insert(SagaCommand)
                .values(
                    id=uuid4(),
                    order_id=command.order_id.value,
                    order_reference=command.order_reference,
                    command=command.kind.value,
                    payload=command.payload,
                    triggering_event_id=command.triggering_event_id.value,
                    operator_note=command.operator_note,
                    triggering_event_envelope=command.triggering_event_envelope,
                    triggering_event_topic=command.triggering_event_topic,
                    trace_parent=current_traceparent(),
                    status="pending",
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["order_id", "command"])
                .returning(SagaCommand.id)
            )
        ).first()
        return EnqueueOutcome.ENQUEUED if inserted is not None else EnqueueOutcome.ALREADY_OWED

    async def claim_first_park(self, row_id: UUID, *, at: datetime) -> FirstParkClaim | None:
        claimed = (
            await self._session.execute(
                update(SagaCommand)
                .where(
                    SagaCommand.id == row_id,
                    SagaCommand.status == "parked",
                    SagaCommand.dead_lettered_at.is_(None),
                )
                .values(dead_lettered_at=at)
                .returning(
                    SagaCommand.triggering_event_envelope,
                    SagaCommand.triggering_event_topic,
                    SagaCommand.first_failed_at,
                )
                .execution_options(synchronize_session=False)
            )
        ).first()
        if claimed is None:
            return None
        return FirstParkClaim(
            envelope=None if claimed[0] is None else bytes(claimed[0]),
            topic=claimed[1],
            first_failed_at=claimed[2],
        )

    async def find_accepted_operator_cancel(
        self, order_id: UniqueId
    ) -> AcceptedOperatorCancel | None:
        # `payload` is a `json` column (never `jsonb`): `json_extract_path_text` reads the request's
        # own `reason`, so the answer is decided by what was sent to Fulfillment, not by a column
        # that could drift from it. Three narrowings, each guarded against a decoy row: the order,
        # the command, the reason.
        row = (
            await self._session.execute(
                select(SagaCommand.operator_note).where(
                    SagaCommand.order_id == order_id.value,
                    SagaCommand.command == SagaCommandKind.STOCK_RELEASE.value,
                    func.json_extract_path_text(SagaCommand.payload, "reason")
                    == OPERATOR_CANCEL_RELEASE_REASON,
                )
            )
        ).first()
        return None if row is None else AcceptedOperatorCancel(note=row.operator_note)
