"""Bring every document to the current timeline-order version before consuming (`PR32`, `PR35`).

* Selected by `{timelineOrderVersion: {$ne: <current>}}`, never by the presence or absence of a
  field: `$ne` matches a document that lacks the field, a presence test would not match one that
  carries an old number.
* `events` is re-sorted with the SAME expression the live apply uses (`timeline_order_expression`),
  the version is stamped, and no other client-visible field is touched (`updatedAt`, the status and
  the references stay as they are). A document already current is not selected, so it receives no
  write.
* It NEVER invents a `causationId` (`PR35`): an edge that was not recorded cannot be recovered. The
  boot log reports how many documents were migrated and how many of them still hold an entry with no
  `causationId`.
"""

import logging
from dataclasses import dataclass
from typing import Any

from pymongo.asynchronous.collection import AsyncCollection

from otc_projector.infrastructure.persistence.read_model_document import (
    TIMELINE_ORDER_VERSION,
    TIMELINE_ORDER_VERSION_FIELD,
)
from otc_projector.infrastructure.persistence.timeline_order import timeline_order_expression

log = logging.getLogger("otc_projector.persistence.timeline_order_migration")


@dataclass(frozen=True, slots=True)
class MigrationResult:
    migrated: int
    still_without_causation_id: int


async def migrate_timeline_order(collection: AsyncCollection[dict[str, Any]]) -> MigrationResult:
    stale: dict[str, Any] = {TIMELINE_ORDER_VERSION_FIELD: {"$ne": TIMELINE_ORDER_VERSION}}
    # `{causationId: None}` matches an entry whose field is null OR absent.
    without_edge = await collection.count_documents(
        {**stale, "events": {"$elemMatch": {"causationId": None}}}
    )
    result = await collection.update_many(
        stale,
        [
            {
                "$set": {
                    "events": timeline_order_expression({"$ifNull": ["$events", []]}),
                    TIMELINE_ORDER_VERSION_FIELD: {"$literal": TIMELINE_ORDER_VERSION},
                }
            }
        ],
    )
    migrated = result.modified_count
    log.info(
        "timeline-order migration: %d document(s) migrated to version %d, %d of them still hold "
        "an entry with no causationId",
        migrated,
        TIMELINE_ORDER_VERSION,
        without_edge,
        extra={"migrated": migrated, "stillWithoutCausationId": without_edge},
    )
    return MigrationResult(migrated=migrated, still_without_causation_id=without_edge)
