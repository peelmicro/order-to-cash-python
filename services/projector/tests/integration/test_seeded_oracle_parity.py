"""J7 (PR44, PR34): the projector against an ORACLE it did not write.

For each of the six seeded sagas, the saga's OWN outbox facts are projected through the real writer
into an empty collection, the same saga is stored by the REAL seed (`MongoTimelineTarget.seed`) into
another, and the two stored documents are compared field by field: element SEQUENCE and BSON TYPE as
well as value (a value comparison alone passes a document whose keys are in the wrong order or whose
integer is the wrong width). The seeded documents are the oracle because they are #7's documents
(the seed is pinned to #7's output by its own tests) and the seed writes them with the same driver.

The comparison excludes exactly four paths, a declared literal, and a separate assertion proves the
comparison skipped exactly those and no others: master data the facts do not carry (`retailer.name`,
`company.name`, `items[].name`, PR9) and `events[].detail`, the seed's hand-written SUBSET (the
projector's `PR16` builders are its oracle; the seed's `stock.released.v1` entry has none at all).

Blind spot, stated: no seeded saga has a tie group (every fact sits at its own instant), so the
causal order is proven by `test_timeline_causal_order.py`, not here.
"""

import dataclasses
import uuid
from typing import Any

import bson
import pytest
from bson.codec_options import CodecOptions
from bson.raw_bson import RawBSONDocument
from pymongo import AsyncMongoClient

from otc_projector.infrastructure.persistence.read_model_document import COLLECTION
from otc_seed.application.dataset import default_dataset
from otc_seed.domain.data.sagas import SAGAS
from otc_seed.infrastructure.mongo import MongoTimelineTarget

pytestmark = pytest.mark.integration

EXCLUDED = frozenset({"retailer.name", "company.name", "items[].name", "events[].detail"})


def kept_keys(
    path: str, document: dict[str, Any], excluded: frozenset[str], skipped: set[str]
) -> list[str]:
    """The element sequence of `document` without the excluded paths (which are recorded)."""
    kept: list[str] = []
    for key in document:
        if f"{path}.{key}" in excluded:
            skipped.add(f"{path}.{key}")
        else:
            kept.append(key)
    return kept


def compare(
    path: str, mine: Any, theirs: Any, excluded: frozenset[str], skipped: set[str]
) -> list[str]:
    """Differences in value, BSON type and element sequence; `skipped` collects the excluded paths
    actually met (so a test can assert the exclusion set is what it claims)."""
    if isinstance(mine, dict) and isinstance(theirs, dict):
        kept_mine = kept_keys(path, mine, excluded, skipped)
        kept_theirs = kept_keys(path, theirs, excluded, skipped)
        problems = []
        if kept_mine != kept_theirs:
            problems.append(f"{path or '<root>'}: element sequence {kept_mine} != {kept_theirs}")
        for key in kept_mine:
            if key in theirs:
                child = f"{path}.{key}" if path else key
                problems += compare(child, mine[key], theirs[key], excluded, skipped)
        return problems
    if isinstance(mine, list) and isinstance(theirs, list):
        if len(mine) != len(theirs):
            return [f"{path}: length {len(mine)} != {len(theirs)}"]
        problems = []
        for index, (a, b) in enumerate(zip(mine, theirs, strict=True)):
            problems += [
                p.replace(f"{path}[]", f"{path}[{index}]", 1)
                for p in compare(f"{path}[]", a, b, excluded, skipped)
            ]
        return problems
    if type(mine) is not type(theirs):
        mine_type, theirs_type = type(mine).__name__, type(theirs).__name__
        return [f"{path}: type {mine_type} != {theirs_type} ({mine!r} / {theirs!r})"]
    if mine != theirs:
        return [f"{path}: value {mine!r} != {theirs!r}"]
    return []


async def seeded_document(uri: str, database: str, saga_index: int) -> dict[str, Any]:
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(uri)
    try:
        dataset = dataclasses.replace(default_dataset(), sagas=(SAGAS[saga_index],))
        await MongoTimelineTarget(client, database).seed(dataset)
        raw_collection = client.get_database(database).get_collection(
            COLLECTION, codec_options=CodecOptions(document_class=RawBSONDocument)
        )
        found = await raw_collection.find_one({"_id": SAGAS[saga_index].order_id})
        assert isinstance(found, RawBSONDocument)
        decoded: dict[str, Any] = bson.decode(bytes(found.raw))
        return decoded
    finally:
        await client.drop_database(database)
        await client.close()


@pytest.mark.parametrize("saga_index", range(6))
async def test_pr44_projecting_each_seeded_sagas_facts_reproduces_the_seeds_stored_document_except_the_declared_set(  # noqa: E501
    read_model: Any, saga_facts: Any, saga_index: int
) -> None:
    saga = SAGAS[saga_index]
    for event in saga_facts(saga):
        await read_model.apply(event)
    projected: dict[str, Any] = bson.decode(await read_model.raw(saga.order_id))
    seeded = await seeded_document(
        read_model.uri, f"{read_model.database}_oracle_{uuid.uuid4().hex[:6]}", saga_index
    )
    skipped: set[str] = set()
    differences = compare("", projected, seeded, EXCLUDED, skipped)
    assert differences == [], f"saga {saga_index} ({saga.order_reference}): {differences[:5]}"
    assert skipped <= EXCLUDED, (
        f"the comparison skipped undeclared paths {sorted(skipped - EXCLUDED)}"
    )
    assert projected["headerComplete"] is True
    assert projected["status"] == saga.status
    assert len(projected["events"]) == len(saga.timeline)


def test_pr44_the_exclusion_is_exactly_the_four_declared_paths() -> None:
    assert {"retailer.name", "company.name", "items[].name", "events[].detail"} == EXCLUDED
    assert len(EXCLUDED) == 4


async def test_pr44_over_the_six_sagas_the_comparison_skipped_exactly_the_declared_paths(
    read_model: Any, saga_facts: Any
) -> None:
    """The exclusion is a declared literal AND an observed fact: across the six sagas the walk met
    each of the four paths and skipped no other (the five completed sagas carry no `detail` on
    either side, the cancelled one does)."""
    skipped: set[str] = set()
    for index, saga in enumerate(SAGAS):
        await read_model.collection.delete_many({})
        for event in saga_facts(saga):
            await read_model.apply(event)
        projected: dict[str, Any] = bson.decode(await read_model.raw(saga.order_id))
        seeded = await seeded_document(
            read_model.uri, f"{read_model.database}_union_{uuid.uuid4().hex[:6]}", index
        )
        assert compare("", projected, seeded, EXCLUDED, skipped) == [], f"saga {index}"
    assert skipped == set(EXCLUDED), (
        f"the comparison skipped {sorted(skipped)}, not exactly {sorted(EXCLUDED)}"
    )
