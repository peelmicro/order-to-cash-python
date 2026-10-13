"""Notifications integration fixtures: an Alembic runner and a migrated database per test.

The shared container and `fresh_database` live in the repository-root `conftest.py`.
"""

import asyncio
import importlib.util
import sys
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

import asyncpg
import httpx
import pytest
import pytest_asyncio
from aiokafka import AIOKafkaProducer
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from otc_notifications.composition import NotificationsRuntime, load_settings, start_runtime
from otc_notifications.main import create_app as create_real_app
from otc_notifications.presentation.app import create_app as create_routes


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
DEAD_LETTER_SUPPORT = (
    Path(__file__).resolve().parents[4] / "tests/observability/dead_letter_support.py"
)


def dead_letter_support() -> ModuleType:
    """`tests/observability/dead_letter_support.py`, loaded by path (importlib mode)."""
    name = "dead_letter_support"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, DEAD_LETTER_SUPPORT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TRACE_SUPPORT = Path(__file__).resolve().parents[4] / "tests/observability/trace_support.py"


@pytest.fixture
def dl_support() -> ModuleType:
    """`tests/observability/dead_letter_support.py` (broker readers, a producer)."""
    return dead_letter_support()


@pytest.fixture
def trace_support() -> ModuleType:
    """`tests/observability/trace_support.py` (typed span readers), loaded by path."""
    name = "trace_support"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, TRACE_SUPPORT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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
    return await migrated_database_from_template("notifications")


@pytest_asyncio.fixture(loop_scope="function")
async def engine(migrated_db: FreshDatabase) -> AsyncIterator[AsyncEngine]:
    # Function loop; created and disposed here, in the loop that uses it.
    eng = create_async_engine(migrated_db.url)
    try:
        yield eng
    finally:
        await eng.dispose()


# ------------------------------------------------------------- feature 23: Mailpit, Kafka, the host


MAILPIT_IMAGE = "axllent/mailpit:v1.27.5"  # the compose pin (docker-compose.infra.yml)
MAILPIT_SMTP_PORT = 1025
MAILPIT_UI_PORT = 8025

# Which topic carries which notified fact (asyncapi.yaml channels `ordersFacts`, `fulfillmentFacts`,
# `billingFacts`): the PRODUCER's side of the routing, written out.
TOPIC_OF = {
    "order.placed.v1": "otc.orders.facts.v1",
    "order.confirmed.v1": "otc.orders.facts.v1",
    "order.completed.v1": "otc.orders.facts.v1",
    "order.cancelled.v1": "otc.orders.facts.v1",
    "order.despatched.v1": "otc.fulfillment.facts.v1",
    "invoice.issued.v1": "otc.billing.facts.v1",
    "payment.received.v1": "otc.billing.facts.v1",
}


@dataclass(frozen=True)
class MailpitServer:
    smtp_host: str
    smtp_port: int
    api_url: str


@pytest.fixture(scope="session")
def mailpit_server() -> Iterator[MailpitServer]:
    """ONE Docker-held Mailpit per session, the compose image, started with the generic
    `DockerContainer` (as the Kafka fixture is). `testcontainers.community.mailpit` exists but
    imports `cryptography` (not a dependency of this workspace) and generates a 4096-bit RSA
    certificate per container for a TLS this suite never uses. Ports are assigned and held by
    Docker. `MP_ENABLE_CHAOS` lets a test force a real 550 / 451 SMTP answer. Sync and session
    scoped: it has no loop; tests talk to it through `Inbox` in their own loop."""
    container = (
        DockerContainer(MAILPIT_IMAGE)
        .with_env("MP_ENABLE_CHAOS", "true")
        .with_exposed_ports(MAILPIT_SMTP_PORT, MAILPIT_UI_PORT)
    )
    with container:
        LogMessageWaitStrategy("accessible via").with_startup_timeout(60).wait_until_ready(
            container
        )
        host = container.get_container_host_ip()
        yield MailpitServer(
            smtp_host=host,
            smtp_port=int(container.get_exposed_port(MAILPIT_SMTP_PORT)),
            api_url=f"http://{host}:{container.get_exposed_port(MAILPIT_UI_PORT)}",
        )


class Inbox:
    """Mailpit's HTTP API, read from the test's own loop. Every assertion in the suite about what
    was e-mailed goes through this: the inbox, not a call's return value."""

    def __init__(self, server: MailpitServer) -> None:
        self._base = server.api_url

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(base_url=self._base, timeout=10) as client:
            response = await client.request(method, path, **kwargs)
        response.raise_for_status()
        is_json = response.headers.get("content-type", "").startswith("application/json")
        return response.json() if is_json else response.text

    async def summaries(self) -> list[dict[str, Any]]:
        found = await self._request("GET", "/api/v1/messages", params={"limit": 500})
        messages: list[dict[str, Any]] = found["messages"]
        return messages

    async def message(self, message_id: str) -> dict[str, Any]:
        found: dict[str, Any] = await self._request("GET", f"/api/v1/message/{message_id}")
        return found

    async def full_messages(self) -> list[dict[str, Any]]:
        return [await self.message(s["ID"]) for s in await self.summaries()]

    async def count(self) -> int:
        return len(await self.summaries())

    async def clear(self) -> None:
        await self._request("DELETE", "/api/v1/messages")

    async def set_chaos(self, **triggers: tuple[int, int]) -> None:
        """`set_chaos(Sender=(550, 100))`: answer MAIL FROM with 550 in 100% of the sessions."""
        body = {name: {"ErrorCode": code, "Probability": p} for name, (code, p) in triggers.items()}
        await self._request("PUT", "/api/v1/chaos", json=body)

    async def clear_chaos(self) -> None:
        await self._request(
            "PUT",
            "/api/v1/chaos",
            json={
                "Sender": {"ErrorCode": 451, "Probability": 0},
                "Recipient": {"ErrorCode": 451, "Probability": 0},
                "Authentication": {"ErrorCode": 535, "Probability": 0},
            },
        )

    async def wait_for_count(
        self, count: int, *, deadline_seconds: float = 30.0
    ) -> list[dict[str, Any]]:
        """Wait until the inbox holds EXACTLY `count` messages: a terminal condition read from the
        inbox itself (never a sleep standing in for one), polled at 50 ms and bounded."""
        deadline = time.monotonic() + deadline_seconds
        seen = -1
        while time.monotonic() < deadline:
            summaries = await self.summaries()
            seen = len(summaries)
            if seen == count:
                return summaries
            if seen > count:
                raise AssertionError(
                    f"the inbox holds {seen} message(s), more than the {count} expected"
                )
            await asyncio.sleep(0.05)
        raise AssertionError(f"the inbox never held exactly {count} message(s): last saw {seen}")


@pytest_asyncio.fixture(loop_scope="function")
async def inbox(mailpit_server: MailpitServer) -> AsyncIterator[Inbox]:
    box = Inbox(mailpit_server)
    await box.clear_chaos()
    await box.clear()
    yield box
    await box.clear_chaos()
    await box.clear()


@dataclass(frozen=True)
class KafkaServerShape:
    bootstrap_servers: str


class Publisher:
    """Publishes a fact exactly as a producer's relay does: the fact's bytes keyed by its
    `correlationId` (the partition key), on the topic of the context that produces it."""

    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap = bootstrap_servers

    async def publish(self, topic: str, key: uuid.UUID, value: bytes) -> None:
        producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap, client_id="otc-notifications-it"
        )
        await producer.start()
        try:
            await producer.send_and_wait(topic, value=value, key=str(key).encode("utf-8"))
        finally:
            await producer.stop()


@pytest_asyncio.fixture(loop_scope="function")
async def private_topics(kafka_server: Any) -> Any:
    """THREE private source topics and their THREE private `.dlq` companions (item 10): a test that
    publishes a poison fact passes them to `notifications_host_factory(topics=...)`, so the poison
    is never on a topic any other test reads. Created under a name unique to the test."""
    return await dead_letter_support().create_private_topics(
        kafka_server.bootstrap_servers, "notifications-dlq"
    )


@pytest.fixture
def publisher(kafka_server: Any) -> Publisher:
    return Publisher(kafka_server.bootstrap_servers)


@dataclass(frozen=True)
class NotificationsHost:
    app: FastAPI
    runtime: NotificationsRuntime
    group: str


HostEnv = Callable[..., None]
HostFactory = Callable[..., AbstractAsyncContextManager[NotificationsHost]]


@pytest.fixture
def host_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    migrated_db: FreshDatabase,
    kafka_server: Any,
    mailpit_server: MailpitServer,
) -> HostEnv:
    """`host_environment(**overrides)`: the environment a real deployment would carry, set through
    the process environment (the only way the host reads it). The working directory is an empty
    directory, so a developer's `.env` can never supply a value, and every variable the composition
    root reads is set here, so a developer shell's value never leaks in either. The consumer group
    is UNIQUE per call unless a test pins one (the restart test), so a group never inherits another
    test's committed offsets; the sender is the SMTP one against the Docker-held Mailpit.

    `kafka_server` and `mailpit_server` are plain sync session fixtures (they run their own loop or
    none), so they are requested here, before any loop runs."""

    def apply(**overrides: str) -> None:
        monkeypatch.chdir(tmp_path)
        values = {
            "NOTIFICATIONS_DATABASE_URL": migrated_db.url,
            "KAFKA_BROKERS": kafka_server.bootstrap_servers,
            "NOTIFICATIONS_KAFKA_CLIENT_ID": "otc-notifications-tests",
            "NOTIFICATIONS_CONSUMER_GROUP": f"notifications-it-{uuid.uuid4().hex[:10]}",
            "NOTIFICATIONS_SENDER": "smtp",
            "SMTP_HOST": mailpit_server.smtp_host,
            "SMTP_PORT": str(mailpit_server.smtp_port),
            "SMTP_FROM_EMAIL": "no-reply@order-to-cash.example",
        }
        values |= overrides
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        for name in (
            "POSTGRES_APP_PASSWORD",
            "POSTGRES_APP_USER",
            "POSTGRES_DB_NOTIFICATIONS",
            "POSTGRES_HOST",
            "POSTGRES_HOST_PORT",
            "SMTP_USER",
            "SMTP_PASSWORD",
            "SMTP_START_TLS",
        ):
            if name not in overrides:
                monkeypatch.delenv(name, raising=False)

    return apply


@pytest_asyncio.fixture(loop_scope="function")
async def notifications_host_factory(host_environment: HostEnv) -> HostFactory:
    """`async with notifications_host_factory(NOTIFICATIONS_SENDER="console") as host:` drives the
    REAL `otc_notifications.main.create_app()` lifespan (no argument, no injected configuration), in
    the test's loop, and stops it on exit: every engine and client it opened is closed in this loop.
    `notifications_host_factory(sender=port)` boots the real `start_runtime` with that sender port
    bound instead: the same composition root, one binding different. `stop_grace_seconds` (sender
    path only) is the grace `runtime.stop()` gives a task before it cancels it."""

    @asynccontextmanager
    async def start(
        *,
        sender: Any = None,
        stop_grace_seconds: float | None = None,
        topics: Any = None,
        dead_letter_producer_factory: Callable[..., Any] | None = None,
        span_processors: Sequence[Any] = (),
        metric_readers: Sequence[Any] = (),
        **overrides: str,
    ) -> AsyncIterator[NotificationsHost]:
        """`topics` (a `private_topics` fixture value) points the consumer at THAT test's private
        source topics instead of the real ones, and `dead_letter_producer_factory` replaces the
        dead-letter publisher's producer (a test that makes the publication fail): both through the
        composition root's test seam (`start_runtime(...)`, never an environment variable
        production could set), so the real `start_runtime` runs with one binding different."""
        host_environment(**overrides)
        if (
            sender is None
            and topics is None
            and dead_letter_producer_factory is None
            and len(span_processors) == 0
            and len(metric_readers) == 0
        ):
            app = create_real_app()
            async with app.router.lifespan_context(app):
                runtime = app.state.runtime
                yield NotificationsHost(app, runtime, runtime.settings.kafka.group_id)
            return
        grace: dict[str, Any] = (
            {} if stop_grace_seconds is None else {"stop_grace_seconds": stop_grace_seconds}
        )
        fact_topics: Sequence[str] | None = None if topics is None else topics.all
        runtime = await start_runtime(
            load_settings(),
            sender=sender,
            fact_topics=fact_topics,
            dead_letter_producer_factory=dead_letter_producer_factory,
            span_processors=span_processors,
            metric_readers=metric_readers,
            **grace,
        )
        app = create_routes()
        app.state.runtime = runtime
        try:
            yield NotificationsHost(app, runtime, runtime.settings.kafka.group_id)
        finally:
            app.state.runtime = None
            await runtime.stop()

    return start


LedgerRows = Callable[[], Awaitable[list[tuple[uuid.UUID, str]]]]


@pytest.fixture
def topic_of() -> dict[str, str]:
    return TOPIC_OF


@pytest.fixture
def ledger_rows(migrated_db: FreshDatabase) -> LedgerRows:
    """`await ledger_rows()` -> every `(event_id, consumer)` of the test database, read through a
    connection of its own, in the order they were recorded."""

    async def read() -> list[tuple[uuid.UUID, str]]:
        connection = await asyncpg.connect(migrated_db.dsn)
        try:
            rows = await connection.fetch(
                "SELECT event_id, consumer FROM processed_events ORDER BY created_at, event_id"
            )
        finally:
            await connection.close()
        return [(r["event_id"], r["consumer"]) for r in rows]

    return read
