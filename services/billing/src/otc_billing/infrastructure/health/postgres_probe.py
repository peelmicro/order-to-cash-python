"""R60: `SELECT 1` against the write model, on a connection that is never pooled.

Copy of `services/orders/src/otc_orders/infrastructure/health/postgres_probe.py`.

The canonical is Orders'; `tests/architecture/test_observability_copy_parity.py` fails
on any difference after this docstring. Edit the canonical, then copy.
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
