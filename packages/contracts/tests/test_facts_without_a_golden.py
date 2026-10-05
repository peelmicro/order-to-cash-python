"""`stock.rejected.v1` and `order.saga_failed.v1` have no real wire envelope (none was captured).

These two fixtures are written by hand from `specs/shared/asyncapi.yaml`. They are shape tests, not
parity evidence: their byte-parity with real #7 output is unproven (disclosed in the report).
"""

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from otc_contracts import UnknownFactTypeError, parse_fact, to_wire_json
from otc_contracts.generated.asyncapi import OrderSagaFailedEvent, StockRejectedEvent


def _load() -> Callable[..., list[str]]:
    spec = importlib.util.spec_from_file_location(
        "otc_contracts_tests_strict_json_2", Path(__file__).with_name("strict_json.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    comparer: Callable[..., list[str]] = module.strict_json_differences
    return comparer


strict_json_differences = _load()
HEAD = (
    '{"eventId":"0b8f8a52-2a5a-4c55-9a43-3d6f3f6a1111","eventType":"%s",'
    '"aggregateId":"c4c18255-fda7-4dd0-8a07-450db7ca6304",'
    '"correlationId":"c4c18255-fda7-4dd0-8a07-450db7ca6304",'
    '"causationId":"bfffaa90-77f8-4196-bc39-8f6a50f4a406",'
    '"occurredAt":"2026-08-30T16:20:20.442Z","payload":%s}'
)
STOCK_REJECTED = HEAD % (
    "stock.rejected.v1",
    '{"orderReference":"ORD-000011","companyCode":"PORTOTOOLS","retailerCode":"LeroyMerlinEs",'
    '"shortages":[{"productCode":"PRD-0008","requested":6,"available":2}],'
    '"reason":"insufficient_stock"}',
)
SAGA_FAILED = HEAD % (
    "order.saga_failed.v1",
    '{"orderReference":"ORD-000011","command":"stock.reserve","attempts":3,'
    '"lastError":"timeout","failedAt":"2026-08-30T16:20:25.442Z"}',
)


def test_stock_rejected_parses_round_trips_and_keeps_the_envelope_bytes() -> None:
    event = parse_fact(STOCK_REJECTED)
    assert isinstance(event, StockRejectedEvent)
    assert event.payload.shortages[0].available == 2
    written = to_wire_json(event)
    assert written.split(',"payload":')[0] == STOCK_REJECTED.split(',"payload":')[0]
    assert strict_json_differences(json.loads(STOCK_REJECTED), json.loads(written)) == []


def test_stock_rejected_without_the_optional_retailer_code_omits_it() -> None:
    document = json.loads(STOCK_REJECTED)
    del document["payload"]["retailerCode"]
    text = json.dumps(document, separators=(",", ":"))
    written = to_wire_json(parse_fact(text))
    assert "retailerCode" not in written
    assert strict_json_differences(document, json.loads(written)) == []


def test_order_saga_failed_parses_round_trips_and_keeps_the_envelope_bytes() -> None:
    event = parse_fact(SAGA_FAILED)
    assert isinstance(event, OrderSagaFailedEvent)
    assert event.payload.attempts == 3
    written = to_wire_json(event)
    assert written.split(',"payload":')[0] == SAGA_FAILED.split(',"payload":')[0]
    assert strict_json_differences(json.loads(SAGA_FAILED), json.loads(written)) == []


def test_an_unregistered_event_type_is_refused_with_a_stable_code() -> None:
    with pytest.raises(UnknownFactTypeError) as raised:
        parse_fact(STOCK_REJECTED.replace("stock.rejected.v1", "stock.exploded.v1"))
    assert raised.value.code == "fact.unknown_type"
    with pytest.raises(UnknownFactTypeError):
        parse_fact("[]")
