"""`SqlAlchemySagaFirstPark`: what happens when a saga command is parked FOR THE FIRST TIME
(`R29`, `OR3`; `design.md` 5.6, gate G4).

1. **One transaction.** The order row is locked (`FOR UPDATE OF orders`), then ONE statement claims
   the first park: it sets `dead_lettered_at` on the parked row that has none yet and RETURNS the
   stored envelope and topic, so the returned row is the answer, never a select followed by a
   write (#8 L16). If a row came back the order records `order.saga_failed.v1` and is saved, so the
   outbox row commits WITH the claim (#8 L17). The lock is taken before the claim, not after as the
   design text lists them, because every other writer of these two rows (a fact's handler, the
   operator cancel) locks the order first and then touches `saga_commands`; the claim first would
   hold a `saga_commands` row while waiting for the order and could deadlock with them.
2. **After the commit**, if the claim carried an envelope, its bytes are dead-lettered to
   `<topic>.dlq` (`x-failed-consumer` `orders.saga`, `x-attempts` the row's accumulated attempts,
   `x-error` the last error, `x-first-failed-at` the instant the row's first failed attempt was
   recorded, `x-failed-at` the park's: SA-3 says they are equal only when one attempt was made).
   A publication that fails is logged at ERROR naming the row id and the bytes stay in the row for
   a manual republish: the park itself and the `order.saga_failed.v1` fact are already durable (G4:
   #8's order, not #7's publish-first).

A row with no envelope (the operator cancel's compensation, gate G1; a row parked before migration
0003) appends the fact and publishes nothing. Every later park of the same row claims nothing and
emits neither.
"""

import logging

from otc_contracts import Envelope, from_wire_json
from otc_orders.application.ports.clock import Clock
from otc_orders.application.ports.saga_command_store import ClaimedCommand
from otc_orders.application.ports.unit_of_work import UnitOfWork
from otc_orders.infrastructure.messaging.fact_retry import DeadLetter, DeadLetterPublisher

log = logging.getLogger("otc_orders.saga.first_park")

CONSUMER = "orders.saga"
UNKNOWN_EVENT_TYPE = "unknown"


class SqlAlchemySagaFirstPark:
    def __init__(
        self, *, unit_of_work: UnitOfWork, dead_letters: DeadLetterPublisher, clock: Clock
    ) -> None:
        self._unit_of_work = unit_of_work
        self._dead_letters = dead_letters
        self._clock = clock

    async def on_parked(self, row: ClaimedCommand, *, total_attempts: int, last_error: str) -> None:
        now = self._clock.now()
        async with self._unit_of_work.begin() as transaction:
            order = await transaction.orders.get_by_id_for_update(row.order_id)
            claim = await transaction.saga_commands.claim_first_park(row.id, at=now)
            if claim is None:
                return
            if order is None:
                raise RuntimeError(f"saga command {row.id}: order {row.order_id} does not exist")
            order.record_saga_failure(
                command=row.kind.value,
                attempts=total_attempts,
                last_error=last_error,
                occurred_at=now,
                causation_id=row.triggering_event_id,
            )
            await transaction.orders.save(order)
        if claim.envelope is None or claim.topic is None:
            log.info(
                "first park recorded; no triggering envelope to dead-letter",
                extra={"rowId": str(row.id), "command": row.kind.value},
            )
            return
        try:
            await self._dead_letters.publish(
                DeadLetter(
                    source_topic=claim.topic,
                    key=str(row.order_id).encode("utf-8"),
                    value=claim.envelope,
                    consumer=CONSUMER,
                    attempts=total_attempts,
                    error=last_error,
                    # Set whenever an envelope is (see `FirstParkClaim`): `park` writes it in the
                    # statement that parks the row. `now` is the unreachable fallback.
                    first_failed_at=claim.first_failed_at or now,
                    failed_at=now,
                    event_type=_event_type_of(claim.envelope),
                )
            )
        except Exception:
            log.exception(
                "first-park dead letter not published; the envelope stays in the row",
                extra={"rowId": str(row.id), "command": row.kind.value, "topic": claim.topic},
            )


def _event_type_of(envelope: bytes) -> str:
    try:
        return from_wire_json(Envelope[dict[str, object]], envelope).event_type
    except ValueError:
        return UNKNOWN_EVENT_TYPE
