"""The Gateway's domain: the issued-order window (R55), the login throttle (R63) and the pure
imports of the layer. No framework, no clock: time is an integer the test moves."""

import ast
import sys
from pathlib import Path
from uuid import UUID

import pytest

from otc_gateway.domain.issued_order_window import IssuedOrderWindow
from otc_gateway.domain.login_throttle import LoginThrottle

DOMAIN = Path(__file__).resolve().parents[2] / "src" / "otc_gateway" / "domain"
A, B, C = UUID(int=1), UUID(int=2), UUID(int=3)


class Ticker:
    def __init__(self) -> None:
        self.ms = 5_000

    def __call__(self) -> int:
        return self.ms


# ------------------------------------------------------------------------ IssuedOrderWindow


def test_window_remembers_an_id_for_the_ttl_and_not_a_millisecond_longer() -> None:
    clock = Ticker()
    window = IssuedOrderWindow(clock, ttl_ms=1000, capacity=10)
    window.record(A)

    clock.ms += 1000
    assert window.is_recently_issued(A)  # exactly the ttl: still there
    clock.ms += 1
    assert not window.is_recently_issued(A)
    assert len(window) == 0  # evicted by the read that found it expired


def test_window_does_not_know_an_id_it_never_recorded() -> None:
    window = IssuedOrderWindow(Ticker(), ttl_ms=1000, capacity=10)
    window.record(A)

    assert not window.is_recently_issued(B)


def test_window_evicts_the_oldest_first_beyond_its_capacity() -> None:
    window = IssuedOrderWindow(Ticker(), ttl_ms=1000, capacity=2)
    for order in (A, B, C):
        window.record(order)

    assert not window.is_recently_issued(A)
    assert window.is_recently_issued(B)
    assert window.is_recently_issued(C)
    assert len(window) == 2


def test_window_re_recording_an_id_makes_it_the_newest_and_restarts_its_clock() -> None:
    clock = Ticker()
    window = IssuedOrderWindow(clock, ttl_ms=1000, capacity=2)
    window.record(A)
    window.record(B)
    clock.ms += 900
    window.record(A)  # A is newest now, and its ttl restarts
    window.record(C)  # evicts B, the oldest, not A

    clock.ms += 900
    assert window.is_recently_issued(A)
    assert not window.is_recently_issued(B)


@pytest.mark.parametrize(("ttl", "capacity"), [(0, 1), (-1, 1), (1, 0), (1, -5)])
def test_window_refuses_a_ttl_or_capacity_that_would_remember_nothing(
    ttl: int, capacity: int
) -> None:
    with pytest.raises(ValueError, match="must be at least 1"):
        IssuedOrderWindow(Ticker(), ttl_ms=ttl, capacity=capacity)


# ------------------------------------------------------------------------ LoginThrottle


def test_throttle_admits_the_limit_then_refuses_with_the_whole_seconds_remaining() -> None:
    clock = Ticker()
    throttle = LoginThrottle(clock, limit=3, window_ms=60_000)

    assert [throttle.check("a") for _ in range(3)] == [0, 0, 0]
    assert throttle.check("a") == 60

    clock.ms += 1  # 59.999 s remain: rounded UP to 60, never down to 59
    assert throttle.check("a") == 60
    clock.ms += 58_999  # 1 ms remains: still a whole second to wait, not 0 (0 means admitted)
    assert throttle.check("a") == 1


def test_throttle_reopens_exactly_when_the_window_ends() -> None:
    clock = Ticker()
    throttle = LoginThrottle(clock, limit=1, window_ms=1000)
    assert throttle.check("a") == 0
    clock.ms += 999
    assert throttle.check("a") == 1
    clock.ms += 1
    assert throttle.check("a") == 0  # a fresh window


def test_throttle_a_refused_attempt_does_not_extend_the_window() -> None:
    clock = Ticker()
    throttle = LoginThrottle(clock, limit=1, window_ms=1000)
    throttle.check("a")
    for _ in range(5):
        clock.ms += 100
        assert throttle.check("a") > 0

    clock.ms += 500  # 1000 ms after the first attempt
    assert throttle.check("a") == 0


def test_throttle_keeps_a_window_per_key() -> None:
    throttle = LoginThrottle(Ticker(), limit=1, window_ms=1000)

    assert throttle.check("a") == 0
    assert throttle.check("a") > 0
    assert throttle.check("b") == 0


def test_throttle_prunes_expired_windows_once_the_table_is_large() -> None:
    clock = Ticker()
    throttle = LoginThrottle(clock, limit=1, window_ms=1000)
    for i in range(4100):
        throttle.check(f"client-{i}")
    clock.ms += 1000

    throttle.check("newcomer")

    assert len(throttle._windows) == 1


@pytest.mark.parametrize(("limit", "window"), [(0, 1), (-1, 1), (1, 0)])
def test_throttle_refuses_a_limit_or_window_that_would_block_everyone_or_no_one(
    limit: int, window: int
) -> None:
    with pytest.raises(ValueError, match="must be at least 1"):
        LoginThrottle(Ticker(), limit=limit, window_ms=window)


# ------------------------------------------------------------------------ purity


def test_the_domain_imports_only_the_standard_library() -> None:
    files = sorted(DOMAIN.rglob("*.py"))
    assert {f.name for f in files} >= {
        "auth.py",
        "issued_order_window.py",
        "login_throttle.py",
        "rpc_error_classification.py",
    }, f"the guard must range over the real domain files: {files}"
    for file in files:
        roots: set[str] = set()
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{file}: a relative import hides its module"
                roots.add((node.module or "").split(".")[0])
        assert roots <= set(sys.stdlib_module_names) | {""}, f"{file.name}: {sorted(roots)}"
