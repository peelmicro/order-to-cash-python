"""The invoice replies on the wire (task E4; BI9, BI32; #8 id 65's class).

Parsed from the BYTES `to_wire_json` writes, so the exact key set and the explicit `null` are what
a consumer would see. Three pairwise-distinct, non-zero, substring-free totals (8465, 350, 8115)
land on their own keys, so a transposition changes a value the test names.

Loop scope: nothing here is async.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from otc_billing.application.messages import (
    InvoiceIssueResult,
    InvoicePage,
    InvoiceSummary,
    InvoiceViewData,
)
from otc_billing.domain.invoice_state import InvoiceStatus
from otc_billing.presentation import invoice_wire
from otc_shared_kernel import UniqueId

INVOICE_ID = UniqueId(uuid.UUID("11111111-2222-4333-8444-555555555555"))
DATE = datetime(2026, 10, 9, 8, 15, 30, 123000, tzinfo=UTC)
PAID_AT = datetime(2026, 10, 11, 17, 45, 59, 987000, tzinfo=UTC)

ISSUE_KEYS = [
    "orderReference",
    "invoiceId",
    "invoiceReference",
    "invoiceDate",
    "currency",
    "totalAmount",
    "status",
    "created",
]


def summary(status: InvoiceStatus = InvoiceStatus.ISSUED) -> InvoiceSummary:
    return InvoiceSummary(
        invoice_id=INVOICE_ID,
        invoice_reference="INV-000042",
        invoice_date=DATE,
        order_reference="ORD-000101",
        currency="EUR",
        total_amount=8115,
        status=status,
    )


def view(status: InvoiceStatus, paid_at: datetime | None) -> InvoiceViewData:
    return InvoiceViewData(
        invoice_id=INVOICE_ID,
        invoice_reference="INV-000042",
        invoice_date=DATE,
        order_reference="ORD-000101",
        retailer_code="RETAIL-77",
        company_code="SUPPLY-CO",
        currency="EUR",
        amount=8465,
        discount=350,
        total_amount=8115,
        status=status,
        paid_at=paid_at,
    )


def parsed(reply: Any) -> dict[str, Any]:
    decoded = json.loads(invoice_wire.encode(reply))
    assert isinstance(decoded, dict)
    return decoded


def test_the_issue_reply_carries_invoice_id_and_the_exact_key_set_for_created_true_and_false() -> (
    None
):
    for created in (True, False):
        reply = parsed(invoice_wire.issue_reply(InvoiceIssueResult(created, summary())))
        assert sorted(reply) == sorted(ISSUE_KEYS), f"created={created}: the key set differs"
        assert reply["invoiceId"] == str(INVOICE_ID.value), f"BI9: created={created}, no invoiceId"
        assert reply["created"] is created
        assert reply["invoiceReference"] == "INV-000042"
        assert reply["invoiceDate"] == "2026-10-09T08:15:30.123Z"
        assert reply["currency"] == "EUR"
        assert reply["totalAmount"] == 8115
        assert reply["orderReference"] == "ORD-000101"
        assert reply["status"] == "issued"
    paid = parsed(invoice_wire.issue_reply(InvoiceIssueResult(False, summary(InvoiceStatus.PAID))))
    assert paid["status"] == "paid"


def test_bi32_an_issued_view_writes_paid_at_null_and_a_paid_view_writes_the_instant() -> None:
    page = InvoicePage(
        items=(view(InvoiceStatus.ISSUED, None), view(InvoiceStatus.PAID, PAID_AT)),
        page=1,
        page_size=25,
        total=2,
    )
    text = invoice_wire.encode(invoice_wire.list_reply(page)).decode("utf-8")
    reply = json.loads(text)
    assert reply["page"]["total"] == 2
    issued, paid = reply["items"]
    assert "paidAt" in issued, "BI32: the key is absent for an issued invoice"
    assert issued["paidAt"] is None
    assert paid["paidAt"] == "2026-10-11T17:45:59.987Z"
    assert text.count('"paidAt":null') == 1, "BI32: expected exactly one explicit null"
    assert text.count("null") == 1, "BI32: no other null may appear in an invoice reply"


def test_amount_discount_and_total_amount_land_on_their_own_keys() -> None:
    page = InvoicePage(items=(view(InvoiceStatus.ISSUED, None),), page=3, page_size=7, total=21)
    reply = parsed(invoice_wire.list_reply(page))
    [item] = reply["items"]
    assert (item["amount"], item["discount"], item["totalAmount"]) == (8465, 350, 8115)
    assert item["invoiceId"] == str(INVOICE_ID.value)
    assert (item["retailerCode"], item["companyCode"]) == ("RETAIL-77", "SUPPLY-CO")
    assert item["orderReference"] == "ORD-000101"
    assert item["invoiceDate"] == "2026-10-09T08:15:30.123Z"
    assert reply["page"] == {"page": 3, "pageSize": 7, "total": 21}
