"""R60 / OR6, S6.2: the read-model probe is BOUNDED; a `ping` that never answers is `down` within
the bound plus 100 ms (the real paused-MongoDB case is `test_projector_health_probes.py`).

The probe is called directly, not through `HealthCheck`, so that the bound under test is its own.
"""

import asyncio
import time

import pytest

from otc_projector.infrastructure.health.mongo_probe import MongoProbe

BOUND = 0.4
SLACK = 0.1
RUNAWAY = 4.0


class SilentDatabase:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def command(self, command: str) -> object:
        self.commands.append(command)
        await asyncio.sleep(RUNAWAY * 4)
        return {"ok": 1}


class AnsweringDatabase:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def command(self, command: str) -> object:
        self.commands.append(command)
        return {"ok": 1}


async def test_or6_the_mongo_probe_is_down_within_its_bound_when_ping_never_answers() -> None:
    database = SilentDatabase()
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(RUNAWAY):
            await MongoProbe(database, bound_seconds=BOUND)()
    elapsed = time.monotonic() - started
    assert elapsed <= BOUND + SLACK, (
        f"R60: the MongoDB probe took {elapsed:.3f} s against a bound of {BOUND} s: "
        "a probe that never answers must be down within its bound plus 100 ms"
    )
    assert database.commands == ["ping"]


async def test_or6_the_mongo_probe_sends_exactly_one_ping_when_the_server_answers() -> None:
    database = AnsweringDatabase()
    await MongoProbe(database, bound_seconds=BOUND)()
    assert database.commands == ["ping"]
