"""E3, E7, E8 (PR6, PR33, PR41, PR47): the write against a real `mongo:8.3.8`.

* PR6: one fact is applied in exactly one `update` and one `findAndModify`, and the driver issues no
  read, on the first delivery AND on the redelivery.
* PR41: the stored element names, their order and their BSON types equal the seed's.
* PR47: text beginning with `$` is stored verbatim.

Test modules cannot import this directory's `conftest.py` (importlib mode), so the fixtures
(`read_model`, `saga_facts`) are typed `Any` here.
"""

import dataclasses
import uuid
from typing import Any

import bson
import pytest
from bson.codec_options import CodecOptions
from bson.int64 import Int64
from bson.raw_bson import RawBSONDocument
from pymongo import AsyncMongoClient

from otc_projector.application.outcome import ProjectionOutcome
from otc_projector.infrastructure.persistence.read_model_document import COLLECTION
from otc_seed.application.dataset import default_dataset
from otc_seed.domain.data.sagas import SAGAS
from otc_seed.infrastructure.mongo import MongoTimelineTarget

pytestmark = pytest.mark.integration


async def test_pr6_applies_one_fact_in_exactly_one_update_and_one_find_and_modify_issuing_no_read(
    read_model: Any, facts: Any
) -> None:
    event = facts.build("order.placed.v1")
    read_model.log.clear()
    first = await read_model.apply(event)
    first_commands = read_model.log.against(COLLECTION)
    read_model.log.clear()
    redelivery = await read_model.apply(event)
    second_commands = read_model.log.against(COLLECTION)
    assert first.outcome is ProjectionOutcome.PROCESSED
    assert redelivery.outcome is ProjectionOutcome.DUPLICATE
    assert first_commands == ["update", "findAndModify"], (
        f"the first delivery issued {first_commands}"
    )
    assert second_commands == ["update", "findAndModify"], (
        f"the redelivery issued {second_commands}"
    )


# ------------------------------------------------------------------------------- E7 / PR41, PR33


def elements(raw: bytes) -> dict[str, Any]:
    """The BSON document decoded WITH order: a dict keeps the element sequence."""
    decoded: dict[str, Any] = bson.decode(raw)
    return decoded


async def seeded_raw(read_model: Any, saga_index: int) -> bytes:
    """The document the REAL seed stores for a saga, in a second database on the same server."""
    database = f"{read_model.database}_seed_{uuid.uuid4().hex[:8]}"
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(read_model.uri)
    try:
        dataset = dataclasses.replace(default_dataset(), sagas=(SAGAS[saga_index],))
        await MongoTimelineTarget(client, database).seed(dataset)
        raw_collection = client.get_database(database).get_collection(
            COLLECTION, codec_options=CodecOptions(document_class=RawBSONDocument)
        )
        found = await raw_collection.find_one({"_id": SAGAS[saga_index].order_id})
        assert isinstance(found, RawBSONDocument)
        return bytes(found.raw)
    finally:
        await client.drop_database(database)
        await client.close()


@pytest.mark.parametrize("saga_index", [0, 5])
async def test_pr41_element_names_order_and_bson_types_equal_the_seeds_document(
    read_model: Any, saga_facts: Any, saga_index: int
) -> None:
    saga = SAGAS[saga_index]
    for event in saga_facts(saga):
        await read_model.apply(event)
    projected = elements(await read_model.raw(saga.order_id))
    seeded = elements(await seeded_raw(read_model, saga_index))
    assert list(projected) == list(seeded), "top-level element sequence differs from the seed's"
    for name in ("retailer", "company", "totals", "references"):
        assert list(projected[name]) == list(seeded[name]), f"{name}: element sequence differs"
    assert list(projected["items"][0]) == list(seeded["items"][0]), "item element sequence differs"
    assert len(projected["events"]) == len(seeded["events"])
    for index, (mine, theirs) in enumerate(zip(projected["events"], seeded["events"], strict=True)):
        # `detail` is excluded exactly as PR44 excludes it: the seed's is a hand-written subset (its
        # `stock.released.v1` entry has none at all), the projector's is PR16's builder.
        mine_keys = [key for key in mine if key != "detail"]
        theirs_keys = [key for key in theirs if key != "detail"]
        assert mine_keys == theirs_keys, f"events[{index}]: element sequence differs"


async def test_pr41_a_total_past_2_to_the_31_is_int64_and_a_small_one_is_int32(
    read_model: Any, facts: Any
) -> None:
    event = facts.build(
        "order.placed.v1",
        payload={"initial_amount": 9245, "initial_discount": 2**31 - 1, "total_amount": 2**31},
    )
    await read_model.apply(event)
    document = elements(await read_model.raw(event.correlation_id))
    assert type(document["totals"]["initialAmount"]) is int, "9245 is not stored as Int32"
    assert type(document["totals"]["initialDiscount"]) is int, "2**31 - 1 is not stored as Int32"
    assert type(document["totals"]["totalAmount"]) is Int64, "2**31 is not stored as Int64"
    assert document["totals"]["totalAmount"] == 2**31


async def test_pr33_the_stored_entry_carries_causation_id_and_the_document_the_three_internal_fields(  # noqa: E501
    read_model: Any, facts: Any
) -> None:
    event = facts.build("order.placed.v1")
    await read_model.apply(event)
    document = await read_model.document(event.correlation_id)
    (entry,) = document["events"]
    assert entry["causationId"] == str(event.causation_id)
    assert document["statusRank"] == 1
    assert document["timelineOrderVersion"] == 2
    assert document["processedEventKeys"] == [f"projector:{event.event_id}"]


# --------------------------------------------------------------------------------- E8 / PR47


async def test_pr47_dollar_prefixed_note_and_last_error_are_stored_verbatim(
    read_model: Any, facts: Any
) -> None:
    order = uuid.UUID("0a0b0c0d-1111-4000-8000-0000000000aa")
    cancelled = facts.build(
        "order.cancelled.v1",
        correlation_id=order,
        payload={"cancellation_reason": "operator_cancelled", "note": "$status"},
    )
    failed = facts.build(
        "order.saga_failed.v1", correlation_id=order, payload={"last_error": "$$NOW x"}
    )
    first = await read_model.apply(cancelled)
    second = await read_model.apply(failed)
    assert first.outcome is ProjectionOutcome.PROCESSED
    assert second.outcome is ProjectionOutcome.PROCESSED
    document = await read_model.document(order)
    by_type = {e["eventType"]: e for e in document["events"]}
    assert by_type["order.cancelled.v1"]["detail"]["note"] == "$status"
    assert by_type["order.saga_failed.v1"]["detail"]["lastError"] == "$$NOW x"
    assert document["status"] == "cancelled", "a `$status` note was evaluated as a field path"


async def test_pr47_a_dollar_status_note_is_stored_as_text_not_evaluated_as_the_documents_status(
    read_model: Any, facts: Any
) -> None:
    """Alone, so that the unwrapped failure is the SUBSTITUTION and not the poison record."""
    event = facts.build(
        "order.cancelled.v1",
        payload={"cancellation_reason": "operator_cancelled", "note": "$status"},
    )
    await read_model.apply(event)
    (entry,) = (await read_model.document(event.correlation_id))["events"]
    assert entry["detail"]["note"] == "$status", (
        f"the note was evaluated by the server: stored {entry['detail']['note']!r}"
    )
