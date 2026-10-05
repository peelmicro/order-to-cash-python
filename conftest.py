"""Shared integration fixtures: ONE Docker-held `postgres:18.6` per test session, a fresh database
per test.

Why a repository-root `conftest.py` (decided in feature 9, for features 10 and 11 to reuse): pytest
applies a root conftest to every test under `tests/`, `packages/` and `services/` without any
service importing anything from another service, so the import-linter independence contract is
untouched. A `conftest.py` under `tests/` would only reach `tests/`; a helper package under `tests/`
imported by services would be a cross-service import. #8 gave each database suite its own container
and `quality.sh` went from 67s to 159s; here the container is started once, lazily, by the first
test that asks for `postgres_server`, and each test gets `CREATE DATABASE` (milliseconds) instead of
a container (seconds).

* The container's port is assigned by Docker and HELD by it (`with_exposed_ports`, no free-port
  picker that releases the port before the container binds it: #8 id 85). The suite therefore
  passes with the developer stack down, and never talks to the composed postgres on 5432.
* Migrated databases come from a TEMPLATE (feature 11, review_db_fulfillment A2): each service's
  Alembic history is run ONCE per session into a template database, and every test that needs a
  migrated database gets `CREATE DATABASE ... TEMPLATE` of it (milliseconds) instead of a full
  migration (seconds). Tests that exercise the migration itself keep using `fresh_database` (an
  empty database) and run Alembic on it. The template is never handed to a test and has no open
  connection, so a test's writes cannot reach the next test: `tests/database_templates/` pins it.
* MongoDB (feature 12, `seed_job`, the first MongoDB writer; the projector reuses it): ONE
  Docker-held `mongo:8.3.8` per session (`mongo_server`, sync, no loop), and a uniquely named
  database per test (`fresh_mongo_database`, function loop, dropped by the fixture that created
  it). It lives here for the same reason the Postgres fixtures do: a root conftest reaches
  `tests/`, `packages/` and `services/` without any service importing another. Same rules: the
  port is assigned by Docker and held by it, the suite passes with the developer stack down and
  never talks to the composed mongo on 27017, and a test builds (and closes) its own
  `AsyncMongoClient` from `uri` in its own loop.
* Loop scopes (pytest's default here is `function`): `postgres_server` is a plain sync fixture, so
  it has no loop at all; `fresh_database` is a function-scoped async fixture, its asyncpg
  connection is created and closed in that same function loop, and any SQLAlchemy engine a test
  builds from `url` must be disposed by the test (or its own function-scoped fixture) in that loop.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from pymongo import AsyncMongoClient
from testcontainers.community.mongodb import MongoDbContainer
from testcontainers.community.postgres import PostgresContainer

POSTGRES_IMAGE = "postgres:18.6"
MONGO_IMAGE = "mongo:8.3.8"  # the compose pin (docker-compose.infra.yml)
_USER = "postgres"
_PASSWORD = "otc_test_password"  # noqa: S105 - a throwaway container's superuser password


@dataclass(frozen=True)
class PostgresServer:
    host: str
    port: int

    def dsn(self, database: str) -> str:
        return f"postgresql://{_USER}:{_PASSWORD}@{self.host}:{self.port}/{database}"

    def sqlalchemy_url(self, database: str) -> str:
        return f"postgresql+asyncpg://{_USER}:{_PASSWORD}@{self.host}:{self.port}/{database}"


@dataclass(frozen=True)
class FreshDatabase:
    """An empty database on the shared server. `url` is an asyncpg SQLAlchemy URL."""

    name: str
    url: str
    dsn: str


@pytest.fixture(scope="session")
def postgres_server() -> Iterator[PostgresServer]:
    container = PostgresContainer(
        POSTGRES_IMAGE, username=_USER, password=_PASSWORD, dbname="postgres", driver=None
    )
    with container:
        yield PostgresServer(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(5432)),
        )


@pytest_asyncio.fixture(loop_scope="function")
async def fresh_database(postgres_server: PostgresServer) -> AsyncIterator[FreshDatabase]:
    # Function loop: the maintenance connection opens and closes inside this one fixture.
    name = f"otc_test_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(postgres_server.dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    try:
        yield FreshDatabase(
            name=name,
            url=postgres_server.sqlalchemy_url(name),
            dsn=postgres_server.dsn(name),
        )
    finally:
        admin = await asyncpg.connect(postgres_server.dsn("postgres"))
        try:
            await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        finally:
            await admin.close()


REPO_ROOT = Path(__file__).resolve().parent
_TEMPLATES: dict[str, str] = {}  # service -> its migrated template database (session-lived)

MigratedDatabaseFactory = Callable[[str], Awaitable[FreshDatabase]]


async def _admin_execute(server: PostgresServer, sql: str) -> None:
    admin = await asyncpg.connect(server.dsn("postgres"))
    try:
        await admin.execute(sql)
    finally:
        await admin.close()


async def _template_for(server: PostgresServer, service: str) -> str:
    """The migrated template of `service`, built on first use by that service's own history."""
    if service in _TEMPLATES:
        return _TEMPLATES[service]
    name = f"otc_template_{service}_{uuid.uuid4().hex}"
    await _admin_execute(server, f'CREATE DATABASE "{name}"')
    config = Config(str(REPO_ROOT / "services" / service / "alembic.ini"))
    config.attributes["url"] = server.sqlalchemy_url(name)
    # env.py calls asyncio.run(): it needs a thread (and so a loop) of its own, and it disposes its
    # engine before returning, so the template has no open connection afterwards.
    await asyncio.to_thread(command.upgrade, config, "head")
    _TEMPLATES[service] = name
    return name


@pytest_asyncio.fixture(loop_scope="function")
async def migrated_database_from_template(
    postgres_server: PostgresServer,
) -> AsyncIterator[MigratedDatabaseFactory]:
    """A factory `await make("billing")` -> a private, migrated copy of that service's database,
    dropped when the test ends. Function loop: every connection opens and closes inside it."""
    created: list[str] = []

    async def make(service: str) -> FreshDatabase:
        template = await _template_for(postgres_server, service)
        name = f"otc_test_{uuid.uuid4().hex}"
        await _admin_execute(postgres_server, f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
        created.append(name)
        return FreshDatabase(
            name=name, url=postgres_server.sqlalchemy_url(name), dsn=postgres_server.dsn(name)
        )

    try:
        yield make
    finally:
        for name in created:
            await _admin_execute(postgres_server, f'DROP DATABASE "{name}" WITH (FORCE)')


_MONGO_USER = "otc_test"
_MONGO_PASSWORD = "otc_test_password"  # noqa: S105 - a throwaway container's root password


@dataclass(frozen=True)
class MongoServer:
    host: str
    port: int

    def uri(self) -> str:
        return (
            f"mongodb://{_MONGO_USER}:{_MONGO_PASSWORD}@{self.host}:{self.port}/?authSource=admin"
        )


@dataclass(frozen=True)
class FreshMongoDatabase:
    """A database name nobody else has used, on the shared server."""

    name: str
    uri: str


@pytest.fixture(scope="session")
def mongo_server() -> Iterator[MongoServer]:
    # port=27017 is the CONTAINER port; the host port is assigned and held by Docker.
    container = MongoDbContainer(MONGO_IMAGE, username=_MONGO_USER, password=_MONGO_PASSWORD)
    with container:
        yield MongoServer(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(27017)),
        )


@pytest_asyncio.fixture(loop_scope="function")
async def fresh_mongo_database(mongo_server: MongoServer) -> AsyncIterator[FreshMongoDatabase]:
    # Function loop: the client that drops the database opens and closes inside this fixture.
    name = f"otc_test_{uuid.uuid4().hex}"
    try:
        yield FreshMongoDatabase(name=name, uri=mongo_server.uri())
    finally:
        client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(mongo_server.uri())
        try:
            await client.drop_database(name)
        finally:
            await client.close()
