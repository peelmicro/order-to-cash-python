"""R60: the RPC transport answers a PING.

The canonical copy is Orders'; Fulfillment, Billing, Projector and the Gateway hold identical copies
(`tests/architecture/test_observability_copy_parity.py`). A client that is not connected (closed,
reconnecting or still connecting: the client's own `is_connected`) is down at once; otherwise
`flush` sends a PING and waits for the PONG, which a docker-paused server never sends. The bound is
`asyncio.timeout` around the call, and `flush(timeout=)` (whole seconds, so rounded up: the nats
client takes an `int`; the outer bound is the authoritative one). `nats.errors.TimeoutError`
subclasses the builtin `TimeoutError`, so the check reports either as "no answer within".
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
