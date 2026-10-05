"""The MongoDB target: the `order_timeline` read model, the first MongoDB writer of the project.

Idempotence mechanism: `update_one({"_id": orderId}, {"$setOnInsert": document}, upsert=True)`. A
document that already exists is left exactly as it is (the projector owns it once live events
arrive), so a second run changes nothing and reports zero added. `_id` is the order id.

The unique index on `orderReference` is PARTIAL (`partialFilterExpression: {orderReference:
{$type: "string"}}`): the projector's placeholder documents carry `orderReference: null`, and
MongoDB indexes and compares nulls equal, so a plain unique index would reject the second
placeholder with E11000. The seeded documents always carry a string and are all covered.
"""

from collections.abc import Mapping
from typing import Any

from pymongo import AsyncMongoClient

from otc_seed.application.dataset import SeedDataset
from otc_seed.domain.timeline import ORDER_TIMELINE_COLLECTION, to_timeline_document

ORDER_REFERENCE_INDEX = "uq_order_reference"


class MongoTimelineTarget:
    name = "mongo"

    def __init__(self, client: AsyncMongoClient[dict[str, Any]], database: str) -> None:
        self._client = client
        self._database = database

    async def verify(self) -> None:
        # A real round trip: an unreachable or unauthenticated server fails here, before any write.
        await self._client.get_database(self._database).command("ping")

    async def seed(self, dataset: SeedDataset) -> Mapping[str, int]:
        collection = self._client.get_database(self._database).get_collection(
            ORDER_TIMELINE_COLLECTION
        )
        await collection.create_index(
            [("orderReference", 1)],
            unique=True,
            name=ORDER_REFERENCE_INDEX,
            partialFilterExpression={"orderReference": {"$type": "string"}},
        )
        added = 0
        for saga in dataset.sagas:
            document = to_timeline_document(saga)
            result = await collection.update_one(
                {"_id": document["_id"]}, {"$setOnInsert": document}, upsert=True
            )
            if result.upserted_id is not None:
                added += 1
        return {ORDER_TIMELINE_COLLECTION: added}
