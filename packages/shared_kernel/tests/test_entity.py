"""`Entity` identity equality and `AggregateRoot` event collection."""

import pytest

from otc_shared_kernel import AggregateRoot, Entity, UniqueId


class Thing(Entity):
    pass


class OtherThing(Entity):
    pass


class Counter(AggregateRoot):
    def bump(self, label: str) -> None:
        self._raise_event(label)


def test_entities_with_the_same_id_and_type_are_equal_and_hash_alike() -> None:
    identity = UniqueId.new()
    assert Thing(identity) == Thing(identity)
    assert hash(Thing(identity)) == hash(Thing(identity))
    assert len({Thing(identity), Thing(identity)}) == 1


def test_entities_with_different_ids_are_not_equal() -> None:
    assert Thing(UniqueId.new()) != Thing(UniqueId.new())


def test_entities_of_different_types_with_the_same_id_are_not_equal() -> None:
    identity = UniqueId.new()
    assert Thing(identity) != OtherThing(identity)
    assert OtherThing(identity) != Thing(identity)
    assert len({Thing(identity), OtherThing(identity)}) == 2


def test_an_entity_is_never_equal_to_a_non_entity() -> None:
    identity = UniqueId.new()
    assert Thing(identity) != identity
    assert Thing(identity) != str(identity)
    assert Thing(identity) != object()


def test_an_entity_exposes_its_id_and_refuses_a_non_unique_id() -> None:
    identity = UniqueId.new()
    assert Thing(identity).id is identity
    with pytest.raises(TypeError):
        Thing("0f8fad5b-d9cb-469f-a165-70867728950e")  # type: ignore[arg-type]
    with pytest.raises(AttributeError):
        Thing(identity).id = UniqueId.new()  # type: ignore[misc]


def test_an_aggregate_collects_events_in_order_and_reading_does_not_clear() -> None:
    root = Counter(UniqueId.new())
    assert list(root.domain_events) == []
    root.bump("a")
    root.bump("b")
    assert list(root.domain_events) == ["a", "b"]
    assert list(root.domain_events) == ["a", "b"]


def test_pull_domain_events_reads_and_clears() -> None:
    root = Counter(UniqueId.new())
    root.bump("a")
    root.bump("b")
    assert root.pull_domain_events() == ("a", "b")
    assert root.domain_events == ()
    assert root.pull_domain_events() == ()


def test_clear_domain_events_discards_without_returning() -> None:
    root = Counter(UniqueId.new())
    root.bump("a")
    root.clear_domain_events()
    assert root.domain_events == ()


def test_the_returned_events_are_a_copy_and_aggregates_do_not_share_a_list() -> None:
    first, second = Counter(UniqueId.new()), Counter(UniqueId.new())
    first.bump("only-first")
    assert second.domain_events == ()
    snapshot = first.pull_domain_events()
    first.bump("later")
    assert snapshot == ("only-first",)
    assert first.domain_events == ("later",)


def test_an_aggregate_root_is_an_entity_with_identity_equality() -> None:
    identity = UniqueId.new()
    assert Counter(identity) == Counter(identity)
    assert Counter(identity) != Thing(identity)
