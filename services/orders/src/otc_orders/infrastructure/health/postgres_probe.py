"""R60: `SELECT 1` against the write model, on a connection that is never pooled.

The canonical copy is Orders'; Fulfillment, Billing and Notifications hold identical copies
(`tests/architecture/test_observability_copy_parity.py`). The probe owns a `NullPool` engine, so a
probe the bound cancels closes its connection instead of returning a half-used one to a pool the
service's own work shares (#8 found that defect in its pooled probe and fixed it with `Pooling =
false`: `order-to-cash-dotnet/src/Orders/Infrastructure/Health/MsSqlHealthCheck.cs:21-33`). The
bound is twice: asyncpg's own connect timeout and `asyncio.timeout` around the whole call, since a
docker-paused server accepts the TCP connection and then never answers the startup message.
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

PROBE_BOUND_SECONDS = 2.0


class PostgresProbe:
    def __init__(self, url: str, *, bound_seconds: float = PROBE_BOUND_SECONDS) -> None:
        self._bound = bound_seconds
        self._engine = create_async_engine(
            url, poolclass=NullPool, connect_args={"timeout": bound_seconds}
        )

    async def __call__(self) -> None:
        async with asyncio.timeout(self._bound):
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))

    async def aclose(self) -> None:
        await self._engine.dispose()
