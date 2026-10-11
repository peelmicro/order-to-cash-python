"""The projector's fact builders: one per fact, every field settable (I1).

They live here, in the service's `conftest.py`, exposed as the `facts` fixture, not in a
`tests/support/facts.py` as `tasks.md` I1 first worded it: pytest runs in `--import-mode=importlib`
and `mypy` resolves test files by path, so a sibling module is importable by neither without a
change to the root `pyproject.toml` (not this feature's to make). Notifications' `conftest.py`
(`facts` fixture) is the precedent.

Defaults are chosen so that no two values in one envelope are equal and no id of the four
(`eventId`, `aggregateId`, `correlationId`, `causationId`) repeats within or across envelopes (#8 id
60); `test_fact_builders.py` asserts it over the whole population. A test that needs a SPECIFIC
value passes it (`facts.build(type, payload={...}, correlation_id=...)`), so the default can never
satisfy an assertion's relation by accident.

Loop scope: nothing here is async.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic.alias_generators import to_camel

from otc_contracts import FACT_MODELS, FactEvent, format_instant, from_wire_json, to_wire_json
from otc_contracts.wire import WireModel


def uid(number: int) -> UUID:
    """A UUID whose text differs from every other `uid` in more than one position."""
    return UUID(f"{number:08x}-{number % 0xFFFF:04x}-4000-8000-{number * 7919:012x}")


def at(day: int, hour: int, millisecond: int) -> datetime:
    return datetime(2026, 3, day, hour, 10 + day % 40, 20 + hour, millisecond * 1000, tzinfo=UTC)


def _payloads() -> dict[str, dict[str, Any]]:
    return {
        "order.placed.v1": {
            "order_reference": "ORD-000101",
            "retailer_code": "ACME",
            "company_code": "GLOBEX",
            "buyer_gln": "8412345678905",
            "supplier_gln": "2022222222227",
            "currency": "EUR",
            "order_date": at(4, 5, 123),
            "lines": [
                {
                    "product_code": "WIDGET-A1",
                    "description": "alpha",
                    "quantity": 3,
                    "unit_price": 1111,
                    "line_discount": 11,
                },
                {
                    "product_code": "WIDGET-A2",
                    "description": "beta",
                    "quantity": 4,
                    "unit_price": 2222,
                    "line_discount": 22,
                },
            ],
            "initial_amount": 130007,
            "initial_discount": 5753,
            "total_amount": 124254,
        },
        "stock.reserved.v1": {
            "order_reference": "ORD-000102",
            "company_code": "INITECH",
            "reservations": [
                {"reservation_id": uid(8001), "product_code": "WIDGET-A1", "units": 3},
                {"reservation_id": uid(8002), "product_code": "WIDGET-A2", "units": 4},
            ],
        },
        "stock.rejected.v1": {
            "order_reference": "ORD-000103",
            "company_code": "UMBRELLA",
            "shortages": [
                {"product_code": "WIDGET-S1", "requested": 9, "available": 2},
                {"product_code": "WIDGET-S2", "requested": 5, "available": 1},
            ],
            "reason": "insufficient_stock",
        },
        "stock.released.v1": {
            "order_reference": "ORD-000104",
            "company_code": "HOOLI",
            "released": [
                {"reservation_id": uid(8003), "product_code": "WIDGET-R1", "units": 6},
                {"reservation_id": uid(8004), "product_code": "WIDGET-R2", "units": 7},
            ],
            "reason": "order_cancelled",
        },
        "credit.approved.v1": {
            "order_reference": "ORD-000105",
            "retailer_code": "BIGMART",
            "company_code": "STARK",
            "credit_code": "CR-000201",
            "currency": "EUR",
            "held_amount": 9245,
            "available_credit_after": 875751,
        },
        "credit.rejected.v1": {
            "order_reference": "ORD-000106",
            "retailer_code": "MEGACO",
            "company_code": "WAYNE",
            "currency": "JPY",
            "requested_amount": 5000,
            "available_credit": 100,
            "reason": "over_limit",
        },
        "credit.released.v1": {
            "order_reference": "ORD-000107",
            "retailer_code": "CORNERSHOP",
            "company_code": "PULL",
            "currency": "KWD",
            "released_amount": 12345,
            "available_credit_after": 1000003,
            "reason": "invoice_paid",
        },
        "order.confirmed.v1": {
            "order_reference": "ORD-000108",
            "retailer_code": "LIDL",
            "company_code": "ZARA",
            "currency": "GBP",
            "total_amount": 654321,
            "confirmed_at": at(5, 6, 234),
        },
        "order.despatched.v1": {
            "order_reference": "ORD-000109",
            "despatch_reference": "DES-000203",
            "despatch_date": at(6, 7, 345),
            "company_code": "MANGO",
            "retailer_code": "ALDI",
            "lines": [
                {"product_code": "GADGET-A1", "units": 2},
                {"product_code": "GADGET-A2", "units": 5},
            ],
        },
        "invoice.issued.v1": {
            "order_reference": "ORD-000110",
            "invoice_reference": "INV-000304",
            "invoice_date": at(7, 8, 456),
            "retailer_code": "AUCHAN",
            "company_code": "DESIGUAL",
            "currency": "CHF",
            "lines": [
                {"product_code": "PART-A1", "units": 2, "unit_price": 3331},
                {"product_code": "PART-A2", "units": 5, "unit_price": 4442},
            ],
            "amount": 777001,
            "discount": 17003,
            "total_amount": 760002,
        },
        "payment.received.v1": {
            "order_reference": "ORD-000111",
            "invoice_reference": "INV-000305",
            "payment_reference": "PAY-A-5001",
            "currency": "USD",
            "amount": 116667,
            "value_date": at(8, 9, 567),
            "source": "operator",
        },
        "order.completed.v1": {
            "order_reference": "ORD-000112",
            "retailer_code": "SHOPRITE",
            "company_code": "BERSHKA",
            "currency": "CAD",
            "total_amount": 987650,
            "completed_at": at(9, 10, 678),
        },
        "order.cancelled.v1": {
            "order_reference": "ORD-000113",
            "retailer_code": "FOODCO",
            "company_code": "MASSIMO",
            "cancellation_reason": "credit_rejected",
            "cancelled_at": at(10, 11, 789),
            "compensation_steps": [
                {
                    "step": "stock_released",
                    "event_id": uid(7101),
                    "event_type": "stock.released.v1",
                    "occurred_at": at(11, 12, 899),
                    "summary": "released stock",
                }
            ],
        },
        "order.saga_failed.v1": {
            "order_reference": "ORD-000114",
            "command": "reserve_stock",
            "attempts": 5,
            "last_error": "connection refused",
            "failed_at": at(12, 12, 345),
        },
    }


def wire_document(value: Any) -> Any:
    """Constructor-style data as the camelCase JSON document the wire carries."""
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
class FactBuilders:
    def event_types(self) -> list[str]:
        return list(_payloads())

    def data(self, event_type: str, **envelope: Any) -> dict[str, Any]:
        """The fact as constructor keyword arguments (snake_case, python values)."""
        index = list(FACT_MODELS).index(event_type) + 1
        base = index * 100
        data: dict[str, Any] = {
            "event_id": uid(base + 1),
            "aggregate_id": uid(base + 2),
            "correlation_id": uid(base + 3),
            "causation_id": uid(base + 4),
            "event_type": event_type,
            "occurred_at": at(2, 3 + index, 100 + index),
            "payload": _payloads()[event_type],
        }
        payload_override = envelope.pop("payload", None)
        data.update(envelope)
        if payload_override:
            data["payload"] = {**data["payload"], **payload_override}
        return data

    def build(self, event_type: str, **envelope: Any) -> FactEvent:
        """The typed event, validated by its generated model. `payload=` overrides payload keys."""
        return self.from_data(event_type, self.data(event_type, **envelope))

    def from_data(self, event_type: str, data: dict[str, Any]) -> FactEvent:
        model: type[WireModel] = FACT_MODELS[event_type]
        parsed: FactEvent = from_wire_json(model, json.dumps(wire_document(data)))  # type: ignore[assignment]
        return parsed

    def wire(self, event: WireModel) -> bytes:
        """The fact exactly as the producer writes it: compact camelCase JSON."""
        return to_wire_json(event).encode("utf-8")


@pytest.fixture(scope="session")
def facts() -> FactBuilders:
    return FactBuilders()
