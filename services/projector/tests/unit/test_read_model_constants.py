"""B2 / PR40: the projector's own constants equal `tests/fixtures/read_model_constants.json`, the
file the seed is pinned to (`services/seed/tests/unit/test_read_model_constants.py`).

Every expected value is READ FROM THE FIXTURE and every actual value from the projector's own
module; nothing is re-typed here (defeat row 8: a literal compared with a literal). Bumping the
projector's version alone, swapping two ranks, or weakening the partial filter fails by name.
"""

import json
from pathlib import Path
from typing import Any

from otc_projector.domain.status_rank import STATUS_RANK
from otc_projector.infrastructure.messaging.consumer_name import ConsumerName
from otc_projector.infrastructure.persistence.read_model_document import (
    COLLECTION,
    TIMELINE_ORDER_VERSION,
)
from otc_projector.infrastructure.persistence.read_model_indexes import (
    ORDER_REFERENCE_INDEX,
)

FIXTURE = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "read_model_constants.json"


def shared() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return loaded


def test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture() -> None:
    constants = shared()
    assert constants["timelineOrderVersion"] == TIMELINE_ORDER_VERSION, (
        "the projector's TIMELINE_ORDER_VERSION differs from the shared fixture's"
    )
    assert dict(STATUS_RANK) == constants["statusRank"], (
        "the projector's status -> rank table differs from the shared fixture's"
    )
    assert ConsumerName.PROJECTOR.value + ":" == constants["processedEventKeyPrefix"], (
        "the projector's dedup-key prefix differs from the shared fixture's"
    )
    assert constants["collection"] == COLLECTION, (
        "the projector's collection name differs from the shared fixture's"
    )
    expected_index = constants["orderReferenceIndex"]
    assert ORDER_REFERENCE_INDEX.name == expected_index["name"]
    assert dict(ORDER_REFERENCE_INDEX.key) == expected_index["key"]
    assert ORDER_REFERENCE_INDEX.unique == expected_index["unique"]
    assert ORDER_REFERENCE_INDEX.partial_filter == expected_index["partialFilterExpression"], (
        "the projector's uq_order_reference partial filter differs from the shared fixture's"
    )
