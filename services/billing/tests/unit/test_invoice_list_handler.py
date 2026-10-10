"""`ListInvoicesHandler`: the clock is read ONCE and handed to the adapter (task J1; BI15, L20).

The adapter takes `now` as a parameter so a test controls it; this is the test that the HANDLER
passes the clock port's value and not the wall clock's. A fixed instant five years from any run
cannot be mistaken for `datetime.now()`.

Loop scope: function (pytest-asyncio default); only in-memory fakes are awaited.
"""

from datetime import UTC, datetime
from typing import Any

from otc_billing.application.handlers import ListInvoicesHandler
from otc_billing.application.messages import InvoicePage, ListInvoicesQuery
from otc_billing.domain.invoice_state import InvoiceStatus

FIXED = datetime(2031, 3, 15, 12, 0, 0, 123000, tzinfo=UTC)


class FixedClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return FIXED


class RecordingReads:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def find_by_order_reference(self, order_reference: str) -> None:
        raise AssertionError("the list read an invoice by order")

    async def list(self, **kwargs: Any) -> InvoicePage:
        self.calls.append(kwargs)
        return InvoicePage((), kwargs["page"], kwargs["page_size"], 0)


class Scope:
    def __init__(self) -> None:
        self.clock = FixedClock()
        self.invoice_reads = RecordingReads()


async def test_bi15_the_handler_reads_the_clock_once_and_hands_that_instant_and_every_filter() -> (
    None
):
    scope = Scope()
    query = ListInvoicesQuery(
        page=3,
        page_size=7,
        status=InvoiceStatus.PAID,
        retailer_code="RETAIL-77",
        company_code="SUPPLY-CO",
        order_reference="ORD-000101",
        issued_before_minutes=60,
    )

    page = await ListInvoicesHandler(scope).handle(query)  # type: ignore[arg-type]

    assert scope.clock.calls == 1, "the clock must be read exactly once"
    [call] = scope.invoice_reads.calls
    assert call["now"] == FIXED, "the adapter was not handed the clock port's instant"
    assert call == {
        "page": 3,
        "page_size": 7,
        "status": InvoiceStatus.PAID,
        "retailer_code": "RETAIL-77",
        "company_code": "SUPPLY-CO",
        "order_reference": "ORD-000101",
        "issued_before_minutes": 60,
        "now": FIXED,
    }
    assert (page.page, page.page_size) == (3, 7)
