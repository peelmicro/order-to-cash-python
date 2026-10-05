"""Fulfillment integration fixtures: an Alembic runner and a migrated database per test.

The shared container and `fresh_database` live in the repository-root `conftest.py`.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Protocol

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class FreshDatabase(Protocol):
    """The shape of the root conftest's `FreshDatabase` (not imported: conftest modules are not
    importable by name under `--import-mode=importlib`)."""

    @property
    def name(self) -> str: ...
    @property
    def url(self) -> str: ...
    @property
    def dsn(self) -> str: ...


ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

AlembicRunner = Callable[[str, str, str], Awaitable[None]]


async def _run_alembic(url: str, action: str, revision: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.attributes["url"] = url

    def _go() -> None:
        if action == "upgrade":
            command.upgrade(config, revision)
        else:
            command.downgrade(config, revision)

    # env.py is the stock async template and calls asyncio.run(); that cannot run inside the test's
    # own running loop, so it runs in a worker thread with a loop of its own. The engine it creates
    # lives and is disposed entirely inside that loop (env.py's `finally: engine.dispose()`).
    await asyncio.to_thread(_go)


@pytest.fixture
def alembic_runner() -> AlembicRunner:
    return _run_alembic


@pytest_asyncio.fixture(loop_scope="function")
async def migrated_db(
    migrated_database_from_template: Callable[[str], Awaitable[FreshDatabase]],
) -> FreshDatabase:
    # a private copy of the session's migrated template (root conftest.py), not a fresh migration
    return await migrated_database_from_template("fulfillment")


@pytest_asyncio.fixture(loop_scope="function")
async def engine(migrated_db: FreshDatabase) -> AsyncIterator[AsyncEngine]:
    # Function loop; created and disposed here, in the loop that uses it.
    eng = create_async_engine(migrated_db.url)
    try:
        yield eng
    finally:
        await eng.dispose()
