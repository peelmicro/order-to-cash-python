"""D1 (PR8, ledger L12, L13): the placeholder is total over the seed's key set, with nested objects
of explicit-`null` leaves.

Totality is what keeps the element order right: the server stores the keys of a `$setOnInsert`
document lexicographically after `_id` (the seed's documents are stored the same way), and a later
pipeline `$set` of a key that does not exist would append it at the END. The expected key set and
the nested key order are READ from the real seed, never re-typed here.
"""

from typing import Any

from otc_projector.infrastructure.persistence.read_model_document import (
    TIMELINE_ORDER_VERSION,
    placeholder,
)
from otc_seed.domain.data.sagas import SAGAS
from otc_seed.domain.timeline import to_timeline_document

ORDER_ID = "0a0b0c0d-0000-4000-8000-0000000000aa"
INSTANT = "2031-02-03T04:05:06.789Z"


def seeded() -> dict[str, Any]:
    return to_timeline_document(SAGAS[0])


def test_pr8_the_placeholder_is_total_over_the_seeds_key_set_with_nested_null_leaves() -> None:
    document = placeholder(ORDER_ID, INSTANT)
    seed = seeded()
    assert set(document) == set(seed), (
        f"missing {sorted(set(seed) - set(document))}, extra {sorted(set(document) - set(seed))}"
    )
    for name in ("retailer", "company", "totals", "references"):
        nested = document[name]
        assert isinstance(nested, dict), f"{name} must be an object, not {nested!r}"
        assert list(nested) == list(seed[name]), f"{name}: nested key order differs from the seed's"
        assert all(leaf is None for leaf in nested.values()), f"{name}: a leaf is not null"
    assert document["status"] == "placed"
    assert document["statusRank"] == 0
    assert document["headerComplete"] is False
    assert document["updatedAt"] == INSTANT
    assert document["_id"] == document["orderId"] == ORDER_ID
    assert document["timelineOrderVersion"] == TIMELINE_ORDER_VERSION
    for scalar in ("orderReference", "orderDate", "cancellationReason", "currency"):
        assert document[scalar] is None, scalar
    for array in ("events", "items", "processedEventKeys"):
        assert document[array] == [], array
