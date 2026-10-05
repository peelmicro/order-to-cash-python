"""The `order_timeline` read-model document of one seeded saga.

One document per seeded order, shaped exactly as `specs/shared/openapi.yaml`'s `OrderDetail`
schema plus the three projector-owned fields (`statusRank`, `timelineOrderVersion`,
`processedEventKeys`), so a seeded document is indistinguishable from one the projector would have
written and the projector's boot migration never has reason to touch it. `_id` is the order id,
which is what makes re-seeding idempotent.

The status-rank table, `TIMELINE_ORDER_VERSION`, the dedup-key prefix and the index name are LOCAL
copies of the projector's, never imported (services never import each other). They are pinned to
`tests/fixtures/read_model_constants.json` by `tests/unit/test_read_model_constants.py` and to #7's
oracle by `tests/unit/test_timeline_value_guard.py`; the projector (feature 24,
`projector_read_model`) is pinned to the same fixture by its last acceptance item (backlog 212).
`causationId` is written from the fixture's own declared edge, never inferred
from array position, because a blank one is silently unrecoverable: the projector's migration never
invents an edge that was never recorded.
"""

from typing import Any

from otc_seed.domain.clock import format_instant
from otc_seed.domain.data.companies import company_by_code
from otc_seed.domain.data.products import product_by_code
from otc_seed.domain.data.retailers import retailer_by_code
from otc_seed.domain.data.sagas import OrderSagaFixture

ORDER_TIMELINE_COLLECTION = "order_timeline"
# A local copy of the projector's own `TIMELINE_ORDER_VERSION`: a seeded document is written at the
# current version so it is never mistaken for one that needs repairing.
TIMELINE_ORDER_VERSION = 2
# The projector's status rank table (PR12), totalised: completed and cancelled outrank every
# in-flight status.
STATUS_RANK: dict[str, int] = {
    "placed": 1,
    "stock_reserved": 2,
    "credit_approved": 3,
    "confirmed": 4,
    "despatched": 5,
    "invoiced": 6,
    "paid": 7,
    "completed": 98,
    "cancelled": 99,
}
# The projector's dedup-ledger prefix: `<consumer>:<eventId>`.
PROCESSED_EVENT_CONSUMER = "projector"


def to_timeline_document(saga: OrderSagaFixture) -> dict[str, Any]:
    retailer = retailer_by_code(saga.retailer_code)
    company = company_by_code(saga.company_code)
    # Ordered by occurredAt (R50); a stable sort, so construction order breaks ties.
    entries = sorted(saga.timeline, key=lambda entry: entry.occurred_at)
    events: list[dict[str, Any]] = []
    for entry in entries:
        event: dict[str, Any] = {
            "eventId": entry.event_id,
            "eventType": entry.event_type,
            "occurredAt": format_instant(entry.occurred_at),
            "summary": entry.summary,
        }
        if entry.detail is not None:
            event["detail"] = dict(entry.detail)
        event["causationId"] = entry.causation_id
        events.append(event)
    return {
        "_id": saga.order_id,
        "orderId": saga.order_id,
        "orderReference": saga.order_reference,
        "orderDate": format_instant(saga.order_date),
        "retailer": {"code": retailer.code, "name": retailer.name, "gln": retailer.gln},
        "company": {"code": company.code, "name": company.name, "gln": company.gln},
        "status": saga.status,
        "cancellationReason": saga.cancellation_reason,
        "currency": saga.currency,
        "totals": {
            "initialAmount": saga.initial_amount,
            "initialDiscount": saga.initial_discount,
            "totalAmount": saga.total_amount,
        },
        "items": [
            {
                "productCode": line.product_code,
                "name": product_by_code(line.product_code).name,
                "quantity": line.quantity,
                "unitPrice": line.unit_price,
                "lineDiscount": line.line_discount,
            }
            for line in saga.lines
        ],
        "references": {
            "despatchReference": saga.despatch.despatch_reference if saga.despatch else None,
            "invoiceReference": saga.invoice.invoice_reference if saga.invoice else None,
            "paymentReference": saga.invoice.payment.payment_reference if saga.invoice else None,
        },
        "events": events,
        "headerComplete": True,
        "updatedAt": format_instant(saga.updated_at),
        "statusRank": STATUS_RANK[saga.status],
        "timelineOrderVersion": TIMELINE_ORDER_VERSION,
        "processedEventKeys": sorted(
            f"{PROCESSED_EVENT_CONSUMER}:{entry.event_id}" for entry in saga.timeline
        ),
    }
