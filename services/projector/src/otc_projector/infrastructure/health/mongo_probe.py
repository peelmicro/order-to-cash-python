"""R60: the read model answers `ping`.

The canonical copy is the Projector's; the Gateway holds an identical copy
(`tests/architecture/test_observability_copy_parity.py`). The bound is `asyncio.timeout` around the
call: a docker-paused MongoDB accepts the connection and then answers nothing, and the driver's own
server-selection wait is far longer than a readiness probe may take.
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
