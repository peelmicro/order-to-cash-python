"""The composition root of the projector: the only place adapters are chosen.

* Configuration is read through pydantic-settings ONLY (`load_settings`); no other module of the
  service touches the environment (`tests/architecture/test_composition_env_reads.py`).
* The ONE handler is registered explicitly, in one statement, in `register_handlers`; the registry
  is validated by `build_dispatcher` (zero handlers or two fail the boot).
* `start_runtime` is what the lifespan runs. Its STATEMENT ORDER is the boot order (`PR43`): the
  dispatcher's validation (before any connection is opened), a MongoDB round trip, index creation
  and verification (`PR22`, `PR52`), the timeline-order migration (`PR32`), the NATS connection
  within a bound (`PR45`), the adapters, and only then the consumer task. Everything it opens is
  owned by one `AsyncExitStack`, so a failure at any step closes what was already opened, in
  reverse, and a task that was already created is stopped and awaited first.
* One asyncio task per transport: the Kafka fact consumer, created here, owned by the runtime and
  awaited on shutdown. The projector has NO outbox relay and NO RPC responder: it consumes facts,
  writes the read model and publishes the update signal
  (`tests/unit/test_projector_consumes_only.py`). A task that ends while the runtime is running, a
  consumer that has not joined its group, or a NATS connection that is closed or reconnecting
  takes readiness down (`unready_reasons`, served by `/health/ready`).
* The external collaborators are the fields of `Externals`, real by default and replaceable by a
  test that wants to observe the ORDER of the steps with recording fakes (`PR43`). The Mongo
  client, the NATS connection and the aiokafka consumer are created inside the running loop, here,
  and closed in it by the stack (ledger L29, L49).
"""

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from typing import Any, Protocol

import nats.errors
from nats.aio.client import Client as NatsClient
from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

import otc_projector.application
from otc_cqrs import Dispatcher, HandlerRegistry
from otc_projector.application.handlers import ProjectFactHandler
from otc_projector.application.messages import ProjectFactCommand
from otc_projector.application.scope import ProjectorScope
from otc_projector.infrastructure.messaging.idempotent_consumer import IdempotentConsumer
from otc_projector.infrastructure.messaging.kafka_fact_subscriber import KafkaFactSubscriber
from otc_projector.infrastructure.persistence.mongo_read_model_writer import MongoReadModelWriter
from otc_projector.infrastructure.persistence.read_model_document import COLLECTION
from otc_projector.infrastructure.persistence.read_model_indexes import (
    ensure_indexes,
    verify_indexes,
)
from otc_projector.infrastructure.persistence.timeline_order_migration import (
    migrate_timeline_order,
)
from otc_projector.infrastructure.settings import KafkaSettings, MongoSettings, NatsSettings
from otc_projector.infrastructure.signal.nats_update_signal_publisher import (
    NatsPublisher,
    NatsUpdateSignalPublisher,
)
from otc_projector.presentation.projector_facts_consumer import ProjectorFactsConsumerTask

log = logging.getLogger("otc_projector.composition")

CONSUMER_STARTUP_SECONDS = 60.0
STOP_GRACE_SECONDS = 30.0
# `nats.connect` with its defaults keeps retrying 60 x 2 s before raising (measured: still
# connecting after 60 s), so the bound on the boot's connection is the projector's own (`PR45`).
NATS_CONNECT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class ProjectorSettings:
    """Every settings class of the service, each constructed exactly once, here."""

    mongo: MongoSettings
    kafka: KafkaSettings
    nats: NatsSettings


def load_settings() -> ProjectorSettings:
    return ProjectorSettings(mongo=MongoSettings(), kafka=KafkaSettings(), nats=NatsSettings())


# ------------------------------------------------------------------------------ the dispatcher

type Wiring = tuple[Dispatcher[ProjectorScope], list[Callable[[ProjectorScope], object]]]


def register_handlers(registry: HandlerRegistry[ProjectorScope]) -> None:
    """Explicit registration: one statement for the one message type, no loop, no decorator."""
    registry.register_command(ProjectFactCommand, ProjectFactHandler)


def _wire() -> Wiring:
    registry = HandlerRegistry[ProjectorScope]()
    register_handlers(registry)
    return registry.build(otc_projector.application), registry.registered_factories()


def build_dispatcher() -> Dispatcher[ProjectorScope]:
    """Register, then validate against every command and query under the application package.

    Pure (no I/O): `tests/architecture/test_registration_behaviour.py` runs it without a database.
    """
    return _wire()[0]


# --------------------------------------------------------------------------- the externals


class NatsConnection(NatsPublisher, Protocol):
    """What the runtime asks of the NATS client besides publishing."""

    @property
    def is_closed(self) -> bool: ...
    @property
    def is_reconnecting(self) -> bool: ...
    async def drain(self) -> None: ...


class FactSubscriber(Protocol):
    """The subscriber surface the runtime uses (the real one is `KafkaFactSubscriber`)."""

    @property
    def ready(self) -> bool: ...
    async def wait_ready(self) -> None: ...
    async def run(
        self,
        handler: Callable[..., Awaitable[None]],
        stop: asyncio.Event,
    ) -> None: ...


type MongoCollection = AsyncCollection[dict[str, Any]]


async def connect_nats(url: str) -> NatsConnection:
    """Connect with logging callbacks (nothing printed by default). On any failure, including the
    cancellation of the caller's bound, the half-built client is closed, so no task is left."""

    async def error_cb(error: Exception) -> None:
        log.error("NATS error: %r", error)

    async def disconnected_cb() -> None:
        log.warning("NATS disconnected")

    async def reconnected_cb() -> None:
        log.info("NATS reconnected")

    client = NatsClient()
    try:
        await client.connect(
            url,
            error_cb=error_cb,
            disconnected_cb=disconnected_cb,
            reconnected_cb=reconnected_cb,
        )
    except BaseException:
        await client.close()
        raise
    return client


def _mongo_client(uri: str) -> AsyncMongoClient[dict[str, Any]]:
    return AsyncMongoClient(uri)


def _kafka_subscriber(settings: KafkaSettings) -> FactSubscriber:
    return KafkaFactSubscriber(settings)


@dataclass(frozen=True, slots=True)
class Externals:
    wire: Callable[[], Wiring] = _wire
    mongo_client: Callable[[str], AsyncMongoClient[dict[str, Any]]] = _mongo_client
    ensure_indexes: Callable[[MongoCollection], Awaitable[None]] = ensure_indexes
    verify_indexes: Callable[[MongoCollection], Awaitable[None]] = verify_indexes
    migrate: Callable[[MongoCollection], Awaitable[object]] = migrate_timeline_order
    nats_connect: Callable[[str], Awaitable[NatsConnection]] = connect_nats
    subscriber: Callable[[KafkaSettings], FactSubscriber] = field(default=_kafka_subscriber)


# ------------------------------------------------------------------------------------ the runtime


class ProjectorRuntime:
    """What the lifespan holds while the service runs."""

    def __init__(
        self,
        *,
        settings: ProjectorSettings,
        dispatcher: Dispatcher[ProjectorScope],
        tasks: dict[str, asyncio.Task[None]],
        subscriber: FactSubscriber,
        connection: NatsConnection,
        stop_event: asyncio.Event,
        stack: AsyncExitStack,
        stop_grace_seconds: float = STOP_GRACE_SECONDS,
    ) -> None:
        self.settings = settings
        self.dispatcher = dispatcher
        self.tasks = tasks
        self.subscriber = subscriber
        self.connection = connection
        self._stop_event = stop_event
        self._stack = stack
        self._stop_grace_seconds = stop_grace_seconds
        self._stopping = False
        for name, task in tasks.items():
            task.add_done_callback(functools.partial(self._on_task_done, name))

    def _on_task_done(self, name: str, task: asyncio.Task[None]) -> None:
        if self._stopping:
            return
        if task.cancelled():
            log.error("transport task %s was cancelled while the service was running", name)
        elif (error := task.exception()) is not None:
            log.error("transport task %s died", name, exc_info=error)
        else:
            log.error("transport task %s ended while the service was running", name)

    def unready_reasons(self) -> list[str]:
        """Empty when ready. A transport task that is done while running is a reason (read live
        from the task, not from a callback that may not have run yet), and so are a consumer that
        has not joined its group and a NATS connection that is closed or reconnecting."""
        if self._stopping:
            return ["the service is shutting down"]
        reasons = [
            f"transport task {name} is not running" for name, t in self.tasks.items() if t.done()
        ]
        if not self.subscriber.ready:
            reasons.append("the Kafka fact consumer has not joined its group")
        if self.connection.is_closed:
            reasons.append("the NATS connection is closed")
        elif self.connection.is_reconnecting:
            reasons.append("the NATS connection is reconnecting")
        return reasons

    async def stop(self) -> None:
        """Stop the task (after its in-flight record), then close what `start_runtime` opened."""
        self._stopping = True
        await _stop_tasks(self._stop_event, self.tasks, self._stop_grace_seconds)
        await self._stack.aclose()


async def _close_nats(connection: NatsConnection) -> None:
    with suppress(nats.errors.Error):
        await connection.drain()


async def _stop_tasks(
    stop_event: asyncio.Event,
    tasks: dict[str, asyncio.Task[None]],
    grace_seconds: float = STOP_GRACE_SECONDS,
) -> None:
    """Ask the tasks to end and await every one. A task that has not ended after the grace period
    (a consumer stuck in `start()`, a handler that never answers) is CANCELLED and awaited: the
    lifespan must end. A failure is logged, never swallowed silently."""
    stop_event.set()
    if tasks:
        _, pending = await asyncio.wait(tasks.values(), timeout=grace_seconds)
        for task in pending:
            task.cancel()
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for name, result in zip(tasks, results, strict=True):
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            log.error("transport task %s ended with an error", name, exc_info=result)


async def _await_consumer_ready(
    subscriber: FactSubscriber, task: asyncio.Task[None], timeout_seconds: float
) -> None:
    """Return once the consumer is ready; raise what ended the task, or `TimeoutError`."""
    waiter = asyncio.create_task(subscriber.wait_ready(), name="fact-consumer ready waiter")
    try:
        done, _ = await asyncio.wait(
            {waiter, task}, timeout=timeout_seconds, return_when=asyncio.FIRST_COMPLETED
        )
        if waiter in done:
            return
        if task in done:
            task.result()  # raises the consumer's own error
            raise RuntimeError("the Kafka fact consumer ended before it was ready")
        raise TimeoutError(
            f"the Kafka fact consumer did not join its group within {timeout_seconds} s"
        )
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


async def start_runtime(
    settings: ProjectorSettings,
    *,
    externals: Externals | None = None,
    consumer_startup_seconds: float = CONSUMER_STARTUP_SECONDS,
    stop_grace_seconds: float = STOP_GRACE_SECONDS,
    nats_connect_seconds: float = NATS_CONNECT_SECONDS,
) -> ProjectorRuntime:
    outside = externals if externals is not None else Externals()
    async with AsyncExitStack() as stack:
        # 1. The dispatcher is validated before anything is opened: a missing or duplicate handler
        #    is a boot failure that cost no connection.
        dispatcher, registered_factories = outside.wire()

        # 2. MongoDB, with a real round trip (an unreachable or unauthenticated server fails here).
        client = outside.mongo_client(settings.mongo.uri)
        stack.push_async_callback(client.close)
        database = client.get_database(settings.mongo.database)
        await database.command("ping")
        collection = database.get_collection(COLLECTION)

        # 3. Indexes, created then verified against the server's stored specification.
        await outside.ensure_indexes(collection)
        await outside.verify_indexes(collection)

        # 4. Bring every document to the current timeline-order version before consuming.
        await outside.migrate(collection)

        # 5. NATS, within a bound: with `PR19` swallowing a failed publish, an unreachable broker
        #    must fail the boot, not run with every signal lost.
        try:
            async with asyncio.timeout(nats_connect_seconds):
                connection = await outside.nats_connect(settings.nats.url)
        except TimeoutError as error:
            raise RuntimeError(
                f"NATS_URL {settings.nats.url} did not accept a connection within "
                f"{nats_connect_seconds} s: the update signal cannot be published"
            ) from error
        stack.push_async_callback(_close_nats, connection)

        # 6. The adapters, and every registered factory built once so a missing binding raises
        #    here, never as an AttributeError on the first message.
        idempotent_consumer = IdempotentConsumer(collection)
        writer = MongoReadModelWriter(collection, idempotent_consumer)
        publisher = NatsUpdateSignalPublisher(connection)

        def scope_factory() -> ProjectorScope:
            return ProjectorScope(read_model=writer, signals=publisher)

        for factory in registered_factories:
            factory(scope_factory())

        subscriber = outside.subscriber(settings.kafka)
        consumer = ProjectorFactsConsumerTask(
            subscriber=subscriber, dispatcher=dispatcher, scope_factory=scope_factory
        )
        stop_event = asyncio.Event()
        tasks: dict[str, asyncio.Task[None]] = {}
        # 7. Every step from here on can fail (Kafka down at boot) and a task may already exist: a
        #    failure stops and awaits the task FIRST, then the stack closes what it used.
        try:
            tasks["fact-consumer"] = asyncio.create_task(
                consumer.run(stop_event), name="fact-consumer"
            )
            await _await_consumer_ready(
                subscriber, tasks["fact-consumer"], consumer_startup_seconds
            )
            # 8. The runtime is built BEFORE the stack is handed over: a constructor that raises
            #    still finds everything owned by `stack`. `pop_all()` is the last statement.
            owned = AsyncExitStack()
            runtime = ProjectorRuntime(
                settings=settings,
                dispatcher=dispatcher,
                tasks=tasks,
                subscriber=subscriber,
                connection=connection,
                stop_event=stop_event,
                stack=owned,
                stop_grace_seconds=stop_grace_seconds,
            )
            owned.push_async_callback(stack.pop_all().aclose)
        except BaseException:
            await _stop_tasks(stop_event, tasks, stop_grace_seconds)
            raise
    return runtime
