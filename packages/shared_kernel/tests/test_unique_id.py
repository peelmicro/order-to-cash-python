"""`UniqueId`: a v4 UUID generated in the domain; identity is its value (domain-model 2.5)."""

import uuid
from typing import Any

import pytest

from otc_shared_kernel import DomainError, InvalidUniqueIdError, UniqueId


def test_new_generates_a_distinct_version_4_uuid_inside_the_domain() -> None:
    ids = [UniqueId.new() for _ in range(500)]
    assert len({i.value for i in ids}) == 500
    assert all(i.value.version == 4 and i.value.variant == uuid.RFC_4122 for i in ids)
    assert all(type(i.value) is uuid.UUID for i in ids)


def test_parse_round_trips_and_normalises_case() -> None:
    original = UniqueId.new()
    assert UniqueId.parse(str(original)) == original
    assert UniqueId.parse(str(original).upper()) == original
    assert str(UniqueId.parse("0F8FAD5B-D9CB-469F-A165-70867728950E")) == (
        "0f8fad5b-d9cb-469f-a165-70867728950e"
    )


def test_two_ids_are_equal_iff_their_values_are_equal() -> None:
    value = uuid.UUID("0f8fad5b-d9cb-469f-a165-70867728950e")
    assert UniqueId(value) == UniqueId(uuid.UUID(str(value)))
    assert hash(UniqueId(value)) == hash(UniqueId(uuid.UUID(str(value))))
    assert UniqueId(value) != UniqueId.new()


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not-a-uuid",
        "00000000-0000-0000-0000-000000000000",  # nil
        "0f8fad5bd9cb469fa16570867728950e",  # no hyphens
        "{0f8fad5b-d9cb-469f-a165-70867728950e}",
        "urn:uuid:0f8fad5b-d9cb-469f-a165-70867728950e",
        "0f8fad5b-d9cb-469f-a165-70867728950e\n",
        " 0f8fad5b-d9cb-469f-a165-70867728950e",
        "0f8fad5b-d9cb-469f-a165-70867728950g",
        "0f8fad5b-d9cb-469f-a165-7086772895",
        None,
        12345,
        b"0f8fad5b-d9cb-469f-a165-70867728950e",
        uuid.UUID(int=1),
    ],
    ids=repr,
)
def test_parse_refuses_anything_but_a_canonical_non_nil_uuid_string(bad: Any) -> None:
    with pytest.raises(InvalidUniqueIdError) as raised:
        UniqueId.parse(bad)
    assert isinstance(raised.value, DomainError)
    assert raised.value.code == "unique_id.invalid"


@pytest.mark.parametrize(
    "bad", [uuid.UUID(int=0), "0f8fad5b-d9cb-469f-a165-70867728950e", None, 1, b"x" * 16]
)
def test_the_constructor_refuses_nil_and_non_uuid_values(bad: Any) -> None:
    with pytest.raises(InvalidUniqueIdError):
        UniqueId(bad)


def test_parse_refuses_a_36_character_string_that_uuid_would_still_read() -> None:
    # `uuid.UUID` ignores hyphen placement; 36 characters with the hyphens in the wrong places
    # parse to a real UUID but are not the canonical spelling, so they are refused.
    misplaced = "0f8fad5b-d9cb469f-a165-7086-7728950e"
    assert len(misplaced) == 36
    assert uuid.UUID(misplaced).int != 0
    with pytest.raises(InvalidUniqueIdError):
        UniqueId.parse(misplaced)
