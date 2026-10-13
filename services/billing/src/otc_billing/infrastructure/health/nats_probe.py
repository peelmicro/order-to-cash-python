"""R60: the RPC transport answers a PING.

Copy of `services/orders/src/otc_orders/infrastructure/health/nats_probe.py`.

The canonical is Orders'; `tests/architecture/test_observability_copy_parity.py` fails
on any difference after this docstring. Edit the canonical, then copy.
"""

import asyncio
import math
from typing import Protocol

PROBE_BOUND_SECONDS = 2.0


class NatsNotConnectedError(ConnectionError):
    """The client is not connected: no request could be answered (or it would wait for a
    reconnect)."""


class NatsConnection(Protocol):
    @property
    def is_connected(self) -> bool: ...

    async def flush(self, timeout: int = ...) -> None: ...  # noqa: ASYNC109 - nats-py's own name


class NatsProbe:
    def __init__(
        self, connection: NatsConnection, *, bound_seconds: float = PROBE_BOUND_SECONDS
    ) -> None:
        self._connection = connection
        self._bound = bound_seconds

    async def __call__(self) -> None:
        if not self._connection.is_connected:
            raise NatsNotConnectedError("the NATS connection is not connected")
        async with asyncio.timeout(self._bound):
            await self._connection.flush(timeout=math.ceil(self._bound))
