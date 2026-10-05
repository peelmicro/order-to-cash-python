"""The seed against a real MongoDB: the `order_timeline` documents, read back from the server.

R-map (feature_list.json id 12): acceptance 3 (the six documents, with `headerComplete`,
`statusRank` and `processedEventKeys` VALUES tested: every leaf of every document read back from
MongoDB equals #7's `toTimelineDocument` output, with its exact BSON type) and acceptance 4
(idempotent for MongoDB too: a second run adds nothing and changes no document).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pymongo import AsyncMongoClient

from otc_seed.application import run_seed
from otc_seed.composition import SeedRuntime
from otc_seed.infrastructure.mongo import ORDER_REFERENCE_INDEX, MongoTimelineTarget

pytestmark = pytest.mark.integration

CONSTANTS_FILE = (
    Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "read_model_constants.json"
)


async def _documents(stack: Any) -> list[dict[str, Any]]:
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(stack.mongo.uri)
    try:
        collection = client.get_database(stack.mongo.name).get_collection("order_timeline")
        return [d async for d in collection.find({}).sort("orderReference", 1)]
    finally:
        await client.close()


async def test_the_documents_read_back_from_mongodb_equal_number7s_value_for_value(
    runtime: SeedRuntime,
    stack: Any,
    number7_timeline: list[dict[str, Any]],
    assert_timeline_matches_oracle: Any,
) -> None:
    await run_seed(runtime.targets)
    documents = await _documents(stack)
    assert len(documents) == 6
    assert_timeline_matches_oracle(documents, number7_timeline)


async def test_the_partial_unique_index_on_order_reference_exists_and_admits_placeholders(
    runtime: SeedRuntime, stack: Any
) -> None:
    await run_seed(runtime.targets)
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(stack.mongo.uri)
    try:
        collection = client.get_database(stack.mongo.name).get_collection("order_timeline")
        indexes = {i["name"]: i async for i in await collection.list_indexes()}
        index = indexes[ORDER_REFERENCE_INDEX]
        # the index options come from the shared fixture the projector is pinned to (backlog 212)
        expected = json.loads(CONSTANTS_FILE.read_text(encoding="utf-8"))["orderReferenceIndex"]
        assert index["unique"] is expected["unique"]
        assert index["key"] == expected["key"]
        assert index["partialFilterExpression"] == expected["partialFilterExpression"]
        # the projector's placeholders carry orderReference: null; a plain unique index would
        # reject the second one with E11000
        await collection.insert_one({"_id": "placeholder-1", "orderReference": None})
        await collection.insert_one({"_id": "placeholder-2", "orderReference": None})
    finally:
        await client.close()


async def test_running_the_seed_twice_changes_no_document(runtime: SeedRuntime, stack: Any) -> None:
    await run_seed(runtime.targets)
    first = await _documents(stack)
    report = await run_seed(runtime.targets)
    assert dict(report.added["mongo"]) == {"order_timeline": 0}
    assert await _documents(stack) == first


async def test_a_document_the_projector_already_advanced_is_left_alone(
    runtime: SeedRuntime, stack: Any
) -> None:
    await run_seed(runtime.targets)
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(stack.mongo.uri)
    try:
        collection = client.get_database(stack.mongo.name).get_collection("order_timeline")
        await collection.update_one({"orderReference": "ORD-000001"}, {"$set": {"statusRank": 5}})
    finally:
        await client.close()
    await run_seed(runtime.targets)
    documents = await _documents(stack)
    assert next(d for d in documents if d["orderReference"] == "ORD-000001")["statusRank"] == 5


async def test_an_unreachable_or_unauthenticated_server_fails_verification_before_any_write(
    stack: Any, mongo_server: Any
) -> None:
    bad_uri = f"mongodb://nobody:wrong@{mongo_server.host}:{mongo_server.port}/?authSource=admin"
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
        bad_uri, serverSelectionTimeoutMS=3000
    )
    try:
        with pytest.raises(Exception, match="Authentication failed"):
            await MongoTimelineTarget(client, stack.mongo.name).verify()
    finally:
        await client.close()
