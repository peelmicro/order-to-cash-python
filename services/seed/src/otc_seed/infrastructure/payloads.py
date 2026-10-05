"""The outbox payload text: validated against the generated contract, written by the one serializer.

A seeded payload is a plain wire-shaped dict from the domain. Before it reaches a `json` column it
is parsed into the contract's payload model for its event type (so a payload the contract would
refuse, a wrong reference pattern, a float, a missing field, fails the seed instead of a consumer
five phases later) and written by `otc_contracts.wire.to_wire_json`: compact separators, non-ASCII
raw, camelCase, instants as `YYYY-MM-DDTHH:MM:SS.mmmZ`. There is no second serializer
configuration here. The payload model of an event type is the annotation of the `payload` field of
that type's registered envelope model, so a fact registered in the contracts needs no second list.

`json.dumps` below only carries the dict into `from_wire_json` (a parse); the bytes that are stored
come from `to_wire_json`.
"""

import json
from collections.abc import Mapping
from typing import Any

from otc_contracts import FACT_MODELS, WireModel, from_wire_json, to_wire_json


def payload_model(event_type: str) -> type[WireModel]:
    annotation = FACT_MODELS[event_type].model_fields["payload"].annotation
    if not (isinstance(annotation, type) and issubclass(annotation, WireModel)):
        raise TypeError(f"the payload of {event_type} is not a wire model: {annotation!r}")
    return annotation


def payload_json(event_type: str, payload: Mapping[str, Any]) -> str:
    model = from_wire_json(
        payload_model(event_type),
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False),
    )
    return to_wire_json(model)
