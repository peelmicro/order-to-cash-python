"""The guarantees the readiness tests of feature 27 (S6.7) lean on, proven once, here.

* `paused(container)` unpauses in a `finally`: a test body that raises (an assertion, a timeout, a
  cancellation) must not leave a frozen container behind (S6 brief: "unpaused in a `finally`").
  The container is real: a private NATS, paused and inspected through Docker.
* `poll(...)` is PACED: a read that fails in microseconds cannot turn the loop into a busy spin
  that burns its whole budget in a millisecond (#8 ids 63 and 69). The probe here fails in
  microseconds (a change of kind from the real probes, which take a bound's worth of time).
"""

import asyncio
import importlib.util
import itertools
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

SUPPORT_PATH = Path(__file__).resolve().parent / "health_support.py"


def _support() -> ModuleType:
    spec = importlib.util.spec_from_file_location("health_support", SUPPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


support = _support()


def test_s6_a_body_that_raises_inside_paused_leaves_the_container_running() -> None:
    def dies_while_frozen(container: object) -> None:
        with support.paused(container):
            assert support.status_of(container) == "paused", "the pause did not take"
            raise RuntimeError("the body died while the container was frozen")

    with support.private_nats() as (container, _url):
        with pytest.raises(RuntimeError, match="the body died while the container was frozen"):
            dies_while_frozen(container)
        status = support.status_of(container)
        assert status == "running", (
            f"S6: a body that raised left the container {status}: the unpause is not in a finally"
        )


def test_s6_a_body_that_times_out_inside_paused_leaves_the_container_running() -> None:
    async def body(container: object) -> None:
        with support.paused(container):
            async with asyncio.timeout(0.2):
                await asyncio.sleep(5)

    with support.private_nats() as (container, _url):
        with pytest.raises(TimeoutError):
            asyncio.run(body(container))
        assert support.status_of(container) == "running"


def test_s6_a_body_that_completes_inside_paused_unpauses_too() -> None:
    with support.private_nats() as (container, _url):
        with support.paused(container):
            assert support.status_of(container) == "paused"
        assert support.status_of(container) == "running"


async def test_s6_poll_is_paced_even_when_the_read_fails_in_microseconds() -> None:
    reads: list[float] = []

    async def instant_failure() -> bool:
        reads.append(time.monotonic())
        return False

    started = time.monotonic()
    with pytest.raises(AssertionError, match="the dependency never came back"):
        await support.poll(
            instant_failure,
            lambda sample: sample,
            within=0.6,
            claim="the dependency never came back",
            interval=0.25,
        )
    elapsed = time.monotonic() - started

    assert elapsed >= 0.6, f"the budget expired after {elapsed:.3f} s: the loop is not waiting"
    # 0.6 s of budget at 0.25 s pacing is 3 reads (at 0, 0.25 and 0.5 s); a spinning loop makes
    # tens of thousands
    assert len(reads) <= 4, f"{len(reads)} reads in {elapsed:.3f} s: the poll is not paced"
    gaps = [later - earlier for earlier, later in itertools.pairwise(reads)]
    assert all(gap >= 0.24 for gap in gaps), f"two reads {min(gaps):.4f} s apart: not paced"


async def test_s6_poll_returns_every_sample_and_stops_at_the_first_accepted_one() -> None:
    values = iter([False, False, True, True])

    async def read() -> bool:
        return next(values)

    samples = await support.poll(read, lambda sample: sample, within=2.0, claim="x", interval=0.01)

    assert samples == [False, False, True]
