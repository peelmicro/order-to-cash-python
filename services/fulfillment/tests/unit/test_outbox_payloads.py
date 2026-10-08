"""Domain event -> wire fact, every field against a distinct source value (C4).

No store, no broker. Each event is built with values that are pairwise distinct across the whole
test (four ids, three reservation ids, two product codes, `companyCode` and `retailerCode` apart,
requested apart from available), so a mapper that reads `company_code` for `retailer_code` or a
constant for `reason` produces a value the assertion cannot mistake for the right one.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import TypedDict

import pytest

from otc_contracts import to_wire_json
from otc_contracts.generated import asyncapi
from otc_fulfillment.domain.events import (
    RejectionReason,
    ReleaseReason,
    ReservationRef,
    Shortage,
    StockRejected,
    StockReleased,
    StockReserved,
)
from otc_fulfillment.infrastructure.outbox.errors import UnmappedDomainEventError
from otc_fulfillment.infrastructure.outbox.payloads import build_fact, narrow
from otc_shared_kernel import UniqueId


def uid(n: int) -> UniqueId:
    return UniqueId(uuid.UUID(f"00000000-0000-4000-8000-{n:012d}"))


EVENT_ID, AGGREGATE_ID, CORRELATION_ID, CAUSATION_ID = uid(1), uid(2), uid(3), uid(4)
OCCURRED_AT = datetime(2026, 10, 8, 9, 30, 5, 123987, tzinfo=UTC)  # sub-millisecond: truncated
ORDER_REFERENCE = "ORD-000123"
COMPANY = "CMP-88"
RETAILER = "RET-77"


class Identity(TypedDict):
    event_id: UniqueId
    aggregate_id: UniqueId
    correlation_id: UniqueId
    causation_id: UniqueId
    occurred_at: datetime


def identity() -> Identity:
    return Identity(
        event_id=EVENT_ID,
        aggregate_id=AGGREGATE_ID,
        correlation_id=CORRELATION_ID,
        causation_id=CAUSATION_ID,
        occurred_at=OCCURRED_AT,
    )


REFS = (
    ReservationRef(reservation_id=uid(11), product_code="PRD-A1", units=3),
    ReservationRef(reservation_id=uid(12), product_code="PRD-B2", units=5),
)


def reserved() -> StockReserved:
    return StockReserved(
        **identity(),
        order_reference=ORDER_REFERENCE,
        company_code=COMPANY,
        retailer_code=RETAILER,
        reservations=REFS,
    )


def rejected(reason: RejectionReason = RejectionReason.UNKNOWN_PRODUCT) -> StockRejected:
    return StockRejected(
        **identity(),
        order_reference=ORDER_REFERENCE,
        company_code=COMPANY,
        retailer_code=RETAILER,
        shortages=(
            Shortage(product_code="PRD-A1", requested=9, available=4),
            Shortage(product_code="PRD-B2", requested=2, available=0),
        ),
        reason=reason,
    )


def released(reason: ReleaseReason = ReleaseReason.ORDER_CANCELLED) -> StockReleased:
    return StockReleased(
        **identity(),
        order_reference=ORDER_REFERENCE,
        company_code=COMPANY,
        retailer_code=RETAILER,
        released=REFS,
        reason=reason,
    )


def wire(payload: object) -> dict[str, object]:
    assert isinstance(
        payload,
        asyncapi.StockReservedPayload
        | asyncapi.StockRejectedPayload
        | asyncapi.StockReleasedPayload,
    )
    parsed: dict[str, object] = json.loads(to_wire_json(payload))
    return parsed


def assert_envelope(fact_envelope: object, event_type: str) -> None:
    dumped = json.loads(to_wire_json(fact_envelope))  # type: ignore[arg-type]
    assert list(dumped)[:7] == [
        "eventId",
        "eventType",
        "aggregateId",
        "correlationId",
        "causationId",
        "occurredAt",
        "payload",
    ], "the envelope's field order is the spec's"
    assert dumped["eventId"] == str(EVENT_ID)
    assert dumped["eventType"] == event_type
    assert dumped["aggregateId"] == str(AGGREGATE_ID)
    assert dumped["correlationId"] == str(CORRELATION_ID)
    assert dumped["causationId"] == str(CAUSATION_ID)
    assert dumped["occurredAt"] == "2026-10-08T09:30:05.123Z", "truncated to the millisecond"


EXPECTED_REFS = [
    {"reservationId": str(uid(11)), "productCode": "PRD-A1", "units": 3},
    {"reservationId": str(uid(12)), "productCode": "PRD-B2", "units": 5},
]


def test_c4_stock_reserved_becomes_its_payload_with_every_field_equal_to_the_supplied_value() -> (
    None
):
    built = build_fact(reserved())

    assert isinstance(built.payload, asyncapi.StockReservedPayload)
    assert wire(built.payload) == {
        "orderReference": ORDER_REFERENCE,
        "companyCode": COMPANY,
        "retailerCode": RETAILER,
        "reservations": EXPECTED_REFS,
    }
    assert_envelope(built.envelope, "stock.reserved.v1")
    assert built.occurred_at == datetime(2026, 10, 8, 9, 30, 5, 123000, tzinfo=UTC)


@pytest.mark.parametrize(
    ("reason", "token"),
    [
        (RejectionReason.UNKNOWN_PRODUCT, "unknown_product"),
        (RejectionReason.INSUFFICIENT_STOCK, "insufficient_stock"),
    ],
)
def test_c4_stock_rejected_becomes_its_payload_with_every_field_equal_to_the_supplied_value(
    reason: RejectionReason, token: str
) -> None:
    built = build_fact(rejected(reason))

    assert isinstance(built.payload, asyncapi.StockRejectedPayload)
    assert wire(built.payload) == {
        "orderReference": ORDER_REFERENCE,
        "companyCode": COMPANY,
        "retailerCode": RETAILER,
        "shortages": [
            {"productCode": "PRD-A1", "requested": 9, "available": 4},
            {"productCode": "PRD-B2", "requested": 2, "available": 0},
        ],
        "reason": token,
    }
    assert_envelope(built.envelope, "stock.rejected.v1")


@pytest.mark.parametrize(
    ("reason", "token"),
    [
        (ReleaseReason.ORDER_CANCELLED, "order_cancelled"),
        (ReleaseReason.CREDIT_REJECTED, "credit_rejected"),
    ],
)
def test_c4_stock_released_becomes_its_payload_with_every_field_equal_to_the_supplied_value(
    reason: ReleaseReason, token: str
) -> None:
    built = build_fact(released(reason))

    assert isinstance(built.payload, asyncapi.StockReleasedPayload)
    assert wire(built.payload) == {
        "orderReference": ORDER_REFERENCE,
        "companyCode": COMPANY,
        "retailerCode": RETAILER,
        "released": EXPECTED_REFS,
        "reason": token,
    }
    assert_envelope(built.envelope, "stock.released.v1")


def test_c4_an_event_class_with_no_mapping_is_refused_naming_the_class() -> None:
    class StockSomethingElse:
        pass

    with pytest.raises(UnmappedDomainEventError) as refusal:
        narrow(StockSomethingElse())

    assert refusal.value.event_class == "StockSomethingElse"
    assert narrow(reserved()) == reserved()
