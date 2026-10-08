"""The composition root of the Fulfillment service: the only place adapters are chosen.

* Configuration is read through pydantic-settings ONLY (`load_settings`); no other module of the
  service touches the environment (`tests/architecture/test_composition_env_reads.py`).
* Handlers are registered explicitly, one statement each, in `register_handlers`; the registry is
  validated by `build_dispatcher` (a command or query with zero handlers or two fails the boot).
* `start_runtime` is what the lifespan runs: it validates the deployment, builds every adapter,
  proves the bindings, and starts the transport tasks. Everything it opens is owned by one
  `AsyncExitStack`, so a failure at any step closes what was already opened, and `stop()` closes
  everything in reverse order. The engine, the NATS client and the Kafka producer are created in the
  loop that runs the lifespan and closed in it.
* One asyncio task per transport (the NATS responder, the outbox relay), created here, owned by the
  runtime and awaited on shutdown. A task that ends while the runtime is running takes readiness
  down (`FulfillmentRuntime.unready_reasons`, served by `/health/ready`).
* The engine's pool is sized from the responder's bound: `pool_size = bound + 1` (the relay's
  session), `max_overflow = 0`, so an admitted request never waits for a connection (`design.md`
  8.2).
* At most one outbox relay per process, and no multi-worker server while the relay is enabled
  (`outbox_and_idempotency/design.md` 5.2). The guard is a COPY of Orders' (`composition.py`), not a
  shared module: there is no fourth shared runtime package.
"""

import asyncio
import functools
import logging
import multiprocessing
from collections.abc import Callable
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass

import nats
import nats.errors
from nats.aio.client import Client
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

import otc_fulfillment.application
from otc_cqrs import Dispatcher, HandlerRegistry
from otc_fulfillment.application.handlers import (
    CheckStockHandler,
    CreateDespatchHandler,
    ListStockHandler,
    ReleaseStockHandler,
    ReplenishStockHandler,
    ReserveStockHandler,
)
from otc_fulfillment.application.messages import (
    CheckStockQuery,
    CreateDespatchCommand,
    ListStockQuery,
    ReleaseStockCommand,
    ReplenishStockCommand,
    ReserveStockCommand,
)
from otc_fulfillment.application.scope import FulfillmentScope
from otc_fulfillment.infrastructure.clock import SystemClock
from otc_fulfillment.infrastructure.ids import UuidIdSource
from otc_fulfillment.infrastructure.outbox.kafka_publisher import KafkaFactPublisher
from otc_fulfillment.infrastructure.outbox.relay import OutboxRelay
from otc_fulfillment.infrastructure.outbox.relay_task import OutboxRelayTask
from otc_fulfillment.infrastructure.outbox.writer import OutboxWriter
from otc_fulfillment.infrastructure.persistence.stock_reads import SqlAlchemyStockReads
from otc_fulfillment.infrastructure.persistence.stock_transactions import (
    SqlAlchemyStockTransactions,
)
from otc_fulfillment.infrastructure.settings import (
    FulfillmentDatabaseSettings,
    KafkaSettings,
    NatsSettings,
    OutboxRelaySettings,
    ResponderSettings,
    ServerSettings,
)
from otc_fulfillment.presentation.stock_responder import StockResponder

log = logging.getLogger("otc_fulfillment.composition")


@dataclass(frozen=True, slots=True)
class FulfillmentSettings:
    """Every settings class of the service, each constructed exactly once, here."""

    database: FulfillmentDatabaseSettings
    outbox: OutboxRelaySettings
    kafka: KafkaSettings
    nats: NatsSettings
    server: ServerSettings
    responder: ResponderSettings


def load_settings() -> FulfillmentSettings:
    return FulfillmentSettings(
        database=FulfillmentDatabaseSettings(),
        outbox=OutboxRelaySettings(),
        kafka=KafkaSettings(),
        nats=NatsSettings(),
        server=ServerSettings(),
        responder=ResponderSettings(),
    )


# ------------------------------------------------------------------------------ the dispatcher


def register_handlers(registry: HandlerRegistry[FulfillmentScope]) -> None:
    """Explicit registration: one statement per message type, no loop, no decorator."""
    registry.register_query(CheckStockQuery, CheckStockHandler)
    registry.register_query(ListStockQuery, ListStockHandler)
    registry.register_command(ReserveStockCommand, ReserveStockHandler)
    registry.register_command(ReleaseStockCommand, ReleaseStockHandler)
    registry.register_command(ReplenishStockCommand, ReplenishStockHandler)
    registry.register_command(CreateDespatchCommand, CreateDespatchHandler)


def _wire() -> tuple[Dispatcher[FulfillmentScope], list[Callable[[FulfillmentScope], object]]]:
    registry = HandlerRegistry[FulfillmentScope]()
    register_handlers(registry)
    return registry.build(otc_fulfillment.application), registry.registered_factories()


def build_dispatcher() -> Dispatcher[FulfillmentScope]:
    """Register, then validate against every command and query under `otc_fulfillment.application`.

    Pure (no I/O): `tests/architecture/test_registration_behaviour.py` runs it without a database.
    """
    return _wire()[0]


# --------------------------------------------------------------------- one relay per deployment

_relay_owner: object | None = None


class MultipleOutboxRelaysError(RuntimeError):
    """A second outbox relay would run: in this process or in a sibling worker process."""


def assert_single_outbox_relay(
    *, relay_enabled: bool, web_concurrency: int, in_worker_process: bool
) -> None:
    """Refuse a deployment that would run more than one relay (design.md 10.3).

    `web_concurrency` is `WEB_CONCURRENCY` (what uvicorn reads for `--workers`); `in_worker_process`
    is true inside a process `multiprocessing` started, which is how uvicorn runs every worker when
    `--workers` is above one. With the relay disabled any number of workers is fine.
    """
    if not relay_enabled:
        return
    if web_concurrency > 1:
        raise MultipleOutboxRelaysError(
            f"WEB_CONCURRENCY={web_concurrency} with OUTBOX_RELAY_ENABLED=true would run "
            f"{web_concurrency} outbox relays: run one worker, or disable the relay on all "
            "but one replica."
        )
    if in_worker_process:
        raise MultipleOutboxRelaysError(
            "this process is a multi-worker server's worker and OUTBOX_RELAY_ENABLED=true: every "
            "worker would run an outbox relay; run one worker, or disable the relay."
        )


def running_in_worker_process() -> bool:
    """True inside a process `multiprocessing` started (uvicorn's way of running `--workers N`)."""
    return multiprocessing.parent_process() is not None


def _claim_relay_slot(owner: object) -> Callable[[], None]:
    """At most one relay-owning runtime per process; returns the release."""
    global _relay_owner
    if _relay_owner is not None:
        raise MultipleOutboxRelaysError("this process already runs an outbox relay")
    _relay_owner = owner

    def release() -> None:
        global _relay_owner
        if _relay_owner is owner:
            _relay_owner = None

    return release


# ------------------------------------------------------------------------------------ the runtime


class FulfillmentRuntime:
    """What the lifespan holds while the service runs."""

    def __init__(
        self,
        *,
        settings: FulfillmentSettings,
        dispatcher: Dispatcher[FulfillmentScope],
        tasks: dict[str, asyncio.Task[None]],
        connection: Client,
        engine: AsyncEngine,
        responder: StockResponder,
        stop_event: asyncio.Event,
        stack: AsyncExitStack,
    ) -> None:
        self.settings = settings
        self.dispatcher = dispatcher
        self.tasks = tasks
        self.connection = connection
        self.engine = engine
        self.responder = responder
        self._stop_event = stop_event
        self._stack = stack
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
        from the task, not from a callback that may not have run yet)."""
        if self._stopping:
            return ["the service is shutting down"]
        reasons = [
            f"transport task {name} is not running" for name, t in self.tasks.items() if t.done()
        ]
        # The responder's loop waits on an inbox: a closed or reconnecting NATS client would not
        # end it, so the connection itself is a reason (a request could not be answered).
        if self.connection.is_closed:
            reasons.append("the NATS connection is closed")
        elif self.connection.is_reconnecting:
            reasons.append("the NATS connection is reconnecting")
        return reasons

    async def stop(self) -> None:
        """Stop the tasks (after their in-flight work), then close what `start_runtime` opened."""
        self._stopping = True
        await _stop_tasks(self._stop_event, self.tasks)
        await self._stack.aclose()


async def _close_nats(connection: Client) -> None:
    with suppress(nats.errors.Error):
        await connection.drain()


async def _stop_tasks(stop_event: asyncio.Event, tasks: dict[str, asyncio.Task[None]]) -> None:
    """Ask the tasks to end and await every one (a failure is logged, never swallowed silently)."""
    stop_event.set()
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for name, result in zip(tasks, results, strict=True):
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            log.error("transport task %s ended with an error", name, exc_info=result)


async def start_runtime(settings: FulfillmentSettings) -> FulfillmentRuntime:
    async with AsyncExitStack() as stack:
        relay_enabled = settings.outbox.enabled
        assert_single_outbox_relay(
            relay_enabled=relay_enabled,
            web_concurrency=settings.server.web_concurrency,
            in_worker_process=running_in_worker_process(),
        )
        # The dispatcher is validated before anything is opened: a missing or duplicate handler is
        # a boot failure that cost no connection.
        dispatcher, registered_factories = _wire()
        if relay_enabled:
            stack.callback(_claim_relay_slot(stack))

        bound = settings.responder.max_concurrent_requests
        engine = create_async_engine(
            settings.database.url,
            pool_size=bound + 1,  # the responder's sessions, plus the relay's
            max_overflow=0,
        )
        stack.push_async_callback(engine.dispose)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        clock = SystemClock()

        connection = await nats.connect(settings.nats.url)
        stack.push_async_callback(_close_nats, connection)

        transactions = SqlAlchemyStockTransactions(
            sessions=sessions, outbox=OutboxWriter(clock=clock), clock=clock
        )
        reads = SqlAlchemyStockReads(sessions)
        ids = UuidIdSource()

        def scope_factory() -> FulfillmentScope:
            return FulfillmentScope(transactions=transactions, reads=reads, clock=clock, ids=ids)

        # Every binding is proven at boot, never on the first message: the scope refuses a port
        # that is bound to nothing, and each registered handler is built once.
        for factory in registered_factories:
            factory(scope_factory())

        responder = StockResponder(
            connection=connection,
            dispatcher=dispatcher,
            scope_factory=scope_factory,
            clock=clock,
            max_concurrent_requests=bound,
        )
        await responder.start()

        stop_event = asyncio.Event()
        tasks: dict[str, asyncio.Task[None]] = {}
        # Every step from here on can fail (Kafka down at boot) and a task may already exist: a
        # failure stops and awaits the tasks FIRST, then the stack closes what they used.
        try:
            tasks["nats-responder"] = asyncio.create_task(
                responder.run(stop_event), name="nats-responder"
            )
            if relay_enabled:
                publisher = KafkaFactPublisher(settings.kafka)
                await publisher.start()
                stack.push_async_callback(publisher.stop)
                relay = OutboxRelay(
                    sessions=sessions,
                    publisher=publisher,
                    clock=clock,
                    batch_size=settings.outbox.batch_size,
                    publish_timeout=settings.outbox.publish_timeout_seconds,
                )
                relay_task = OutboxRelayTask(
                    relay, poll_interval=settings.outbox.poll_interval_seconds, enabled=True
                )
                tasks["outbox-relay"] = asyncio.create_task(
                    relay_task.run(stop_event), name="outbox-relay"
                )
            # The runtime is built BEFORE the stack is handed over: a constructor that raises
            # still finds everything owned by `stack`. `pop_all()` is the last statement.
            owned = AsyncExitStack()
            runtime = FulfillmentRuntime(
                settings=settings,
                dispatcher=dispatcher,
                tasks=tasks,
                connection=connection,
                engine=engine,
                responder=responder,
                stop_event=stop_event,
                stack=owned,
            )
            owned.push_async_callback(stack.pop_all().aclose)
        except BaseException:
            await _stop_tasks(stop_event, tasks)
            raise
    return runtime
