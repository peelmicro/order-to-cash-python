"""`delta_to_pipeline`: one `ProjectionDelta` as ONE aggregation-pipeline `$set` stage (`PR6`).

Pure: `(delta, dedup_key) -> [stage]`, unit-tested on the emitted tree. With
`L(x) = {"$literal": x}`:

* **Every value taken from a fact is literal-wrapped (`PR47`).** Inside a pipeline an unwrapped
  string beginning with `$` is a field path and one beginning with `$$` a variable: an operator
  note `"$status"` was stored as the document's own status, and a `lastError` `"$$NOW x"` failed
  the whole update with `FailedToParse` (a poison record, redelivered forever). Measured on
  `mongo:8.3.8`. The rule is total, not selective, so the guard is structural.
* **Every array and rank operand is `$ifNull`-guarded**: `$setUnion` and `$concatArrays` fail on a
  missing field and a missing `statusRank` compares as `null`, below every number.
* `status` uses a strict `$gt`, `statusRank` a `$max`, both against the pre-update document within
  the one stage; for a status-less fact (rank 0) both are no-ops, so the stage keeps one shape.
* `updatedAt` is the `$max` of `occurredAt` text (fixed-width `.mmmZ`), never a clock (`PR14`).
* `processedEventKeys` is stored sorted (`$sortArray`): the dedup ledger is a pure function of the
  SET of facts applied (`PR15`).
* Dotted outputs (`"retailer.code"`) set only the named leaf of an existing object.
"""

from typing import Any

from otc_contracts import format_instant
from otc_projector.domain.projection_delta import HeaderDelta, ProjectionDelta, TimelineEntryDelta
from otc_projector.infrastructure.persistence.read_model_document import (
    TIMELINE_ORDER_VERSION,
    TIMELINE_ORDER_VERSION_FIELD,
)
from otc_projector.infrastructure.persistence.timeline_order import timeline_order_expression


def literal(value: object) -> dict[str, object]:
    return {"$literal": value}


def entry_document(entry: TimelineEntryDelta) -> dict[str, object]:
    """The stored entry, in the seed's element order (`timeline.py:55-63`)."""
    document: dict[str, object] = {
        "eventId": entry.event_id,
        "eventType": entry.event_type,
        "occurredAt": format_instant(entry.occurred_at),
        "summary": entry.summary,
    }
    if entry.detail is not None:
        document["detail"] = dict(entry.detail)
    document["causationId"] = entry.causation_id
    return document


def _header_fields(header: HeaderDelta) -> dict[str, Any]:
    """The header `order.placed.v1` writes UNCONDITIONALLY (`PR9`): no `$ifNull`."""
    return {
        "orderReference": literal(header.order_reference),
        "orderDate": literal(format_instant(header.order_date)),
        "retailer.code": literal(header.retailer_code),
        "retailer.gln": literal(header.retailer_gln),
        "company.code": literal(header.company_code),
        "company.gln": literal(header.company_gln),
        "currency": literal(header.currency),
        "totals.initialAmount": literal(header.initial_amount),
        "totals.initialDiscount": literal(header.initial_discount),
        "totals.totalAmount": literal(header.total_amount),
        "items": literal(
            [
                {
                    "productCode": item.product_code,
                    "name": None,
                    "quantity": item.quantity,
                    "unitPrice": item.unit_price,
                    "lineDiscount": item.line_discount,
                }
                for item in header.items
            ]
        ),
        "headerComplete": literal(True),
    }


def delta_to_pipeline(delta: ProjectionDelta, dedup_key: str) -> list[dict[str, object]]:
    occurred_at = format_instant(delta.entry.occurred_at)
    current_rank: dict[str, object] = {"$ifNull": ["$statusRank", 0]}
    fields: dict[str, Any] = {
        "processedEventKeys": {
            "$sortArray": {
                "input": {
                    "$setUnion": [{"$ifNull": ["$processedEventKeys", []]}, literal([dedup_key])]
                },
                "sortBy": 1,
            }
        },
        "events": timeline_order_expression(
            {
                "$concatArrays": [
                    {"$ifNull": ["$events", []]},
                    [literal(entry_document(delta.entry))],
                ]
            }
        ),
        "statusRank": {"$max": [current_rank, literal(delta.status_rank)]},
        "status": {
            "$cond": [
                {"$gt": [literal(delta.status_rank), current_rank]},
                literal(delta.implied_status),
                "$status",
            ]
        },
        "references.despatchReference": {
            "$ifNull": [
                "$references.despatchReference",
                literal(delta.despatch_reference_if_absent),
            ]
        },
        "references.invoiceReference": {
            "$ifNull": ["$references.invoiceReference", literal(delta.invoice_reference_if_absent)]
        },
        "references.paymentReference": {
            "$ifNull": ["$references.paymentReference", literal(delta.payment_reference_if_absent)]
        },
        "cancellationReason": {
            "$ifNull": ["$cancellationReason", literal(delta.cancellation_reason_if_absent)]
        },
        "updatedAt": {
            "$max": [{"$ifNull": ["$updatedAt", literal(occurred_at)]}, literal(occurred_at)]
        },
        TIMELINE_ORDER_VERSION_FIELD: literal(TIMELINE_ORDER_VERSION),
    }
    if delta.header is not None:
        fields.update(_header_fields(delta.header))
    return [{"$set": fields}]
