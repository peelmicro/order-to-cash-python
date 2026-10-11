"""VARIANT OF services/orders/src/otc_orders/infrastructure/messaging/idempotent_consumer.py (R17, R18).

Divergence: the ledger is not a `processed_events` row inside a PostgreSQL transaction; it is the
`processedEventKeys` array of the read-model document itself, written by the SAME single
`find_one_and_update` that applies the projection. There is no transaction to share (the standalone
MongoDB has none, and one document is strictly better): the mark and the effect are the same bytes
in the same write (design.md 6.3).

Behavioural conformance: services/projector/tests/integration/test_idempotent_consumer_conformance.py
"""  # noqa: E501 - the two paths are the banner the parity guard matches; they cannot wrap

import enum
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import UUID

from pymongo import ReturnDocument
from pymongo.asynchronous.collection import AsyncCollection

from .consumer_name import ConsumerName


class ConsumptionOutcome(enum.Enum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"


class IdempotentConsumer:
    """The filter IS the idempotency check; the work is a post-apply callback.

    `find_one_and_update({_id: scope_id, processedEventKeys: {$ne: key}}, stages(key))`: a document
    that already holds the key does not match, nothing is written and `None` comes back
    (`DUPLICATE`). Otherwise the pipeline applies the whole effect and records the key in one
    write, and the POST-apply document comes back (`PROCESSED`). `return_document=AFTER` is not
    the driver's default (`BEFORE`), and a deletion probe cannot see that default: only a test of
    what the callback receives can.

    The document `scope_id` must already exist (the writer's first operation creates it): an absent
    document matches nothing and would read as a duplicate. `stages` is a parameter, not a return
    value of the work, because the work (here: the signal) must run AFTER the write and never on a
    duplicate. The only attribute is the collection handle: no deduplication state lives in the
    process (PR51).
    """

    def __init__(self, collection: AsyncCollection[dict[str, Any]]) -> None:
        self._collection = collection

    async def run_once(
        self,
        *,
        scope_id: str,
        event_id: UUID,
        consumer: ConsumerName,
        stages: Callable[[str], list[dict[str, object]]],
        after_applied: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> ConsumptionOutcome:
        key = f"{consumer.value}:{event_id}"
        applied = await self._collection.find_one_and_update(
            {"_id": scope_id, "processedEventKeys": {"$ne": key}},
            stages(key),
            return_document=ReturnDocument.AFTER,
        )
        if applied is None:
            return ConsumptionOutcome.DUPLICATE
        await after_applied(applied)
        return ConsumptionOutcome.PROCESSED
