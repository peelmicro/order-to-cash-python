"""R60: the read model answers `ping`.

Copy of `services/projector/src/otc_projector/infrastructure/health/mongo_probe.py`.

The canonical is Projector'; `tests/architecture/test_observability_copy_parity.py` fails
on any difference after this docstring. Edit the canonical, then copy.
"""

import asyncio
from typing import Protocol

PROBE_BOUND_SECONDS = 2.0


class PingTarget(Protocol):
    async def command(self, command: str) -> object: ...


class MongoProbe:
    def __init__(self, database: PingTarget, *, bound_seconds: float = PROBE_BOUND_SECONDS) -> None:
        self._database = database
        self._bound = bound_seconds

    async def __call__(self) -> None:
        async with asyncio.timeout(self._bound):
            await self._database.command("ping")
