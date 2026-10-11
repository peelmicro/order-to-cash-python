"""I1: the fact builders cover exactly the registry, parse through the real parser, and give every
envelope four pairwise-distinct ids (#8 id 60: a builder that reused one id for two fields lets a
transposition survive every assertion).

The builders are `FactBuilders` in this service's `conftest.py` (the `facts` fixture).
"""

from typing import Any

from otc_contracts import FACT_MODELS, parse_fact


def test_the_builder_set_equals_the_fact_registry(facts: Any) -> None:
    assert set(facts.event_types()) == set(FACT_MODELS)


def test_every_built_envelope_parses_with_parse_fact_into_its_registered_model(facts: Any) -> None:
    for event_type in FACT_MODELS:
        wire = facts.wire(facts.build(event_type))
        parsed = parse_fact(wire)
        assert isinstance(parsed, FACT_MODELS[event_type]), event_type
        assert parsed.event_type == event_type


def test_every_envelope_has_four_distinct_ids_and_no_id_repeats_across_envelopes(
    facts: Any,
) -> None:
    seen: dict[Any, str] = {}
    for event_type in FACT_MODELS:
        event = facts.build(event_type)
        ids = [event.event_id, event.aggregate_id, event.correlation_id, event.causation_id]
        assert len(set(ids)) == 4, f"{event_type}: an id repeats inside one envelope"
        for name, value in zip(
            ("eventId", "aggregateId", "correlationId", "causationId"), ids, strict=True
        ):
            assert value not in seen, f"{event_type}.{name} repeats {seen[value]}"
            seen[value] = f"{event_type}.{name}"
