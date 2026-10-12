"""A read-model document as the wire shapes `OrderSummary` and `OrderDetail` (`openapi.yaml`).

Every field is copied by name, from its own source, into the generated model: the wire model is an
allow-list, so a field the document gains tomorrow reaches the wire only when someone writes it
here (the projector's internal fields never can: `ReadModelOrder` has no place for them).

Money is never computed: the three order totals are the document's own integers, each from its own
field (`initialAmount`, `initialDiscount`, `totalAmount` are three different values, and a
transposition of two of them is what `tests/unit/test_order_views.py` is built to fail).

A placeholder (R53: a fact outran `order.placed.v1`) has no header yet. In the DETAIL its absent
parts are absent and `headerComplete` is `false`; the LIST never contains one (the adapter filters
them out, so the page and its `total` agree).
"""

from otc_contracts.generated import openapi
from otc_gateway.application.ports.order_read_model import (
    ReadModelEvent,
    ReadModelItem,
    ReadModelOrder,
    ReadModelParty,
    ReadModelReferences,
    ReadModelSummary,
    ReadModelTotals,
)


class IncompleteOrderHeaderError(Exception):
    """A document the list was given has no usable header: the adapter's filter and the document
    disagree, which is a defect, not a row to skip."""


def _party(party: ReadModelParty) -> openapi.PartyRef | None:
    if party.code is None or party.gln is None:  # `PartyRef` requires both
        return None
    return openapi.PartyRef(code=party.code, name=party.name, gln=party.gln)


def _totals(totals: ReadModelTotals) -> openapi.OrderTotals | None:
    if (
        totals.initial_amount is None
        or totals.initial_discount is None
        or totals.total_amount is None
    ):
        return None  # all three or none: an amount is never invented
    return openapi.OrderTotals(
        initial_amount=totals.initial_amount,
        initial_discount=totals.initial_discount,
        total_amount=totals.total_amount,
    )


def _item(item: ReadModelItem) -> openapi.OrderItem:
    return openapi.OrderItem(
        product_code=item.product_code,
        name=item.name,
        quantity=item.quantity,
        unit_price=item.unit_price,
        line_discount=item.line_discount,
    )


def _references(references: ReadModelReferences) -> openapi.OrderReferences:
    return openapi.OrderReferences(
        despatch_reference=(
            None
            if references.despatch_reference is None
            else openapi.DespatchReference(references.despatch_reference)
        ),
        invoice_reference=(
            None
            if references.invoice_reference is None
            else openapi.InvoiceReference(references.invoice_reference)
        ),
        payment_reference=(
            None
            if references.payment_reference is None
            else openapi.PaymentReference(references.payment_reference)
        ),
    )


def _event(event: ReadModelEvent) -> openapi.TimelineEntry:
    return openapi.TimelineEntry(
        event_id=event.event_id,
        causation_id=event.causation_id,
        event_type=event.event_type,
        occurred_at=event.occurred_at,
        summary=event.summary,
        detail=event.detail,
    )


def order_detail(order: ReadModelOrder) -> openapi.OrderDetail:
    header = order.header
    return openapi.OrderDetail(
        order_id=header.order_id,
        order_reference=header.order_reference,
        order_date=header.order_date,
        retailer=_party(header.retailer),
        company=_party(header.company),
        status=openapi.OrderStatus(header.status),
        cancellation_reason=(
            None
            if header.cancellation_reason is None
            else openapi.CancellationReason(header.cancellation_reason)
        ),
        currency=header.currency,
        totals=_totals(header.totals),
        items=[_item(i) for i in order.items],
        references=_references(order.references),
        events=[_event(e) for e in order.events],
        header_complete=order.header_complete,
        updated_at=header.updated_at,
    )


def order_summary(header: ReadModelSummary) -> openapi.OrderSummary:
    retailer = _party(header.retailer)
    company = _party(header.company)
    totals = _totals(header.totals)
    if (
        header.order_reference is None
        or header.order_date is None
        or header.currency is None
        or retailer is None
        or company is None
        or totals is None
    ):
        raise IncompleteOrderHeaderError(
            f"order {header.order_id} reached the list with an incomplete header"
        )
    return openapi.OrderSummary(
        order_id=header.order_id,
        order_reference=header.order_reference,
        order_date=header.order_date,
        retailer=retailer,
        company=company,
        status=openapi.OrderStatus(header.status),
        cancellation_reason=(
            None
            if header.cancellation_reason is None
            else openapi.CancellationReason(header.cancellation_reason)
        ),
        currency=header.currency,
        totals=totals,
        updated_at=header.updated_at,
    )
