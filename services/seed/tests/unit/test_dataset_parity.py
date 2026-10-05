"""Dataset parity with #7: every row of every table equals what #7's TypeScript computes.

R-map (feature_list.json id 12, acceptance 2; backlog 201 item 3: the seeded causal chain is #8's,
unchanged): the population is every row of `seed_dataset_from_number7.json`, compared field by
field; the expected set is the oracle file, never this port's own output.
"""

from typing import Any

from otc_seed.domain.clock import format_instant
from otc_seed.domain.data.companies import COMPANIES
from otc_seed.domain.data.credits import CREDITS
from otc_seed.domain.data.currencies import CURRENCIES
from otc_seed.domain.data.products import PRODUCTS
from otc_seed.domain.data.retailers import RETAILERS
from otc_seed.domain.data.sagas import SAGAS, OutboxFixture
from otc_seed.domain.data.stock import STOCK


def _iso(value: Any) -> str:
    return format_instant(value)


def test_master_data_rows_equal_number7s(number7_dataset: dict[str, Any]) -> None:
    d = number7_dataset
    assert [
        {
            "id": c.id,
            "code": c.code,
            "isoNumber": c.iso_number,
            "symbol": c.symbol,
            "decimalPoints": c.decimal_points,
        }
        for c in CURRENCIES
    ] == d["currencies"]
    assert [
        {
            "id": p.id,
            "code": p.code,
            "ean": p.ean,
            "name": p.name,
            "description": p.description,
            "price": p.price,
            "currencyCode": p.currency_code,
        }
        for p in PRODUCTS
    ] == d["products"]
    for ours, key in ((RETAILERS, "retailers"), (COMPANIES, "companies")):
        assert [
            {
                "id": r.id,
                "code": r.code,
                "name": r.name,
                "country": r.country,
                "vat": r.vat,
                "gln": r.gln,
                "currencyCode": r.currency_code,
            }
            for r in ours
        ] == d[key]
    assert [
        {
            "id": c.id,
            "code": c.code,
            "retailerCode": c.retailer_code,
            "companyCode": c.company_code,
            "creditLimit": c.credit_limit,
            "currencyCode": c.currency_code,
        }
        for c in CREDITS
    ] == d["credits"]
    assert [
        {
            "id": s.id,
            "companyCode": s.company_code,
            "productCode": s.product_code,
            "units": s.units,
            "reservedUnits": s.reserved_units,
            "lowStockThreshold": s.low_stock_threshold,
        }
        for s in STOCK
    ] == d["stock"]


def _outbox(f: OutboxFixture) -> dict[str, Any]:
    return {
        "id": f.id,
        "eventId": f.event_id,
        "eventType": f.event_type,
        "aggregateId": f.aggregate_id,
        "correlationId": f.correlation_id,
        "causationId": f.causation_id,
        "payload": dict(f.payload),
        "occurredAt": _iso(f.occurred_at),
        "publishedAt": _iso(f.published_at),
    }


def test_every_saga_fact_equals_number7s(number7_dataset: dict[str, Any]) -> None:
    expected = number7_dataset["sagas"]
    assert [s.sequence for s in SAGAS] == [e["sequence"] for e in expected] == [1, 2, 3, 4, 5, 6]
    for saga, e in zip(SAGAS, expected, strict=True):
        assert saga.order_id == e["orderId"]
        assert saga.order_reference == e["orderReference"]
        assert _iso(saga.order_date) == e["orderDate"]
        assert (saga.retailer_code, saga.company_code, saga.currency) == (
            e["retailerCode"],
            e["companyCode"],
            e["currency"],
        )
        assert (saga.status, saga.cancellation_reason) == (e["status"], e["cancellationReason"])
        assert (saga.initial_amount, saga.initial_discount, saga.total_amount) == (
            e["initialAmount"],
            e["initialDiscount"],
            e["totalAmount"],
        )
        assert _iso(saga.updated_at) == e["updatedAt"]
        assert [
            {
                "productCode": line.product_code,
                "description": line.description,
                "quantity": line.quantity,
                "unitPrice": line.unit_price,
                "lineDiscount": line.line_discount,
            }
            for line in saga.lines
        ] == e["lines"]
        assert [_outbox(f) for f in saga.orders_outbox] == e["ordersOutbox"]
        assert [_outbox(f) for f in saga.fulfillment_outbox] == e["fulfillmentOutbox"]
        assert [_outbox(f) for f in saga.billing_outbox] == e["billingOutbox"]
        assert [
            {
                "id": r.id,
                "companyCode": r.company_code,
                "retailerCode": r.retailer_code,
                "productCode": r.product_code,
                "units": r.units,
                "status": r.status,
                "createdAt": _iso(r.created_at),
                "updatedAt": _iso(r.updated_at),
            }
            for r in saga.reservations
        ] == e["reservations"]
        despatch = None
        if saga.despatch:
            d = saga.despatch
            despatch = {
                "id": d.id,
                "despatchReference": d.despatch_reference,
                "despatchDate": _iso(d.despatch_date),
                "companyCode": d.company_code,
                "retailerCode": d.retailer_code,
                "items": [{"productCode": i.product_code, "units": i.units} for i in d.items],
            }
        assert despatch == e["despatch"]
        assert [
            {
                "id": x.id,
                "creditId": x.credit_id,
                "orderReference": x.order_reference,
                "amount": x.amount,
                "type": x.type,
                "creditDate": _iso(x.credit_date),
            }
            for x in saga.credit_ledger_entries
        ] == e["creditLedgerEntries"]
        invoice = None
        if saga.invoice:
            i = saga.invoice
            invoice = {
                "id": i.id,
                "invoiceReference": i.invoice_reference,
                "invoiceDate": _iso(i.invoice_date),
                "amount": i.amount,
                "discount": i.discount,
                "totalAmount": i.total_amount,
                "status": i.status,
                "paidAt": _iso(i.paid_at),
                "items": [
                    {"productCode": x.product_code, "units": x.units, "price": x.price}
                    for x in i.items
                ],
                "payment": {
                    "id": i.payment.id,
                    "paymentReference": i.payment.payment_reference,
                    "amount": i.payment.amount,
                    "valueDate": _iso(i.payment.value_date),
                    "source": i.payment.source,
                },
            }
        assert invoice == e["invoice"]
        timeline = []
        for t in saga.timeline:
            entry: dict[str, Any] = {
                "eventId": t.event_id,
                "eventType": t.event_type,
                "occurredAt": _iso(t.occurred_at),
                "summary": t.summary,
                "causationId": t.causation_id,
            }
            if t.detail is not None:
                entry["detail"] = dict(t.detail)
            timeline.append(entry)
        assert timeline == e["timeline"]


def test_the_seeded_causal_chain_is_number7s_one_link_shorter_than_a_live_saga(
    number7_dataset: dict[str, Any],
) -> None:
    """Backlog 201 item 3. In every saga each fact's `causationId` is either the eventId of an
    EARLIER fact of the same saga, or one of the two synthetic command ids (the roots); never a
    responder command id, which is what a live saga's responder facts cite. The chain is unchanged
    from #7's (the equality test above), and this states its shape."""
    for saga in SAGAS:
        event_ids = {t.event_id for t in saga.timeline}
        roots = [t for t in saga.timeline if t.causation_id not in event_ids]
        assert len(roots) == (2 if saga.status == "completed" else 1)
        for entry in roots:
            assert entry.event_type in {"order.placed.v1", "payment.received.v1"}
        for entry in saga.timeline:
            if entry.causation_id in event_ids:
                cause = next(t for t in saga.timeline if t.event_id == entry.causation_id)
                assert cause.occurred_at < entry.occurred_at
