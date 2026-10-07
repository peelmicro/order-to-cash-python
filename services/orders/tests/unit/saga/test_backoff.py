"""The back-off arithmetic (task 8.1; L14, L15): `int` in, `int` out, never a `float`."""

import pytest

from otc_orders.infrastructure.saga.backoff import (
    in_line_backoff_ms,
    park_backoff_ms,
    park_exponent,
)

CAP = 900_000


def test_the_in_line_schedule_for_three_attempts_is_500_then_1000_ms() -> None:
    assert [in_line_backoff_ms(attempt, base_ms=500) for attempt in (1, 2)] == [500, 1000]
    assert in_line_backoff_ms(3, base_ms=500) == 2000


def test_the_park_back_off_for_3_6_and_9_total_attempts_is_60_120_and_240_seconds() -> None:
    delays = [park_backoff_ms(n, max_attempts=3, cap_ms=CAP) for n in (3, 6, 9)]

    assert delays == [60_000, 120_000, 240_000]
    assert all(type(delay) is int for delay in delays), "int arithmetic: `/` would make a float"
    assert park_exponent(9, max_attempts=3) == 3


def test_the_park_back_off_is_capped() -> None:
    assert park_backoff_ms(30, max_attempts=3, cap_ms=CAP) == CAP
    assert park_backoff_ms(30, max_attempts=3, cap_ms=70_000) == 70_000


def test_the_park_exponent_is_clamped_before_the_power() -> None:
    assert park_exponent(2**31 - 1, max_attempts=3) == 31
    assert park_exponent(2**31 - 1, max_attempts=1) == 31, (
        "the clamp is the same for any cycle size"
    )
    assert park_backoff_ms(2**31 - 1, max_attempts=1, cap_ms=2**62) == 30_000 * 2**31


def test_floor_division_keeps_partial_cycles_below_the_next_doubling() -> None:
    assert park_exponent(5, max_attempts=3) == 1
    assert park_exponent(3, max_attempts=3) == 1
    assert park_exponent(2, max_attempts=3) == 0


@pytest.mark.parametrize("attempt", [0, 11, -1])
def test_an_in_line_attempt_outside_one_to_ten_is_refused(attempt: int) -> None:
    with pytest.raises(ValueError, match=r"1\.\.10"):
        in_line_backoff_ms(attempt, base_ms=500)
