"""The seed's local copies of the projector-owned constants equal the shared fixture.

The fixture is `tests/fixtures/read_model_constants.json`.

R-map (backlog 212, seed half; feature_list.json id 12): the seed copies five facts of the
projector's read-model contract (the collection name, `timelineOrderVersion`, the status-rank
table, the `processedEventKeys` prefix and the order-reference index) and may not import the
projector (services never import each other). #7 kept them "in sync by inspection"; here they live
once, in the shared fixture, and feature 24 (`projector_read_model`) is pinned to the same file by
its own acceptance item. The seed's values are pinned to #7's oracle by `test_timeline_value_guard`;
this file ties them to the fixture, so a one-sided edit (seed only, or file only) fails by name.

Arms (recorded in `progress/impl_seed_job.md`, Round 3): `TIMELINE_ORDER_VERSION` changed in the
seed only; `"completed": 98` changed in the file only.
"""

import json
from pathlib import Path
from typing import Any

from otc_seed.domain.data.sagas import SAGAS
from otc_seed.domain.timeline import (
    ORDER_TIMELINE_COLLECTION,
    PROCESSED_EVENT_CONSUMER,
    STATUS_RANK,
    TIMELINE_ORDER_VERSION,
    to_timeline_document,
)
from otc_seed.infrastructure.mongo import ORDER_REFERENCE_INDEX

CONSTANTS_FILE = (
    Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "read_model_constants.json"
)


def _constants() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(CONSTANTS_FILE.read_text(encoding="utf-8"))
    return loaded


def test_the_fixture_is_the_file_it_claims_to_be() -> None:
    constants = _constants()
    assert set(constants) == {
        "collection",
        "timelineOrderVersion",
        "statusRank",
        "processedEventKeyPrefix",
        "orderReferenceIndex",
        "_note",
    }
    assert len(constants["statusRank"]) == 9


def test_the_seed_timeline_order_version_equals_the_fixture() -> None:
    assert _constants()["timelineOrderVersion"] == TIMELINE_ORDER_VERSION


def test_the_seed_status_rank_table_equals_the_fixture() -> None:
    assert _constants()["statusRank"] == STATUS_RANK


def test_the_seed_processed_event_key_prefix_equals_the_fixture() -> None:
    prefix = _constants()["processedEventKeyPrefix"]
    assert f"{PROCESSED_EVENT_CONSUMER}:" == prefix
    # and the keys the seed really writes carry it (the format, not just the constant)
    keys = [key for saga in SAGAS for key in to_timeline_document(saga)["processedEventKeys"]]
    assert len(keys) == 50
    assert all(key.startswith(prefix) for key in keys)


def test_the_seed_collection_and_index_name_equal_the_fixture() -> None:
    constants = _constants()
    assert constants["collection"] == ORDER_TIMELINE_COLLECTION
    assert constants["orderReferenceIndex"]["name"] == ORDER_REFERENCE_INDEX


def test_every_seeded_document_carries_the_fixture_version_and_rank() -> None:
    constants = _constants()
    for saga in SAGAS:
        document = to_timeline_document(saga)
        assert document["timelineOrderVersion"] == constants["timelineOrderVersion"]
        assert document["statusRank"] == constants["statusRank"][saga.status]
