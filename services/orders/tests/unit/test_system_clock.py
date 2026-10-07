"""`SystemClock` returns aware UTC instants in whole milliseconds (feature 14, 3.2; OI19)."""

from datetime import UTC, timedelta

from otc_orders.infrastructure.clock import SystemClock


def test_the_system_clock_returns_aware_utc_whole_milliseconds() -> None:
    clock = SystemClock()
    instants = [clock.now() for _ in range(1000)]
    assert all(instant.tzinfo is not None for instant in instants), "aware"
    assert all(instant.utcoffset() == timedelta(0) for instant in instants), "UTC"
    assert all(instant.tzinfo is UTC for instant in instants)
    assert all(instant.microsecond % 1000 == 0 for instant in instants), "whole milliseconds"
    assert len({instant.microsecond for instant in instants}) > 1, "a real clock moves"
