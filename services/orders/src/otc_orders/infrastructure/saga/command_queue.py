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

from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from otc_orders.application.ports.clock import Clock
from otc_orders.application.ports.saga_command_store import EnqueueOutcome, OwedCommand
from otc_orders.infrastructure.persistence.models import SagaCommand


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
                    status="pending",
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["order_id", "command"])
                .returning(SagaCommand.id)
            )
        ).first()
        return EnqueueOutcome.ENQUEUED if inserted is not None else EnqueueOutcome.ALREADY_OWED
