"""`application/order_views.py`: a read-model document as `OrderSummary` / `OrderDetail`.

The fields are copied by name from their own source into the generated models (E1: #8's
transposition survived a whole suite). The HTTP tests assert the whole body; these assert the rule
a placeholder (R53) and an incomplete header follow: the DETAIL tolerates what the LIST must never
carry, and an incomplete header reaching the list is a defect, not a row to skip silently.
"""

import dataclasses
from datetime import UTC, datetime
from uuid import UUID

import pytest

from otc_gateway.application.order_views import (
    IncompleteOrderHeaderError,
    order_detail,
    order_summary,
)
from otc_gateway.application.ports.order_read_model import (
    ReadModelOrder,
    ReadModelParty,
    ReadModelReferences,
    ReadModelSummary,
    ReadModelTotals,
)

AT = datetime(2026, 8, 18, 10, 15, 0, tzinfo=UTC)
COMPLETE = ReadModelSummary(
    order_id=UUID(int=1),
    order_reference="ORD-000042",
    order_date=AT,
    retailer=ReadModelParty("R", "Retailer", "8412345000013"),
    company=ReadModelParty("C", None, "8412345000020"),
    status="placed",
    cancellation_reason=None,
    currency="EUR",
    totals=ReadModelTotals(300, 20, 280),
    updated_at=AT,
)


def document(header: ReadModelSummary, *, complete: bool = True) -> ReadModelOrder:
    return ReadModelOrder(
        header=header,
        items=(),
        references=ReadModelReferences(None, None, None),
        events=(),
        header_complete=complete,
    )


def test_a_complete_header_is_a_summary_with_each_total_from_its_own_field() -> None:
    summary = order_summary(COMPLETE)

    assert (summary.totals.initial_amount, summary.totals.initial_discount) == (300, 20)
    assert summary.totals.total_amount == 280
    assert summary.retailer.name == "Retailer"
    assert summary.company.name is None  # master data the projector has not written (PR9)


@pytest.mark.parametrize(
    "gap",
    [
        {"order_reference": None},
        {"order_date": None},
        {"currency": None},
        {"retailer": ReadModelParty(None, None, None)},
        {"retailer": ReadModelParty("R", "Retailer", None)},
        {"company": ReadModelParty(None, "x", "8412345000020")},
        {"totals": ReadModelTotals(None, None, None)},
        {"totals": ReadModelTotals(300, None, 280)},
    ],
)
def test_a_header_with_any_required_part_missing_never_becomes_a_list_row(
    gap: dict[str, object],
) -> None:
    with pytest.raises(IncompleteOrderHeaderError):
        order_summary(dataclasses.replace(COMPLETE, **gap))  # type: ignore[arg-type]


def test_the_detail_of_a_header_with_gaps_omits_the_gaps_and_says_header_complete_false() -> None:
    detail = order_detail(
        document(
            dataclasses.replace(
                COMPLETE,
                order_reference=None,
                retailer=ReadModelParty(None, None, None),
                totals=ReadModelTotals(300, None, 280),
            ),
            complete=False,
        )
    )

    assert detail.order_reference is None
    assert detail.retailer is None
    assert detail.totals is None  # all three or none: an amount is never invented
    assert detail.header_complete is False
    assert detail.company is not None
