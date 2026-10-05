"""Feature 8 acceptance items 3, 4 and 5 against the 12 golden envelopes copied from #8.

* ENVELOPE byte-exact (field set, order, value formatting): everything before the `payload` value.
* PAYLOAD semantically equal: object key order immaterial (MySQL `json` normalised it on #7's wire,
  CLAUDE.md), array order significant, and TYPES strict: Python's `==` makes `1 == 1.0 == True`, so
  the comparer below checks `type(...)` itself and is proven against sentinels.
* ROUND-TRIP: every golden parses into the generated models by `eventType` and re-serialises to a
  semantically equal document.
"""

import hashlib
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from otc_contracts import FACT_MODELS, from_wire_json, parse_fact, to_wire_json
from otc_contracts.generated.asyncapi import (
    CreditApprovedEvent,
    CreditRejectedEvent,
    OrderPlacedEvent,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "golden_envelopes"
ENVELOPE_KEYS = [
    "eventId",
    "eventType",
    "aggregateId",
    "correlationId",
    "causationId",
    "occurredAt",
    "payload",
]
# SHA-256 of the committed bytes, pinned: `cmp` against
# ../order-to-cash-dotnet/tests/Contracts.UnitTests/GoldenEnvelopes/ was identical at copy time.
PINNED_SHA256: dict[str, str] = {
    "credit_approved_v1.json": "caf80c98b5cc803f25be0dd0738836952c9b9ad79e6dc0ffadc0ab0801e5f929",
    "credit_rejected_v1.json": "1121410acff56b21920945ec3db3ea6e60c4527806696f5ad632482e1369a575",
    "credit_released_v1.json": "561dacf30309ef261c900fa5360698b3d4f271a4687b5a8d3d2e9f23568cd2a8",
    "invoice_issued_v1.json": "85d1f29411112a743de2346d41dd2e1cc24ddfca54d956e0b6a3dfde50ad5ed0",
    "order_cancelled_v1.json": "f8b1eed126d8404f3ea09ec3df058a143270f08bbe7882561fcfd4e0b874f012",
    "order_completed_v1.json": "1a42f8f0481992a188cc1b20df6308df800d7fb0f932b6a97f39fd7ab6d64cc5",
    "order_confirmed_v1.json": "1e171c341ee4e4b6fc3878c11c9b75d35ebdaeff5aa1e3aa2e494523941e03c5",
    "order_despatched_v1.json": "885e6a8016c4a5761afbf8803f4e94ac3fbc4c21cea8b4810af779ca7b3b6674",
    "order_placed_v1.json": "683e9ca0a95d083f0db7c328a5b075f45ae43846c76e916a05c0475e064913d3",
    "payment_received_v1.json": "0bc152d16d2530fc3fab53aa52ee57fc0eb6222420e958873146c32368a487d2",
    "stock_released_v1.json": "52378063ce7abf354511413eb4300f39f55caa81ddd7c12f0de92f32eb66d7b1",
    "stock_reserved_v1.json": "367480567c464aac0145cd024a11b48dd0ecfdeb452e5bf3693405e8e545441e",
}


def _load_strict_json() -> Any:
    spec = importlib.util.spec_from_file_location(
        "otc_contracts_tests_strict_json", Path(__file__).with_name("strict_json.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


strict_json_differences: Callable[..., list[str]] = _load_strict_json().strict_json_differences


def golden_text(name: str) -> str:
    return (GOLDEN_DIR / name).read_bytes().decode("utf-8")


def split_at_payload(text: str) -> tuple[str, str]:
    """`(bytes before the payload value, the payload value's text)` of a compact envelope."""
    marker = ',"payload":'
    head, _, rest = text.partition(marker)
    assert rest.endswith("}"), "the payload is the last envelope field"
    return head, rest[:-1]


GOLDEN_FILES = sorted(p.name for p in GOLDEN_DIR.glob("*.json"))


# --------------------------------------------------------------------------- the comparer itself
@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        (8934, 8934.0),
        (8934, True),
        (1, True),
        (0, False),
        (8934, "8934"),
        (None, 0),
        ("", None),
        ({"a": 8934}, {"a": 8934.0}),
        ([8934], [True]),
        ({"a": [{"b": 1}]}, {"a": [{"b": 1.0}]}),
        ({"a": 1}, {"a": 1, "b": 2}),
        ({"a": 1, "b": 2}, {"a": 1}),
        ({"a": None}, {}),
        ([1, 2], [2, 1]),
        ([1], [1, 1]),
        (1.0, 1),
    ],
)
def test_the_payload_comparer_sees_a_difference(expected: Any, actual: Any) -> None:
    """Sentinels: each pair is `==` in Python or differs only by order/type, and must be flagged."""
    assert strict_json_differences(expected, actual), f"{expected!r} vs {actual!r} was not flagged"


def test_the_payload_comparer_ignores_object_key_order_at_every_depth() -> None:
    first = {"a": 1, "b": {"c": [1, {"x": 1, "y": 2}], "d": "é"}}
    second = {"b": {"d": "é", "c": [1, {"y": 2, "x": 1}]}, "a": 1}
    assert strict_json_differences(first, second) == []


def test_python_equality_alone_cannot_see_the_differences_the_comparer_sees() -> None:
    """Why the comparer exists: `json.loads(a) == json.loads(b)` equates all three."""
    assert json.loads("[1]") == json.loads("[1.0]") == json.loads("[true]")
    assert json.loads('{"a":8934}') == json.loads('{"a":8934.0}')


# ------------------------------------------------------------------------------- the golden set
def test_the_twelve_golden_envelope_files_are_exactly_these() -> None:
    assert set(GOLDEN_FILES) == {
        "credit_approved_v1.json",
        "credit_rejected_v1.json",
        "credit_released_v1.json",
        "invoice_issued_v1.json",
        "order_cancelled_v1.json",
        "order_completed_v1.json",
        "order_confirmed_v1.json",
        "order_despatched_v1.json",
        "order_placed_v1.json",
        "payment_received_v1.json",
        "stock_released_v1.json",
        "stock_reserved_v1.json",
    }
    assert len(GOLDEN_FILES) == 12


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_a_golden_envelope_has_the_envelope_keys_in_spec_order(name: str) -> None:
    keys = list(json.loads(golden_text(name)).keys())
    assert keys == ENVELOPE_KEYS


# ---------------------------------------------------------------- acceptance 3: envelope exact
@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_envelope_is_byte_exact_against_the_golden(name: str) -> None:
    golden = golden_text(name)
    reserialised = to_wire_json(parse_fact(golden))
    golden_head, _ = split_at_payload(golden)
    actual_head, _ = split_at_payload(reserialised)
    assert actual_head.encode("utf-8") == golden_head.encode("utf-8")


# ------------------------------------------------------------- acceptance 4: payload semantic
@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_payload_is_semantically_equal_to_the_golden(name: str) -> None:
    golden = json.loads(golden_text(name))
    actual = json.loads(to_wire_json(parse_fact(golden_text(name))))
    assert strict_json_differences(golden["payload"], actual["payload"], "$.payload") == []


# ------------------------------------------------------------------ acceptance 5: round trip
@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_round_trip_every_golden_parses_into_its_model_and_reserialises_equal(name: str) -> None:
    text = golden_text(name)
    event_type = json.loads(text)["eventType"]
    event = parse_fact(text)
    assert type(event) is FACT_MODELS[event_type], f"{name} parsed as {type(event).__name__}"
    again = to_wire_json(event)
    assert strict_json_differences(json.loads(text), json.loads(again)) == []
    # and the second generation is stable: parse -> write -> parse -> write is a fixed point
    assert to_wire_json(parse_fact(again)) == again


def test_a_golden_parses_to_the_values_the_file_literally_holds() -> None:
    """Not circular: literals read off `order_placed_v1.json`, not produced by the serializer."""
    event = parse_fact(golden_text("order_placed_v1.json"))
    assert isinstance(event, OrderPlacedEvent)
    assert str(event.event_id) == "ac6e7c85-2c32-4c6b-ae9a-83336843e412"
    assert event.payload.total_amount == 8934
    assert event.payload.lines[0].quantity == 6
    assert event.payload.lines[0].unit_price == 1489
    assert event.payload.order_reference == "ORD-000011"


def test_the_non_ascii_golden_is_written_raw_not_escaped() -> None:
    text = golden_text("order_cancelled_v1.json")
    assert "—" in text, "this golden is the non-ASCII fixture; it must still contain the em dash"
    written = to_wire_json(parse_fact(text))
    assert "—" in written
    assert "\\u" not in written


# ------------------------------------------------------- substituted sibling eventType (row 3)
def test_a_credit_approved_envelope_is_refused_by_the_credit_rejected_model() -> None:
    approved = golden_text("credit_approved_v1.json")
    with pytest.raises(ValueError, match=r"credit\.rejected\.v1"):
        from_wire_json(CreditRejectedEvent, approved)
    assert isinstance(from_wire_json(CreditApprovedEvent, approved), CreditApprovedEvent)


def test_every_golden_relabelled_with_a_sibling_event_type_is_refused() -> None:
    """Dispatch is by `eventType`, never by payload shape: 12 goldens x 11 sibling labels."""
    event_types = {n: json.loads(golden_text(n))["eventType"] for n in GOLDEN_FILES}
    accepted: list[str] = []
    for name in GOLDEN_FILES:
        for sibling in sorted(set(event_types.values()) - {event_types[name]}):
            document = json.loads(golden_text(name))
            document["eventType"] = sibling
            try:
                parse_fact(json.dumps(document))
            except ValueError:  # pydantic.ValidationError is a ValueError
                continue
            accepted.append(f"{name} accepted as {sibling}")
    assert accepted == []


def test_the_golden_bytes_are_pinned() -> None:
    """A corrupted golden value would still round-trip (the model re-serialises what it parsed);
    the bytes are what must not move, so each file's SHA-256 is pinned."""
    digests = {n: hashlib.sha256((GOLDEN_DIR / n).read_bytes()).hexdigest() for n in GOLDEN_FILES}
    moved = sorted(n for n in PINNED_SHA256 if digests.get(n) != PINNED_SHA256[n])
    assert moved == [], f"golden bytes changed (copied from #8, must be immutable): {moved}"
    assert set(digests) == set(PINNED_SHA256)
