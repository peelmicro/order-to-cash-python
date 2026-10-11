"""The Notifications fact fixtures: the seven notified facts and the seven that are not.

`facts.event("order.placed.v1")` is variant A and `facts.event(..., variant="B")` is variant B: the
SAME shape with EVERY value different. They exist for two reasons.

1. FIXTURES MUST NOT SATISFY AN ASSERTION'S RELATION BY ACCIDENT (Phase 10 `billing_credit` D1; #8
   ids 58, 59 and 60). Within one fixture no two scalar values are equal, and no string value
   contains another (#8's `OrderCancelledTemplate.cs:16` survivor was a PREFIX collision:
   `"credit.release"` inside `"credit.released.v1"`); `test_fact_fixtures_do_not_collide.py` proves
   both over the whole population of leaf values, envelope included.
2. Variant B is the "plausible wrong value" supplier of `test_template_payload_sites.py`: replacing
   ONE leaf of A with B's value must change the rendered message exactly when that leaf is rendered.

Instants carry a non-zero millisecond and differ from one another, from the envelope's
`occurredAt` and from the wire text of any other field. Money amounts are integer minor units in
currencies of different exponents (A: EUR 2, JPY 0, KWD 3, USD 2; B has other codes).

Loop scope: nothing here is async.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic.alias_generators import to_camel

from otc_contracts import FACT_MODELS, format_instant, from_wire_json, to_wire_json
from otc_contracts.wire import WireModel

NOTIFIED_TYPES = (
    "order.placed.v1",
    "order.confirmed.v1",
    "order.despatched.v1",
    "invoice.issued.v1",
    "payment.received.v1",
    "order.completed.v1",
    "order.cancelled.v1",
)
NOT_NOTIFIED_TYPES = (
    "stock.reserved.v1",
    "stock.rejected.v1",
    "stock.released.v1",
    "credit.approved.v1",
    "credit.rejected.v1",
    "credit.released.v1",
    "order.saga_failed.v1",
)


def uid(number: int) -> UUID:
    """A UUID whose text differs from every other `uid` in more than one position."""
    return UUID(f"{number:08x}-{number % 0xFFFF:04x}-4000-8000-{number * 7919:012x}")


def at(day: int, hour: int, millisecond: int) -> datetime:
    return datetime(2026, 3, day, hour, 10 + day % 40, 20 + hour, millisecond * 1000, tzinfo=UTC)


# variant -> eventType -> (envelope ids offset, payload)
def _payloads(variant: str) -> dict[str, dict[str, Any]]:
    b = variant == "B"
    return {
        "order.placed.v1": {
            "order_reference": "ORD-000902" if b else "ORD-000101",
            "retailer_code": "TESCO" if b else "ACME",
            "company_code": "INDITEX" if b else "GLOBEX",
            "buyer_gln": "5012345678900" if b else "8412345678905",
            "supplier_gln": "3012345678903" if b else "2022222222227",
            "currency": "GBP" if b else "EUR",
            "order_date": at(14, 7, 811) if b else at(4, 5, 123),
            "lines": [
                {
                    "product_code": "WIDGET-B1" if b else "WIDGET-A1",
                    "description": "bolt" if b else "alpha",
                    "quantity": 8 if b else 3,
                    "unit_price": 7771 if b else 1111,
                    "line_discount": 77 if b else 11,
                },
                {
                    "product_code": "WIDGET-B2" if b else "WIDGET-A2",
                    "description": "cog" if b else "beta",
                    "quantity": 9 if b else 4,
                    "unit_price": 8882 if b else 2222,
                    "line_discount": 88 if b else 22,
                },
            ],
            "initial_amount": 330000 if b else 130000,
            "initial_discount": 9750 if b else 5750,
            "total_amount": 654321 if b else 124250,
        },
        "order.confirmed.v1": {
            "order_reference": "ORD-000903" if b else "ORD-000102",
            "retailer_code": "CARREFOUR" if b else "BIGMART",
            "company_code": "ZARA" if b else "INITECH",
            "currency": "CLP" if b else "JPY",
            "total_amount": 8765432 if b else 5000,
            "confirmed_at": at(15, 8, 822) if b else at(5, 6, 234),
        },
        "order.despatched.v1": {
            "order_reference": "ORD-000904" if b else "ORD-000103",
            "despatch_reference": "DES-000904" if b else "DES-000203",
            "despatch_date": at(16, 9, 833) if b else at(6, 7, 345),
            "company_code": "MANGO" if b else "UMBRELLA",
            "retailer_code": "LIDL" if b else "MEGACO",
            "lines": [
                {"product_code": "GADGET-B1" if b else "GADGET-A1", "units": 6 if b else 2},
                {"product_code": "GADGET-B2" if b else "GADGET-A2", "units": 7 if b else 5},
            ],
        },
        "invoice.issued.v1": {
            "order_reference": "ORD-000905" if b else "ORD-000104",
            "invoice_reference": "INV-000905" if b else "INV-000304",
            "invoice_date": at(17, 10, 844) if b else at(7, 8, 456),
            "retailer_code": "ALDI" if b else "CORNERSHOP",
            "company_code": "DESIGUAL" if b else "HOOLI",
            "currency": "BHD" if b else "KWD",
            "lines": [
                {
                    "product_code": "PART-B1" if b else "PART-A1",
                    "units": 6 if b else 2,
                    "unit_price": 4441 if b else 3331,
                },
                {
                    "product_code": "PART-B2" if b else "PART-A2",
                    "units": 7 if b else 5,
                    "unit_price": 5552 if b else 4442,
                },
            ],
            "amount": 777000 if b else 123456,
            "discount": 17000 if b else 6789,
            "total_amount": 760000 if b else 116667,
        },
        "payment.received.v1": {
            "order_reference": "ORD-000906" if b else "ORD-000105",
            "invoice_reference": "INV-000906" if b else "INV-000305",
            "payment_reference": "PAY-B-6001" if b else "PAY-A-5001",
            "currency": "CHF" if b else "EUR",
            "amount": 999999 if b else 116667,
            "value_date": at(18, 11, 855) if b else at(8, 9, 567),
            "source": "robot" if b else "operator",
        },
        "order.completed.v1": {
            "order_reference": "ORD-000907" if b else "ORD-000106",
            "retailer_code": "AUCHAN" if b else "SHOPRITE",
            "company_code": "PULL" if b else "WAYNE",
            "currency": "CAD" if b else "USD",
            "total_amount": 456789 if b else 987650,
            "completed_at": at(19, 12, 866) if b else at(9, 10, 678),
        },
        "order.cancelled.v1": {
            "order_reference": "ORD-000908" if b else "ORD-000107",
            "retailer_code": "MIGROS" if b else "FOODCO",
            "company_code": "BERSHKA" if b else "STARK",
            "cancellation_reason": "operator_cancelled" if b else "credit_rejected",
            "cancelled_at": at(20, 13, 877) if b else at(10, 11, 789),
            "compensation_steps": [
                {
                    "step": "credit_released" if b else "stock_released",
                    "event_id": uid(7001 if b else 7101),
                    "event_type": "credit.released.v1" if b else "stock.released.v1",
                    "occurred_at": at(21 if b else 11, 14, 188 if b else 899),
                    "summary": "released credit" if b else "released stock",
                },
                {
                    "step": "stock_released" if b else "credit_released",
                    "event_id": uid(7002 if b else 7102),
                    "event_type": "stock.released.v1" if b else "credit.released.v1",
                    "occurred_at": at(22 if b else 12, 15, 299 if b else 911),
                    "summary": "released stock again" if b else "released credit again",
                },
            ],
            "note": "operator note B" if b else "operator note A",
        },
    }


# The seven facts that are NOT notified: valid minimal payloads, so a test can feed the consumer a
# well-formed fact that must still produce nothing.
def _other_payloads() -> dict[str, dict[str, Any]]:
    return {
        "stock.reserved.v1": {
            "order_reference": "ORD-000111",
            "company_code": "GLOBEX",
            "reservations": [
                {"reservation_id": uid(8001), "product_code": "WIDGET-A1", "units": 3}
            ],
        },
        "stock.rejected.v1": {
            "order_reference": "ORD-000112",
            "company_code": "GLOBEX",
            "shortages": [{"product_code": "WIDGET-A1", "requested": 5, "available": 1}],
            "reason": "insufficient_stock",
        },
        "stock.released.v1": {
            "order_reference": "ORD-000113",
            "company_code": "GLOBEX",
            "released": [{"reservation_id": uid(8003), "product_code": "WIDGET-A1", "units": 3}],
            "reason": "order_cancelled",
        },
        "credit.approved.v1": {
            "order_reference": "ORD-000114",
            "retailer_code": "ACME",
            "company_code": "GLOBEX",
            "credit_code": "CR-000001",
            "held_amount": 124250,
            "currency": "EUR",
            "available_credit_after": 875750,
        },
        "credit.rejected.v1": {
            "order_reference": "ORD-000115",
            "retailer_code": "ACME",
            "company_code": "GLOBEX",
            "requested_amount": 124250,
            "currency": "EUR",
            "available_credit": 100,
            "reason": "over_limit",
        },
        "credit.released.v1": {
            "order_reference": "ORD-000116",
            "retailer_code": "ACME",
            "company_code": "GLOBEX",
            "released_amount": 124250,
            "currency": "EUR",
            "available_credit_after": 1000000,
            "reason": "invoice_paid",
        },
        "order.saga_failed.v1": {
            "order_reference": "ORD-000117",
            "command": "reserve_stock",
            "attempts": 5,
            "last_error": "boom",
            "failed_at": at(12, 12, 345),
        },
    }


def wire_document(value: Any) -> Any:
    """Constructor-style data as the camelCase JSON document the wire carries (enums stay text,
    which is how the strict generated models take them)."""
    if isinstance(value, dict):
        return {to_camel(key): wire_document(item) for key, item in value.items()}
    if isinstance(value, list):
        return [wire_document(item) for item in value]
    if isinstance(value, datetime):
        return format_instant(value)
    if isinstance(value, UUID):
        return str(value)
    return value


@dataclass(frozen=True, slots=True)
class FactFixtures:
    def envelope_ids(self, event_type: str, variant: str) -> dict[str, UUID]:
        base = (list(FACT_MODELS).index(event_type) + 1) * 100 + (50 if variant == "B" else 0)
        return {
            "event_id": uid(base + 1),
            "aggregate_id": uid(base + 2),
            "correlation_id": uid(base + 3),
            "causation_id": uid(base + 4),
        }

    def event_dict(self, event_type: str, variant: str = "A") -> dict[str, Any]:
        """The fact as constructor keyword arguments (snake_case, python values)."""
        payloads = {**_payloads(variant), **_other_payloads()}
        index = list(FACT_MODELS).index(event_type)
        return {
            **self.envelope_ids(event_type, variant),
            "event_type": event_type,
            "occurred_at": at(25 if variant == "B" else 2, 3 + index, 100 + index),
            "payload": payloads[event_type],
        }

    def event(self, event_type: str, variant: str = "A") -> Any:
        """The typed event (`OrderPlacedEvent`, ...), validated by its generated model."""
        return self.event_from(event_type, self.event_dict(event_type, variant))

    def event_from(self, event_type: str, data: dict[str, Any]) -> Any:
        """Parse constructor-style data through the wire (the strict model takes enums as text
        only from JSON)."""
        model: type[WireModel] = FACT_MODELS[event_type]
        return from_wire_json(model, json.dumps(wire_document(data)))

    def wire(self, event_type: str, variant: str = "A") -> bytes:
        """The fact exactly as the producer writes it: compact camelCase JSON."""
        return to_wire_json(self.event(event_type, variant)).encode("utf-8")

    def wire_from(self, event: WireModel) -> bytes:
        return to_wire_json(event).encode("utf-8")

    def with_values(self, event_type: str, **envelope: Any) -> Any:
        """Variant A with some envelope fields replaced (an `eventId` to redeliver, ...)."""
        data = self.event_dict(event_type)
        data.update(envelope)
        return self.event_from(event_type, data)


@pytest.fixture(scope="session")
def facts() -> FactFixtures:
    return FactFixtures()


@pytest.fixture(scope="session")
def parsed() -> Callable[[bytes], dict[str, Any]]:
    def parse(data: bytes) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(data)
        return loaded

    return parse


class InMemoryLedger:
    """The `DeliveryLedger` port in memory: a set of event ids and a call log."""

    def __init__(self) -> None:
        self.recorded: set[UUID] = set()
        self.calls: list[tuple[str, UUID]] = []
        self.forget_error: Exception | None = None

    async def record(self, event_id: UUID) -> Any:
        from otc_notifications.application.ports.delivery_ledger import LedgerOutcome

        self.calls.append(("record", event_id))
        if event_id in self.recorded:
            return LedgerOutcome.DUPLICATE
        self.recorded.add(event_id)
        return LedgerOutcome.RECORDED

    async def forget(self, event_id: UUID) -> None:
        self.calls.append(("forget", event_id))
        if self.forget_error is not None:
            raise self.forget_error
        self.recorded.discard(event_id)


class RecordingSender:
    """The `NotificationSender` port, recording every message; `failures` are raised in order."""

    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.failures: list[BaseException] = []

    async def send(self, message: Any) -> None:
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(message)


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()
