"""Async Alembic environment (the `alembic init -t async` shape): asyncpg only, no sync driver.

The URL comes from `config.attributes["url"]` when a caller supplies one (the integration tests),
otherwise from `BillingDatabaseSettings`. `alembic upgrade head` from the command line therefore
needs no URL on the command line and no `%`-interpolated password in an ini file.
"""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from otc_billing.infrastructure.persistence.models import Base
from otc_billing.infrastructure.settings import BillingDatabaseSettings

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    supplied = config.attributes.get("url")
    if isinstance(supplied, str):
        return supplied
    return BillingDatabaseSettings().url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    try:
        # `begin()` commits on exit. Measured on Alembic 1.20: `connect()` also persisted the DDL,
        # but this way the commit does not depend on Alembic's own transaction handling.
        async with engine.begin() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
