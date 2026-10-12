"""The adapter's document parsing, without a server: what a stored document must look like, and
that a defect in one is loud rather than a wrong number on the wire.

(Against documents the REAL projector writes: `tests/integration/test_order_read_model.py`.)
"""

from dataclasses import fields
from typing import Any
from uuid import UUID

import pytest

from otc_gateway.infrastructure import mongo_order_read_model as adapter

ORDER_ID = "11111111-1111-4111-8111-111111111111"


def stored(**override: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "orderId": ORDER_ID,
        "orderReference": "ORD-000042",
        "orderDate": "2026-08-18T10:15:00.100Z",
        "retailer": {"code": "R", "name": None, "gln": "8412345000013"},
        "company": {"code": "C", "name": "Company", "gln": "8412345000020"},
        "status": "placed",
        "cancellationReason": None,
        "currency": "EUR",
        "totals": {"initialAmount": 124250, "initialDiscount": 5000, "totalAmount": 119250},
        "items": [],
        "references": {
            "despatchReference": None,
            "invoiceReference": None,
            "paymentReference": None,
        },
        "events": [],
        "headerComplete": True,
        "updatedAt": "2026-08-18T10:20:05.700Z",
        # the projector's internals: present in the stored document, modelled nowhere in the Gateway
        "statusRank": 1,
        "processedEventKeys": ["a:b"],
        "timelineOrderVersion": 2,
    }
    return document | override


def test_a_stored_document_becomes_an_order_and_the_internal_elements_have_nowhere_to_go() -> None:
    order = adapter.order_of(stored())

    assert order.header.order_id == UUID(ORDER_ID)
    assert order.header.totals.initial_amount == 124250
    assert order.header_complete is True
    names = {f.name for f in fields(order.header)} | {f.name for f in fields(order)}
    assert not [n for n in names if "rank" in n or "key" in n or "version" in n]
    assert not hasattr(order, "status_rank")


def test_the_inclusion_lists_name_no_internal_element_and_cover_every_modelled_one() -> None:
    assert not {"statusRank", "processedEventKeys", "timelineOrderVersion"} & set(
        adapter.DETAIL_FIELDS
    )
    assert set(adapter.SUMMARY_FIELDS) < set(adapter.DETAIL_FIELDS)
    assert set(adapter.DETAIL_FIELDS) - set(adapter.SUMMARY_FIELDS) == {
        "items",
        "references",
        "events",
        "headerComplete",
    }
    assert adapter.projection_of(("a", "b")) == {"_id": 0, "a": 1, "b": 1}


@pytest.mark.parametrize(
    "broken",
    [
        {"totals": {"initialAmount": True, "initialDiscount": 0, "totalAmount": 1}},
        {"totals": {"initialAmount": "124250", "initialDiscount": 0, "totalAmount": 1}},
        {"totals": {"initialAmount": 1.5, "initialDiscount": 0, "totalAmount": 1}},
        {"status": 7},
        {"orderId": None},
        {"retailer": None},
        {"events": "not-a-list"},
        {"updatedAt": None},
    ],
)
def test_a_stored_document_of_the_wrong_shape_is_refused_not_coerced(
    broken: dict[str, Any],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        adapter.order_of(stored(**broken))


def test_a_bson_64_bit_integer_becomes_a_plain_int() -> None:
    from bson.int64 import Int64

    order = adapter.order_of(
        stored(totals={"initialAmount": Int64(10), "initialDiscount": 0, "totalAmount": Int64(10)})
    )

    assert type(order.header.totals.total_amount) is int


def test_an_event_that_predates_the_causal_order_amendment_has_no_causation_id() -> None:
    entry = {
        "eventId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "eventType": "order.placed.v1",
        "occurredAt": "2026-08-18T10:15:00.100Z",
        "summary": "Order placed",
    }

    order = adapter.order_of(stored(events=[entry]))

    assert order.events[0].causation_id is None
    assert order.events[0].detail is None
