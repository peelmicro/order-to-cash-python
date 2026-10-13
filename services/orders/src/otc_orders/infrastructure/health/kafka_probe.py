"""R60: the fact stream's broker answers a cluster description.

The canonical copy is Orders'; Notifications and Projector hold identical copies
(`tests/architecture/test_observability_copy_parity.py`). This module and `dlq_depth.py` are the
only places of this service that start an `AIOKafkaAdminClient`
(`test_kafka_client_confinement.py`).

The client is dedicated (never the relay's producer or the consumer, whose state a probe must not
disturb), long-lived, and started on the FIRST call, inside the loop that runs the probe. A call
the bound cancels leaves the client usable: after a pause longer than the bound the next call
answers (measured in `observability_reliability` S6.3 against a real broker: the first call after
the unpause was `up`), so no client per call is needed. A client whose start the bound cancelled is
closed and rebuilt on the next call, never kept half-started.
"""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import Any, Protocol

from aiokafka.admin import AIOKafkaAdminClient

PROBE_BOUND_SECONDS = 2.0
CLOSE_BOUND_SECONDS = 5.0


class AdminClient(Protocol):
    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def describe_cluster(self) -> dict[str, Any]: ...


AdminClientFactory = Callable[[str, str], AdminClient]


def _aiokafka_admin(brokers: str, client_id: str) -> AdminClient:
    client: AdminClient = AIOKafkaAdminClient(bootstrap_servers=brokers, client_id=client_id)
    return client


class KafkaAdminProbe:
    def __init__(
        self,
        brokers: str,
        *,
        client_id: str,
        bound_seconds: float = PROBE_BOUND_SECONDS,
        client_factory: AdminClientFactory = _aiokafka_admin,
    ) -> None:
        self._brokers = brokers
        self._client_id = client_id
        self._bound = bound_seconds
        self._factory = client_factory
        self._client: AdminClient | None = None

    async def __call__(self) -> None:
        async with asyncio.timeout(self._bound):
            if self._client is None:
                client = self._factory(self._brokers, self._client_id)
                try:
                    await client.start()
                except BaseException:
                    await _close(client)
                    raise
                self._client = client
            await self._client.describe_cluster()

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await _close(client)


async def _close(client: AdminClient) -> None:
    with suppress(Exception):
        async with asyncio.timeout(CLOSE_BOUND_SECONDS):
            await client.close()
