"""otc-contracts: wire models generated from the specs, and the one serializer configuration."""

from otc_contracts.facts import FACT_MODELS, FactEvent, UnknownFactTypeError, parse_fact
from otc_contracts.wire import WireModel, format_instant, from_wire_json, to_wire_json

__all__ = [
    "FACT_MODELS",
    "FactEvent",
    "UnknownFactTypeError",
    "WireModel",
    "format_instant",
    "from_wire_json",
    "parse_fact",
    "to_wire_json",
]
