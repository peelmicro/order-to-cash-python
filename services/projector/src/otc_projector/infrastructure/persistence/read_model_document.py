"""The read-model document: the collection, its version, and the placeholder.

The document is the seed's, byte for byte (`services/seed/src/otc_seed/domain/timeline.py:65-103`):
same element names (camelCase literals), same nested key order, same string ids and `.mmmZ` instants
(`PR41`). Its top-level element order is the server's, not ours: `$setOnInsert` stores the keys
after `_id` lexicographically (measured on `mongo:8.3.8`, design 3.2), and the seed creates its
documents with the same operator, so the two writers give the same order for free PROVIDED the
placeholder is total over the shape (a later pipeline `$set` of a key that does not exist would
append it at the end). `unit/test_placeholder.py` pins the key set to the seed's.

`retailer`, `company`, `totals` and `references` are objects of explicit-`null` leaves, never a
`null` object: a pipeline `$set` of `"retailer.code"` onto a `null` parent silently REPLACES the
`null` with `{"code": ...}` and `name`/`gln` vanish (measured, design 3.3).

`TIMELINE_ORDER_VERSION` and the collection name equal `tests/fixtures/read_model_constants.json`
(`PR40`, `unit/test_read_model_constants.py`); the seed keeps its own local copies pinned to the
same file.
"""

from typing import Final

COLLECTION: Final = "order_timeline"
TIMELINE_ORDER_VERSION: Final = 2
TIMELINE_ORDER_VERSION_FIELD: Final = "timelineOrderVersion"


def placeholder(order_id: str, occurred_at_wire: str) -> dict[str, object]:
    """The document a fact other than `order.placed.v1` creates for an absent order (`PR8`).

    `updatedAt` is the triggering fact's own `occurredAt`, never a clock (`PR14`, `PR15`).
    """
    return {
        "_id": order_id,
        "orderId": order_id,
        "orderReference": None,
        "orderDate": None,
        "retailer": {"code": None, "name": None, "gln": None},
        "company": {"code": None, "name": None, "gln": None},
        "status": "placed",
        "cancellationReason": None,
        "currency": None,
        "totals": {"initialAmount": None, "initialDiscount": None, "totalAmount": None},
        "items": [],
        "references": {
            "despatchReference": None,
            "invoiceReference": None,
            "paymentReference": None,
        },
        "events": [],
        "headerComplete": False,
        "updatedAt": occurred_at_wire,
        "statusRank": 0,
        TIMELINE_ORDER_VERSION_FIELD: TIMELINE_ORDER_VERSION,
        "processedEventKeys": [],
    }
