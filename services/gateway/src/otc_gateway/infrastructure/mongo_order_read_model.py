"""`MongoOrderReadModel`: the projector's `order_timeline` collection, READ ONLY (R54).

Every read names its fields. The collection also stores `statusRank`, `processedEventKeys` and
`timelineOrderVersion` (internal: `PR33`, `specs/projector_read_model/requirements.md`), and a
projection that EXCLUDED them would let any field added to the document tomorrow reach this process
by default. These queries INCLUDE a literal list instead (`SUMMARY_FIELDS`, `DETAIL_FIELDS`), and
the parsing below builds `ReadModelOrder`, which has nowhere to keep anything else: a new internal
field cannot leak by default, at either layer (`tests/unit/test_mongo_order_read_model.py`).

The only methods called on the collection are `find` and `count_documents` (the sole-writer guard
`services/projector/tests/unit/test_read_model_sole_writer.py` permits a read anywhere and fails a
write-shaped call here; `tests/unit/test_gateway_reads_only.py` pins the exact set).

Element names are camelCase literals equal to the projector's (`read_model_document.py`) and the
seed's (`services/seed/.../timeline.py:65-103`); ids are `str(UUID)`, instants are `.mmmZ` strings.
`tests/integration/test_order_read_model.py` runs this adapter against documents written by the
REAL projector writer, so a renamed element fails there and not in production.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import ConnectionFailure

from otc_gateway.application.errors import ReadModelUnavailableError
from otc_gateway.application.ports.order_read_model import (
    OrderListFilter,
    ReadModelEvent,
    ReadModelItem,
    ReadModelOrder,
    ReadModelPage,
    ReadModelParty,
    ReadModelReferences,
    ReadModelSummary,
    ReadModelTotals,
)

COLLECTION = "order_timeline"

SUMMARY_FIELDS: tuple[str, ...] = (
    "orderId",
    "orderReference",
    "orderDate",
    "retailer",
    "company",
    "status",
    "cancellationReason",
    "currency",
    "totals",
    "updatedAt",
)
DETAIL_FIELDS: tuple[str, ...] = (
    *SUMMARY_FIELDS,
    "items",
    "references",
    "events",
    "headerComplete",
)


def projection_of(fields: tuple[str, ...]) -> dict[str, int]:
    """An INCLUSION projection: exactly these elements (and not `_id`)."""
    return {"_id": 0, **dict.fromkeys(fields, 1)}


type Document = Mapping[str, Any]


def _text(doc: Document, key: str) -> str | None:
    value = doc.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"read model element {key!r} is {type(value).__name__}, expected a string")
    return value


def _required_text(doc: Document, key: str) -> str:
    value = _text(doc, key)
    if value is None:
        raise TypeError(f"read model element {key!r} is absent")
    return value


def _number(doc: Document, key: str) -> int | None:
    value = doc.get(key)
    if value is None:
        return None
    if type(value) is bool or not isinstance(value, int):
        raise TypeError(
            f"read model element {key!r} is {type(value).__name__}, expected an integer"
        )
    return int(value)  # a BSON Int64 is an int subclass; the wire model wants a plain int


def _required_number(doc: Document, key: str) -> int:
    value = _number(doc, key)
    if value is None:
        raise TypeError(f"read model element {key!r} is absent")
    return value


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text)  # `.mmmZ` -> aware UTC


def _object(doc: Document, key: str) -> Document:
    value = doc.get(key)
    if not isinstance(value, Mapping):
        raise TypeError(f"read model element {key!r} is not an object")
    return value


def _list(doc: Document, key: str) -> list[Document]:
    value = doc.get(key)
    if not isinstance(value, list):
        raise TypeError(f"read model element {key!r} is not an array")
    return [v for v in value if isinstance(v, Mapping)]


def _party(doc: Document, key: str) -> ReadModelParty:
    party = _object(doc, key)
    return ReadModelParty(
        code=_text(party, "code"), name=_text(party, "name"), gln=_text(party, "gln")
    )


def _summary(doc: Document) -> ReadModelSummary:
    totals = _object(doc, "totals")
    order_date = _text(doc, "orderDate")
    return ReadModelSummary(
        order_id=UUID(_required_text(doc, "orderId")),
        order_reference=_text(doc, "orderReference"),
        order_date=None if order_date is None else _instant(order_date),
        retailer=_party(doc, "retailer"),
        company=_party(doc, "company"),
        status=_required_text(doc, "status"),
        cancellation_reason=_text(doc, "cancellationReason"),
        currency=_text(doc, "currency"),
        totals=ReadModelTotals(
            initial_amount=_number(totals, "initialAmount"),
            initial_discount=_number(totals, "initialDiscount"),
            total_amount=_number(totals, "totalAmount"),
        ),
        updated_at=_instant(_required_text(doc, "updatedAt")),
    )


def _event(entry: Document) -> ReadModelEvent:
    causation = _text(entry, "causationId")
    detail = entry.get("detail")
    return ReadModelEvent(
        event_id=UUID(_required_text(entry, "eventId")),
        causation_id=None if causation is None else UUID(causation),
        event_type=_required_text(entry, "eventType"),
        occurred_at=_instant(_required_text(entry, "occurredAt")),
        summary=_required_text(entry, "summary"),
        detail=dict(detail) if isinstance(detail, Mapping) else None,
    )


def order_of(doc: Document) -> ReadModelOrder:
    references = _object(doc, "references")
    return ReadModelOrder(
        header=_summary(doc),
        items=tuple(
            ReadModelItem(
                product_code=_required_text(item, "productCode"),
                name=_text(item, "name"),
                quantity=_required_number(item, "quantity"),
                unit_price=_required_number(item, "unitPrice"),
                line_discount=_required_number(item, "lineDiscount"),
            )
            for item in _list(doc, "items")
        ),
        references=ReadModelReferences(
            despatch_reference=_text(references, "despatchReference"),
            invoice_reference=_text(references, "invoiceReference"),
            payment_reference=_text(references, "paymentReference"),
        ),
        events=tuple(_event(entry) for entry in _list(doc, "events")),
        header_complete=doc.get("headerComplete") is True,
    )


def _unavailable(error: ConnectionFailure) -> ReadModelUnavailableError:
    return ReadModelUnavailableError(f"the read model did not answer: {type(error).__name__}")


class MongoOrderReadModel:
    def __init__(self, collection: AsyncCollection[dict[str, Any]]) -> None:
        self._collection = collection

    async def find_by_id(self, order_id: UUID) -> ReadModelOrder | None:
        try:
            doc = await self._collection.find_one(
                {"_id": str(order_id)}, projection_of(DETAIL_FIELDS)
            )
        except ConnectionFailure as error:  # includes ServerSelectionTimeoutError
            raise _unavailable(error) from None
        return None if doc is None else order_of(doc)

    async def find_order_id_by_reference(self, order_reference: str) -> UUID | None:
        try:
            doc = await self._collection.find_one(
                {"orderReference": order_reference}, projection_of(("orderId",))
            )
        except ConnectionFailure as error:
            raise _unavailable(error) from None
        return None if doc is None else UUID(_required_text(doc, "orderId"))

    async def list_orders(self, order_filter: OrderListFilter) -> ReadModelPage:
        # R53: a placeholder (a fact outran `order.placed.v1`) has no header, and `OrderSummary`
        # requires one. It is filtered HERE, so the page and `total` count the same set.
        query: dict[str, Any] = {"headerComplete": True}
        if order_filter.statuses:
            query["status"] = {"$in": list(order_filter.statuses)}
        if order_filter.retailer_code is not None:
            query["retailer.code"] = order_filter.retailer_code
        if order_filter.company_code is not None:
            query["company.code"] = order_filter.company_code
        if order_filter.order_reference is not None:
            query["orderReference"] = order_filter.order_reference
        # `openapi.yaml` listOrders: newest `orderDate` first (`.mmmZ` strings sort
        # chronologically);
        # `_id` makes the order total, so consecutive pages never repeat or skip a row.
        cursor = (
            self._collection.find(query, projection_of(SUMMARY_FIELDS))
            .sort([("orderDate", -1), ("_id", -1)])
            .skip((order_filter.page - 1) * order_filter.page_size)
            .limit(order_filter.page_size)
        )
        try:
            documents = await cursor.to_list()
            total = await self._collection.count_documents(query)
        except ConnectionFailure as error:
            raise _unavailable(error) from None
        return ReadModelPage(items=tuple(_summary(d) for d in documents), total=total)
