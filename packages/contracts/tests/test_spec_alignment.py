"""The generated models against `specs/shared/*.yaml`, read at TEST time (not baked in).

Feature 8 acceptance item 1 (generation) is guarded by the drift tests; this file proves the other
direction: that what was generated, and the hand-written registry, still say what the spec says. A
spec edit with no regeneration fails here as well as in the drift check.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from otc_contracts import FACT_MODELS
from otc_contracts.generated import asyncapi, openapi
from otc_contracts.generated.nullable import NULLABLE_FIELDS
from otc_contracts.wire import WireModel

REPO_ROOT = Path(__file__).resolve().parents[3]
EXCLUDED_HEADER_SCHEMAS = {"FactHeaders", "DeadLetterHeaders", "RpcHeaders"}
# The two facts for which #8's capture has no real wire envelope (#7's retained topics held none).
FACTS_WITHOUT_A_GOLDEN = {"stock.rejected.v1", "order.saga_failed.v1"}
GOLDEN_EVENT_TYPES = {
    "credit.approved.v1",
    "credit.rejected.v1",
    "credit.released.v1",
    "invoice.issued.v1",
    "order.cancelled.v1",
    "order.completed.v1",
    "order.confirmed.v1",
    "order.despatched.v1",
    "order.placed.v1",
    "payment.received.v1",
    "stock.released.v1",
    "stock.reserved.v1",
}


def load_schemas(name: str) -> dict[str, Any]:
    spec = yaml.safe_load((REPO_ROOT / "specs" / "shared" / f"{name}.yaml").read_text("utf-8"))
    schemas: dict[str, Any] = spec["components"]["schemas"]
    return schemas


ASYNC = load_schemas("asyncapi")
OPEN = load_schemas("openapi")
MODULES: dict[str, Any] = {"asyncapi": asyncapi, "openapi": openapi}
SPECS = {"asyncapi": ASYNC, "openapi": OPEN}


def resolve(schemas: dict[str, Any], schema: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """`(properties, required)` of a schema, merging `allOf` parts left to right (a later part
    replaces an earlier property of the same name, as an override does)."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for part in schema.get("allOf", []):
        target = schemas[part["$ref"].rsplit("/", 1)[-1]] if "$ref" in part else part
        sub_props, sub_required = resolve(schemas, target)
        properties.update(sub_props)
        required.extend(sub_required)
    properties.update(schema.get("properties", {}))
    required.extend(schema.get("required", []))
    return properties, required


def event_schemas() -> dict[str, str]:
    """`{schema name: eventType const}` for every `*Event` schema in asyncapi.yaml."""
    found: dict[str, str] = {}
    for name, schema in ASYNC.items():
        if name.endswith("Event"):
            properties, _ = resolve(ASYNC, schema)
            found[name] = properties["eventType"]["const"]
    return found


def wire_aliases(model: type[BaseModel]) -> list[str]:
    return [field.alias or name for name, field in model.model_fields.items()]


def object_schema_names(module: str) -> list[str]:
    excluded = EXCLUDED_HEADER_SCHEMAS if module == "asyncapi" else set()
    return [
        name
        for name, schema in SPECS[module].items()
        if (schema.get("properties") or schema.get("allOf")) and name not in excluded
    ]


# ------------------------------------------------------------------------ the fourteen facts
def test_the_spec_declares_fourteen_event_schemas_so_the_sweep_is_not_vacuous() -> None:
    assert len(event_schemas()) == 14


def test_every_event_schema_has_a_model_and_a_registry_entry() -> None:
    missing: list[str] = []
    for schema_name, event_type in event_schemas().items():
        model = getattr(asyncapi, schema_name, None)
        if model is None:
            missing.append(f"{schema_name}: no generated model")
        elif FACT_MODELS.get(event_type) is not model:
            missing.append(f"{event_type}: registry entry is not {schema_name}")
    assert missing == []
    assert set(FACT_MODELS) == set(event_schemas().values()), "a registry entry has no spec fact"


def test_each_event_model_pins_its_own_event_type_literal() -> None:
    """Sibling substitution: the model for `X` must accept only `X`, not a neighbour's type."""
    for schema_name, event_type in event_schemas().items():
        model = getattr(asyncapi, schema_name)
        annotation = model.model_fields["event_type"].annotation
        assert annotation.__args__ == (event_type,), f"{schema_name}: {annotation}"


def test_each_event_payload_is_the_payload_model_the_spec_names() -> None:
    for schema_name in event_schemas():
        properties, _ = resolve(ASYNC, ASYNC[schema_name])
        expected = properties["payload"]["$ref"].rsplit("/", 1)[-1]
        assert (
            getattr(asyncapi, schema_name).model_fields["payload"].annotation.__name__ == expected
        )


def test_the_facts_with_no_golden_are_exactly_the_two_listed() -> None:
    assert set(event_schemas().values()) - GOLDEN_EVENT_TYPES == FACTS_WITHOUT_A_GOLDEN
    assert set(event_schemas().values()) >= GOLDEN_EVENT_TYPES
    assert len(GOLDEN_EVENT_TYPES) == 12


def test_the_envelope_field_order_is_the_order_the_spec_declares() -> None:
    spec_order = list(ASYNC["Envelope"]["properties"])
    assert spec_order == [
        "eventId", "eventType", "aggregateId", "correlationId", "causationId", "occurredAt",
        "payload",
    ]  # fmt: skip
    assert wire_aliases(asyncapi.Envelope) == spec_order
    for schema_name in event_schemas():
        assert wire_aliases(getattr(asyncapi, schema_name)) == spec_order, schema_name


# -------------------------------------------------------- every object schema, both specs
@pytest.mark.parametrize("module", ["asyncapi", "openapi"])
def test_every_object_schema_has_a_model_whose_fields_are_the_spec_properties_in_order(
    module: str,
) -> None:
    names = object_schema_names(module)
    assert len(names) > 30, "the sweep must see the object schemas"
    problems: list[str] = []
    for name in names:
        model = getattr(MODULES[module], name, None)
        if model is None:
            problems.append(f"{module}.{name}: no generated model")
            continue
        properties, required = resolve(SPECS[module], SPECS[module][name])
        if wire_aliases(model) != list(properties):
            problems.append(f"{module}.{name}: {wire_aliases(model)} != {list(properties)}")
        for field_name, field in model.model_fields.items():
            wire = field.alias or field_name
            if field.is_required() != (wire in required):
                problems.append(f"{module}.{name}.{wire}: required-ness differs from the spec")
    assert problems == []


@pytest.mark.parametrize("module", ["asyncapi", "openapi"])
def test_every_enum_schema_has_a_str_enum_with_exactly_the_spec_values(module: str) -> None:
    enums = {n: s["enum"] for n, s in SPECS[module].items() if "enum" in s}
    assert enums, "the sweep must see the enum schemas"
    for name, values in enums.items():
        generated = getattr(MODULES[module], name)
        assert [member.value for member in generated] == values, f"{module}.{name}"


def test_every_generated_model_inherits_the_one_wire_model() -> None:
    for module in MODULES.values():
        models = [
            m
            for m in vars(module).values()
            if isinstance(m, type) and issubclass(m, BaseModel) and m.__module__ == module.__name__
        ]
        assert models
        # a RootModel wraps one primitive, has no wire-field naming, and is deliberately not a
        # WireModel; every object model is
        not_wire = [m.__name__ for m in models if not issubclass(m, WireModel)]
        assert all(
            issubclass(getattr(module, n), BaseModel) and "root" in getattr(module, n).model_fields
            for n in not_wire
        ), not_wire


# ------------------------------------------------------------------- None handling vs the spec
def spec_nullable_fields() -> dict[str, list[str]]:
    """Independent of the generator: properties whose schema is `oneOf` with `type: 'null'`."""
    found: dict[str, list[str]] = {}
    for module, schemas in SPECS.items():
        for name, schema in schemas.items():
            names = [
                prop
                for prop, sub in schema.get("properties", {}).items()
                if any(option.get("type") == "null" for option in sub.get("oneOf", []))
            ]
            if names:
                found[f"{module}.{name}"] = sorted(names)
    return found


def test_the_nullable_table_is_exactly_what_the_spec_declares_nullable() -> None:
    expected = spec_nullable_fields()
    assert len(expected) == 7, "the sweep must see the nullable fields"
    assert {k: sorted(v) for k, v in NULLABLE_FIELDS.items()} == expected


def test_the_not_required_fields_of_the_fourteen_payloads_are_these_and_none_is_nullable() -> None:
    """The per-field None table for the facts: optional here means absent when None."""
    payloads = {
        ASYNC[name]["allOf"][1]["properties"]["payload"]["$ref"].rsplit("/", 1)[-1]
        for name in event_schemas()
    }
    optional: dict[str, list[str]] = {}
    for payload in sorted(payloads):
        properties, required = resolve(ASYNC, ASYNC[payload])
        missing = [p for p in properties if p not in required]
        if missing:
            optional[payload] = missing
    assert optional == {
        "CreditReleasedPayload": ["creditCode"],
        "CreditRejectedPayload": ["creditCode"],
        "OrderCancelledPayload": ["note"],
        "OrderPlacedPayload": ["notes"],
        "StockRejectedPayload": ["retailerCode"],
        "StockReleasedPayload": ["retailerCode"],
        "StockReservedPayload": ["retailerCode"],
    }
    assert not any(k.startswith("asyncapi.") and k[9:] in payloads for k in NULLABLE_FIELDS)


def test_the_excluded_header_schemas_are_transport_headers_with_non_camel_case_keys() -> None:
    """Why they are excluded (generate_contracts.py): their keys are hyphenated header names."""
    for name in EXCLUDED_HEADER_SCHEMAS:
        assert any("-" in key for key in ASYNC[name]["properties"]), name
        assert not hasattr(asyncapi, name)


# ------------------------------------------------ every property site, at every depth (review D3)
def all_property_names(node: Any) -> set[str]:
    """Every property NAME declared anywhere under a schema, inline object schemas included."""
    names: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                names.update(value)
                for sub in value.values():
                    names |= all_property_names(sub)
            else:
                names |= all_property_names(value)
    elif isinstance(node, list):
        for item in node:
            names |= all_property_names(item)
    return names


def generated_aliases(module: Any) -> set[str]:
    aliases: set[str] = set()
    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, WireModel)
            and value.__module__ == module.__name__
        ):
            aliases.update(field.alias or name for name, field in value.model_fields.items())
    return aliases


# Population pinned (non-vacuity): the distinct property names of each spec, headers excluded.
PROPERTY_NAME_POPULATION = {"asyncapi": 105, "openapi": 91}


@pytest.mark.parametrize("module", ["asyncapi", "openapi"])
def test_every_property_name_at_every_depth_is_exactly_a_generated_wire_name(module: str) -> None:
    excluded = EXCLUDED_HEADER_SCHEMAS if module == "asyncapi" else set()
    spec_names = all_property_names({k: v for k, v in SPECS[module].items() if k not in excluded})
    aliases = generated_aliases(MODULES[module])
    assert sorted(spec_names - aliases) == [], "spec names with no generated alias of that spelling"
    assert sorted(aliases - spec_names) == [], "generated wire names the spec does not declare"
    assert len(spec_names) == PROPERTY_NAME_POPULATION[module], "population pin (non-vacuity)"
