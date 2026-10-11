"""H1 (PR8, PR22, PR39, PR52): the two indexes against a real server.

* PR22: created idempotently; a same-name index with different options fails the boot naming the
  index, the code the SERVER raised (read from the exception, never a literal) and the `dropIndex`
  one-liner.
* PR39: the seed's creation then the projector's, and the reverse, raise nothing (two-party claim:
  BOTH creation orders).
* PR52: a differently-named unique index on `orderReference` fails the boot, naming it; and the
  stored specification of each expected index is compared in key, uniqueness and partial filter
  (`{$type: 2}` is accepted by the server's create as equivalent of `{$type: "string"}` and only the
  comparison catches it).
* PR22 on code 85: an identical index under another name is refused with the OTHER name; the
  message names that index, not the expected one.
* PR8: two placeholders (`orderReference: null`) coexist under the real partial index.
"""

import dataclasses
import uuid
from typing import Any

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import OperationFailure

from otc_projector.infrastructure.persistence.read_model_document import COLLECTION
from otc_projector.infrastructure.persistence.read_model_indexes import (
    EXPECTED_INDEXES,
    ReadModelIndexError,
    ensure_indexes,
    verify_indexes,
)
from otc_seed.application.dataset import default_dataset
from otc_seed.infrastructure.mongo import MongoTimelineTarget

pytestmark = pytest.mark.integration


async def stored(collection: Any) -> dict[str, dict[str, Any]]:
    return {spec["name"]: dict(spec) async for spec in await collection.list_indexes()}


async def test_pr22_creates_both_indexes_idempotently(read_model: Any) -> None:
    collection = read_model.collection
    await ensure_indexes(collection)
    await ensure_indexes(collection)  # a second run raises nothing
    await verify_indexes(collection)
    specs = await stored(collection)
    for expected in EXPECTED_INDEXES:
        found = specs[expected.name]
        assert tuple(found["key"].items()) == expected.key, expected.name
        assert bool(found.get("unique", False)) is expected.unique, expected.name
        assert found.get("partialFilterExpression") == expected.partial_filter, expected.name
    assert set(specs) == {"_id_", "uq_order_reference", "ix_status_updatedAt"}


async def test_pr22_a_plain_unique_index_of_the_same_name_fails_the_boot_naming_the_index_and_the_raised_code(  # noqa: E501
    read_model: Any,
) -> None:
    collection = read_model.client.get_database(read_model.database).get_collection("conflict_box")
    await collection.create_index([("orderReference", 1)], unique=True, name="uq_order_reference")
    # the code the server raises for the projector's creation, read from the exception itself
    with pytest.raises(OperationFailure) as raised:
        await collection.create_index(
            [("orderReference", 1)],
            unique=True,
            name="uq_order_reference",
            partialFilterExpression={"orderReference": {"$type": "string"}},
        )
    server_code = raised.value.code
    print(f"the server raised code {server_code} ({(raised.value.details or {}).get('codeName')})")
    assert server_code in (85, 86), f"the server raised an unexpected code {server_code}"
    with pytest.raises(ReadModelIndexError) as refused:
        await ensure_indexes(collection)
    message = str(refused.value)
    assert "uq_order_reference" in message, "the index is not named"
    assert "dropIndex" in message, "the dropIndex one-liner is missing"
    assert f"code {server_code}" in message, (
        f"the message does not carry the code the server raised ({server_code}): {message}"
    )


async def test_pr39_the_seeds_index_then_the_projectors_and_the_reverse_raise_nothing(
    read_model: Any,
) -> None:
    empty = dataclasses.replace(default_dataset(), sagas=())
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(read_model.uri)
    first, second = (f"{read_model.database}_{tag}_{uuid.uuid4().hex[:6]}" for tag in ("a", "b"))
    try:
        # seed first, projector second
        await MongoTimelineTarget(client, first).seed(empty)
        collection = client.get_database(first).get_collection(COLLECTION)
        await ensure_indexes(collection)
        await verify_indexes(collection)
        # projector first, seed second
        collection = client.get_database(second).get_collection(COLLECTION)
        await ensure_indexes(collection)
        await MongoTimelineTarget(client, second).seed(empty)
        await verify_indexes(collection)
        for database in (first, second):
            specs = await stored(client.get_database(database).get_collection(COLLECTION))
            assert specs["uq_order_reference"]["partialFilterExpression"] == {
                "orderReference": {"$type": "string"}
            }, database
    finally:
        await client.drop_database(first)
        await client.drop_database(second)
        await client.close()


async def test_pr52_a_differently_named_unique_index_on_order_reference_fails_the_boot(
    read_model: Any,
) -> None:
    collection = read_model.client.get_database(read_model.database).get_collection("rogue_box")
    await collection.create_index([("orderReference", 1)], unique=True, name="uq_rogue_reference")
    await ensure_indexes(collection)  # no conflict: the names differ
    with pytest.raises(ReadModelIndexError) as refused:
        await verify_indexes(collection)
    message = str(refused.value)
    assert "uq_rogue_reference" in message, "the offending index is not named"
    assert "dropIndex" in message


async def test_pr8_two_placeholders_with_null_order_reference_coexist(
    read_model: Any, facts: Any
) -> None:
    first = facts.build("order.confirmed.v1", correlation_id=uuid.UUID(int=0xA1))
    second = facts.build("order.despatched.v1", correlation_id=uuid.UUID(int=0xA2))
    await read_model.apply(first)
    await read_model.apply(second)
    for event in (first, second):
        document = await read_model.document(event.correlation_id)
        assert document["orderReference"] is None
        assert document["headerComplete"] is False
    assert await read_model.collection.count_documents({"orderReference": None}) == 2


async def test_pr52_the_stored_partial_filter_is_compared_with_the_expected_definition(
    read_model: Any,
) -> None:
    """The comparison half of PR52 (acceptance 3: "checked against the server's stored
    specification"). The numeric alias `{$type: 2}` (what #8's seed once wrote) is accepted by the
    server as equivalent to `{$type: "string"}`, so `ensure_indexes` raises nothing and ONLY
    `verify_indexes` can fail the boot."""
    collection = read_model.client.get_database(read_model.database).get_collection("alias_box")
    await collection.create_index(
        [("orderReference", 1)],
        unique=True,
        name="uq_order_reference",
        partialFilterExpression={"orderReference": {"$type": 2}},
    )
    await ensure_indexes(collection)  # the server treats the alias as the same index: no conflict
    with pytest.raises(ReadModelIndexError) as refused:
        await verify_indexes(collection)
    message = str(refused.value)
    assert "uq_order_reference" in message, "the index is not named"
    assert "partialFilterExpression" in message, "the differing property is not named"
    assert 'dropIndex("uq_order_reference")' in message, "the dropIndex one-liner is missing"


async def test_pr52_a_stored_non_unique_index_of_the_expected_name_fails_the_verification(
    read_model: Any,
) -> None:
    """The comparison half of PR52 for `unique`, through a fake collection: the server refuses to
    create the sibling (code 86), so the stored specification is served by hand."""

    class StoredSpecifications:
        name = "fake_box"

        async def list_indexes(self) -> Any:
            specifications = [
                {"name": "_id_", "key": {"_id": 1}},
                {
                    "name": "uq_order_reference",
                    "key": {"orderReference": 1},
                    "partialFilterExpression": {"orderReference": {"$type": "string"}},
                },
                {"name": "ix_status_updatedAt", "key": {"status": 1, "updatedAt": -1}},
            ]

            async def generate() -> Any:
                for specification in specifications:
                    yield specification

            return generate()

    with pytest.raises(ReadModelIndexError) as refused:
        await verify_indexes(StoredSpecifications())  # type: ignore[arg-type]
    message = str(refused.value)
    assert "uq_order_reference" in message
    assert "unique False != True" in message, "the uniqueness difference is not reported"


async def test_pr22_an_identical_index_under_another_name_fails_the_boot_naming_the_server_named_index(  # noqa: E501
    read_model: Any,
) -> None:
    collection = read_model.client.get_database(read_model.database).get_collection("renamed_box")
    await collection.create_index(
        [("orderReference", 1)],
        unique=True,
        name="uq_other",
        partialFilterExpression={"orderReference": {"$type": "string"}},
    )
    with pytest.raises(ReadModelIndexError) as refused:
        await ensure_indexes(collection)
    message = str(refused.value)
    assert "code 85" in message, f"the server's code is not carried: {message}"
    assert 'dropIndex("uq_other")' in message, (
        f"the one-liner does not drop the index the server named: {message}"
    )
    assert 'dropIndex("uq_order_reference")' not in message, (
        f"the one-liner names an index that does not exist on the collection: {message}"
    )
