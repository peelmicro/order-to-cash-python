"""B3: the REFERENCE implementation of the causal timeline order (`PR10` clauses 1-5, `PR31`), over
hand cases. The pipeline expression is checked against this oracle by the integration differential
test; here the oracle itself is held to the rule.

`eventId`s are chosen so that the fallback (`eventId` ascending) alone would invert the expected
order wherever a causal edge exists.
"""

from otc_projector.domain.timeline_order import TimelinePosition, causal_order

T = "2026-03-01T10:00:00.000Z"
LATER = "2026-03-01T10:00:00.001Z"


def position(event_id: str, cause: str | None, at: str = T) -> TimelinePosition:
    return TimelinePosition(event_id=event_id, occurred_at=at, causation_id=cause)


def ids(entries: list[TimelinePosition]) -> list[str]:
    return [entry.event_id for entry in entries]


def test_pr10_the_reference_rule_orders_by_occurred_at_then_depth_then_event_id() -> None:
    # A chain of three in one tie group, delivered reversed, with eventIds ordered AGAINST the
    # chain: the fallback alone would give c, b, a.
    root = position("c-root", "command-1")
    middle = position("b-middle", "c-root")
    leaf = position("a-leaf", "b-middle")
    assert ids(causal_order([leaf, middle, root])) == ["c-root", "b-middle", "a-leaf"]


def test_pr10_occurred_at_is_the_primary_key_even_against_a_causal_edge() -> None:
    # The cause carries a LATER instant: the instants are different groups, the edge is ignored.
    early_effect = position("z-effect", "a-cause", at=T)
    late_cause = position("a-cause", None, at=LATER)
    assert ids(causal_order([late_cause, early_effect])) == ["z-effect", "a-cause"]


def test_pr10_two_siblings_of_one_cause_order_by_event_id() -> None:
    cause = position("m-cause", None)
    second = position("y-sibling", "m-cause")
    first = position("b-sibling", "m-cause")
    assert ids(causal_order([second, first, cause])) == ["m-cause", "b-sibling", "y-sibling"]


def test_pr31_a_cause_in_another_tie_group_means_depth_zero() -> None:
    foreign_cause = position("a-cause", None, at=LATER)
    effect = position("z-effect", "a-cause", at=T)
    sibling_root = position("m-root", None, at=T)
    # depth 0 for both T entries: eventId decides (m-root < z-effect).
    assert ids(causal_order([effect, foreign_cause, sibling_root])) == [
        "m-root",
        "z-effect",
        "a-cause",
    ]


def test_pr31_an_absent_causation_id_is_cause_less_not_an_error() -> None:
    assert ids(causal_order([position("b", None), position("a", None)])) == ["a", "b"]


def test_pr31_a_two_cycle_terminates_with_every_entry_once_and_is_deterministic() -> None:
    entries = [position("b", "a"), position("a", "b")]
    first = causal_order(entries)
    assert sorted(ids(first)) == ["a", "b"]
    assert ids(causal_order(entries)) == ids(first)
    assert ids(causal_order(list(reversed(entries)))) == ids(first)


def test_pr31_a_three_cycle_terminates_with_every_entry_once_and_is_deterministic() -> None:
    entries = [position("c", "b"), position("a", "c"), position("b", "a")]
    first = causal_order(entries)
    assert sorted(ids(first)) == ["a", "b", "c"]
    assert ids(causal_order(entries)) == ids(first)


def test_pr31_a_self_edge_is_not_a_cause() -> None:
    # If a self-edge counted, `a-self` would reach depth 1 and sort after `b-plain`.
    entries = [position("b-plain", None), position("a-self", "a-self")]
    assert ids(causal_order(entries)) == ["a-self", "b-plain"]


def test_pr10_an_empty_list_is_ordered_to_an_empty_list() -> None:
    assert causal_order([]) == []


def test_pr10_the_input_is_not_mutated_and_the_result_is_a_new_list() -> None:
    entries = [position("b", None), position("a", None)]
    result = causal_order(entries)
    assert ids(entries) == ["b", "a"]
    assert result is not entries
