"""`MongoReadModelWriter`: the two operations that apply one fact (`PR6`, `PR7`, `PR42`).

1. **Bring the document into existence**:
   `update_one({_id}, {$setOnInsert: placeholder}, upsert=True)` (`upsert` is NOT the default of
   `update_one`), a no-op on an existing document. Its one race, two
   first facts for an absent order, could make one insert lose with `DuplicateKeyError` on `_id`:
   caught HERE ONLY and retried exactly ONCE (it can then only match); every other error propagates.
   Measured: on `mongo:8.3.8` the server retries a lost `_id` upsert itself (4,800 racing upserts, 0
   errors), so the retry is unreachable there and is kept as a conditional clause. Not
   delegated to `retryWrites`: the compose stack and the test container are standalone servers,
   where no driver retries.
2. **The atomic apply**, through the idempotent-consumer variant: one `find_one_and_update` whose
   filter is the idempotency check and whose pipeline is the whole projection of the fact. A
   `DuplicateKeyError` here is NOT retried: it would be a duplicate key on `uq_order_reference`, a
   poison record that is feature 27's to dead-letter, never something to retry blindly.

The writer never reads the document in order to decide what to write, and holds no state beyond its
two collaborators (`PR51`). The store's mapping is converted to the typed `AppliedDocument` here, so
no untyped document crosses the port (ledger L30).
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import DuplicateKeyError

from otc_contracts import format_instant
from otc_projector.application.outcome import ProjectionOutcome
from otc_projector.application.ports.read_model import AfterApplied, AppliedDocument, AppliedTotals
from otc_projector.domain.projection_delta import ProjectionDelta
from otc_projector.infrastructure.messaging.consumer_name import ConsumerName
from otc_projector.infrastructure.messaging.idempotent_consumer import (
    ConsumptionOutcome,
    IdempotentConsumer,
)
from otc_projector.infrastructure.persistence.delta_to_pipeline import delta_to_pipeline
from otc_projector.infrastructure.persistence.read_model_document import placeholder


def is_id_conflict(error: DuplicateKeyError) -> bool:
    """True when the duplicate key is on `_id`: the lost upsert race of two first facts."""
    key_pattern = (error.details or {}).get("keyPattern")
    return key_pattern == {"_id": 1} or "index: _id_" in str(error)


def _totals(document: Mapping[str, Any]) -> AppliedTotals | None:
    totals = document.get("totals") or {}
    initial_amount = totals.get("initialAmount")
    initial_discount = totals.get("initialDiscount")
    total_amount = totals.get("totalAmount")
    if initial_amount is None or initial_discount is None or total_amount is None:
        return None  # a placeholder: the header (and with it the totals) is not known yet
    return AppliedTotals(
        initial_amount=int(initial_amount),
        initial_discount=int(initial_discount),
        total_amount=int(total_amount),
    )


def to_applied_document(document: Mapping[str, Any]) -> AppliedDocument:
    references = document.get("references") or {}
    return AppliedDocument(
        order_id=str(document["_id"]),
        order_reference=document.get("orderReference"),
        status=str(document["status"]),
        cancellation_reason=document.get("cancellationReason"),
        despatch_reference=references.get("despatchReference"),
        invoice_reference=references.get("invoiceReference"),
        payment_reference=references.get("paymentReference"),
        totals=_totals(document),
    )


class MongoReadModelWriter:
    def __init__(
        self, collection: AsyncCollection[dict[str, Any]], consumer: IdempotentConsumer
    ) -> None:
        self._collection = collection
        self._consumer = consumer

    async def apply(
        self, delta: ProjectionDelta, *, after_applied: AfterApplied
    ) -> ProjectionOutcome:
        await self._ensure_document(delta)

        async def announce(document: Mapping[str, Any]) -> None:
            await after_applied(to_applied_document(document))

        outcome = await self._consumer.run_once(
            scope_id=delta.order_id,
            event_id=UUID(delta.entry.event_id),
            consumer=ConsumerName.PROJECTOR,
            stages=lambda key: delta_to_pipeline(delta, key),
            after_applied=announce,
        )
        if outcome is ConsumptionOutcome.PROCESSED:
            return ProjectionOutcome.PROCESSED
        return ProjectionOutcome.DUPLICATE

    async def _ensure_document(self, delta: ProjectionDelta) -> None:
        document = placeholder(delta.order_id, format_instant(delta.entry.occurred_at))
        try:
            await self._collection.update_one(
                {"_id": delta.order_id}, {"$setOnInsert": document}, upsert=True
            )
        except DuplicateKeyError as error:
            if not is_id_conflict(error):
                raise
            # The other writer created the document first: this can only match now. Once.
            await self._collection.update_one(
                {"_id": delta.order_id}, {"$setOnInsert": document}, upsert=True
            )
