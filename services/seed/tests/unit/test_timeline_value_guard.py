"""The `order_timeline` documents' VALUES, against #7's own `toTimelineDocument` output.

R-map (feature_list.json id 12, acceptance 3: "headerComplete, statusRank, processedEventKeys
values tested"; #8 review D1): every seeded document is compared with the checked-in oracle field
by field, so a blank `causationId`, a total off by one cent, a dropped dedup key, a wrong party GLN
or a wrong instant fails by name. #8 was rejected once because these values were guarded only for
presence.

Defeat list, as it applies here (armed in progress/impl_seed_job.md): delete the behaviour (blank
every `causationId`); corrupt a supplied field (a total, `headerComplete`); drop an optional element
(`detail`, one `processedEventKeys` entry); reorder (two events); compare a literal to a literal
(avoided: the expected side is the oracle file, and the literal spot checks below are typed
separately from it); fixtures must not satisfy the relation by accident (every id and instant in
the oracle is distinct, so a cross-field mix-up cannot compare equal).
"""

from typing import Any

import pytest

from otc_seed.domain.data.sagas import SAGAS
from otc_seed.domain.timeline import (
    ORDER_TIMELINE_COLLECTION,
    STATUS_RANK,
    TIMELINE_ORDER_VERSION,
    to_timeline_document,
)


def test_every_seeded_document_equals_number7s_field_by_field(
    number7_timeline: list[dict[str, Any]], assert_timeline_matches_oracle: Any
) -> None:
    assert_timeline_matches_oracle([to_timeline_document(s) for s in SAGAS], number7_timeline)


def test_the_oracle_is_the_population_it_claims_to_be(
    number7_timeline: list[dict[str, Any]],
) -> None:
    """Sentinel for the guard itself: six documents, 9 + 9 + 9 + 9 + 9 + 5 = 50 events, 50 dedup
    keys, and the cancelled one carries the two `detail` objects. A comparison over an empty or
    truncated oracle would pass vacuously."""
    assert len(number7_timeline) == 6
    assert sum(len(d["events"]) for d in number7_timeline) == 50
    assert sum(len(d["processedEventKeys"]) for d in number7_timeline) == 50
    assert sum(1 for d in number7_timeline for e in d["events"] if "detail" in e) == 2
    assert all(e["causationId"] for d in number7_timeline for e in d["events"])


def test_literal_spot_checks_typed_independently_of_the_oracle_file() -> None:
    """Values from #8's review (round 2) and #7's saga arithmetic, typed here by hand."""
    first = to_timeline_document(SAGAS[0])
    assert first["_id"] == first["orderId"] == "1741d5aa-cfba-4205-a1c0-82e7a5cb8984"
    assert first["totals"] == {"initialAmount": 16130, "initialDiscount": 0, "totalAmount": 16130}
    assert first["items"][0] == {
        "productCode": "PRD-0002",
        "name": "Pasta 500g Case (24u)",
        "quantity": 5,
        "unitPrice": 1849,
        "lineDiscount": 0,
    }
    assert first["retailer"]["name"] == "Carrefour España"
    assert first["company"]["gln"] == "5400000000218"
    assert first["events"][2]["summary"] == "Credit hold of 161.30 EUR approved"
    # the chain: stock.reserved cites order.placed; the root cites a synthetic command id
    assert first["events"][1]["causationId"] == first["events"][0]["eventId"]
    assert first["events"][0]["causationId"] == "0914f64b-f91e-4af3-927c-f9227fb92077"
    assert first["updatedAt"] == "2026-06-02T09:00:10.000Z"
    cancelled = to_timeline_document(SAGAS[5])
    assert cancelled["status"] == "cancelled"
    assert cancelled["statusRank"] == 99
    assert cancelled["references"] == {
        "despatchReference": None,
        "invoiceReference": None,
        "paymentReference": None,
    }
    assert cancelled["events"][2]["detail"] == {
        "reason": "simulated_cents_rule",
        "requestedAmount": 24999,
    }
    assert cancelled["events"][2]["summary"] == (
        "Credit hold of 249.99 EUR rejected (simulated_cents_rule)"
    )


def test_projector_owned_fields_are_written_at_the_current_values() -> None:
    for saga in SAGAS:
        document = to_timeline_document(saga)
        assert document["headerComplete"] is True
        assert document["timelineOrderVersion"] == TIMELINE_ORDER_VERSION == 2
        assert document["statusRank"] == STATUS_RANK[saga.status]
        keys = document["processedEventKeys"]
        assert keys == sorted(keys)
        assert keys == sorted(f"projector:{e['eventId']}" for e in document["events"])
        assert [e["occurredAt"] for e in document["events"]] == sorted(
            e["occurredAt"] for e in document["events"]
        )
    assert STATUS_RANK["completed"] == 98
    assert STATUS_RANK["cancelled"] == 99


def test_the_collection_name_is_the_documented_one() -> None:
    assert ORDER_TIMELINE_COLLECTION == "order_timeline"


@pytest.mark.parametrize("path", ["totals", "events", "processedEventKeys", "retailer"])
def test_the_guard_itself_fails_when_a_value_differs(
    number7_timeline: list[dict[str, Any]], assert_timeline_matches_oracle: Any, path: str
) -> None:
    """The comparison is armed in the suite too: a corrupted copy of one document must fail it,
    and the failure must name the path. (The arming table in the report corrupts the PRODUCTION
    code.)"""
    documents = [to_timeline_document(s) for s in SAGAS]
    target = documents[2]
    if path == "totals":
        target["totals"]["totalAmount"] += 1
    elif path == "events":
        target["events"][4]["causationId"] = ""
    elif path == "processedEventKeys":
        target["processedEventKeys"].pop()
    else:
        target["retailer"]["gln"] = target["company"]["gln"]
    with pytest.raises(AssertionError, match=r"ORD-000003 \."):
        assert_timeline_matches_oracle(documents, number7_timeline)
