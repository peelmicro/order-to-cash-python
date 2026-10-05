"""Every seeded instant is whole milliseconds (backlog 205), and the two formatters agree.

R-map (feature_list.json id 12, acceptance 2/3; backlog 205 for the seed): `timestamptz(3)` ROUNDS
a sub-millisecond part while `format_instant` TRUNCATES it, so a value with a sub-millisecond part
would be stored as `.124` and enveloped as `.123`. The seed's instants are computed from three
fixed whole-second constants plus whole-minute/second/day offsets; this test asserts the population
(every `datetime` reachable from the dataset) so a later fixture cannot introduce one. #8 fixes its
instants the same way (whole-second `DateTimeOffset` constants); #7's are `Date` (millisecond type).
"""

from dataclasses import fields, is_dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from otc_contracts import format_instant as contracts_format_instant
from otc_seed.application import default_dataset
from otc_seed.domain.clock import BASE_DATE, MASTER_DATA_TIMESTAMP, format_instant


def _instants(value: Any) -> list[datetime]:
    if isinstance(value, datetime):
        return [value]
    if is_dataclass(value) and not isinstance(value, type):
        return [i for f in fields(value) for i in _instants(getattr(value, f.name))]
    if isinstance(value, tuple | list):
        return [i for item in value for i in _instants(item)]
    return []


def test_every_instant_of_the_dataset_is_whole_milliseconds_utc_and_aware() -> None:
    instants = _instants(default_dataset())
    assert len(instants) > 200  # the population is not vacuous (sagas alone carry well over 100)
    for instant in instants:
        assert instant.tzinfo is not None
        assert instant.utcoffset() == timedelta(0)
        assert instant.microsecond % 1000 == 0, instant


def test_the_domain_formatter_agrees_with_the_contracts_formatter_on_every_instant() -> None:
    for instant in _instants(default_dataset()):
        assert format_instant(instant) == contracts_format_instant(instant)


def test_the_two_formatters_agree_on_truncation_not_rounding() -> None:
    value = datetime(2026, 6, 1, 9, 0, 0, 123987, tzinfo=UTC)
    assert format_instant(value) == contracts_format_instant(value) == "2026-06-01T09:00:00.123Z"


def test_the_formatter_converts_to_utc_and_refuses_a_naive_instant() -> None:
    plus_two = timezone(timedelta(hours=2))
    assert format_instant(datetime(2026, 6, 1, 11, 0, 0, tzinfo=plus_two)) == (
        "2026-06-01T09:00:00.000Z"
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        format_instant(datetime(2026, 6, 1, 9, 0, 0))


def test_the_two_epoch_constants_are_the_documented_ones() -> None:
    assert format_instant(MASTER_DATA_TIMESTAMP) == "2026-01-01T00:00:00.000Z"
    assert format_instant(BASE_DATE) == "2026-06-01T09:00:00.000Z"
