"""The composition root of the Orders service: the only place adapters are chosen.

* Configuration is read through pydantic-settings ONLY (`load_settings`); no other module of the
  service touches the environment (`tests/architecture/test_composition_env_reads.py`).
* Handlers are registered explicitly, one statement each, in `register_handlers`; the registry is
  validated by `build_dispatcher` (a command with zero handlers or two fails the boot).
* `start_runtime` is what the lifespan runs: it validates the deployment, builds every adapter,
  proves the bindings, and starts the transport tasks. Everything it opens is owned by one
  `AsyncExitStack`, so a failure at any step closes what was already opened, and `stop()` closes
  everything in reverse order. The engine, the NATS client and the Kafka producer are created in the
  loop that runs the lifespan and closed in it.
* One asyncio task per transport (the NATS responder, the outbox relay) and the saga's three (the
  fast path, the sweeper, the Kafka fact consumer), created here, owned by the runtime and awaited
  on shutdown. A task that ends while the runtime is running takes readiness down
  (`OrdersRuntime.unready_reasons`, served by `/health/ready`). The saga's tasks are stopped in
  REVERSE start order, each awaited before the next is asked to stop: the consumer finishes its
  in-flight record (handler and commit), the sweeper its batch, the fast path cancels its in-flight
  dispatches, and only then do the responder and the relay stop and the stack closes NATS and the
  engine that every one of them uses (`order_saga_orchestrator/design.md` 12.1).
* At most one outbox relay per process, and no multi-worker server while the relay is enabled
  (`outbox_and_idempotency/design.md` 5.2: two relays can publish one order's facts out of order).
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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import otc_orders.application
import otc_orders.application.saga.fact_commands as fact_commands_module
from otc_cqrs import Dispatcher, HandlerRegistry
from otc_orders.application.commands.place_order import PlaceOrderCommand, PlaceOrderCommandHandler
from otc_orders.application.saga.dispatch_events import (
    CreditRejectionRecorded,
    OrderConfirmedBySaga,
    OrderMarkedDespatched,
    OrderMarkedStockReserved,
    OrderPlacedFactRecorded,
)
from otc_orders.application.saga.fact_command_handlers import SagaFactCommandHandler
from otc_orders.application.saga.fact_commands import (
    HandleCreditApprovedFactCommand,
    HandleCreditRejectedFactCommand,
    HandleCreditReleasedFactCommand,
    HandleInvoiceIssuedFactCommand,
    HandleOrderDespatchedFactCommand,
    HandleOrderPlacedFactCommand,
    HandlePaymentReceivedFactCommand,
    HandleStockRejectedFactCommand,
    HandleStockReleasedFactCommand,
    HandleStockReservedFactCommand,
)
from otc_orders.application.saga.order_sagas import (
    CreditApprovedSaga,
    CreditRejectedSaga,
    OrderDespatchedSaga,
    OrderPlacedSaga,
    StockReservedSaga,
)
from otc_orders.application.scope import OrdersScope
from otc_orders.infrastructure.clock import SystemClock
from otc_orders.infrastructure.messaging.kafka_fact_subscriber import KafkaFactSubscriber
from otc_orders.infrastructure.messaging.nats_saga_commands import NatsSagaCommandsAdapter
from otc_orders.infrastructure.messaging.nats_stock_availability import NatsStockAvailability
from otc_orders.infrastructure.outbox.kafka_publisher import KafkaFactPublisher
from otc_orders.infrastructure.outbox.relay import OutboxRelay
from otc_orders.infrastructure.outbox.relay_task import OutboxRelayTask
from otc_orders.infrastructure.outbox.writer import OutboxWriter
from otc_orders.infrastructure.persistence.reference_catalog import SqlAlchemyReferenceCatalog
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_orders.infrastructure.saga.command_dispatcher import SagaCommandDispatcher
from otc_orders.infrastructure.saga.command_ledger import SqlAlchemySagaCommandLedger
from otc_orders.infrastructure.saga.fact_consumption import SqlAlchemyFactConsumption
from otc_orders.infrastructure.saga.fast_path import SagaFastPath
from otc_orders.infrastructure.saga.sweeper import SagaCommandSweeper
from otc_orders.infrastructure.saga.sweeper_task import SagaCommandSweeperTask
from otc_orders.infrastructure.settings import (
    KafkaSettings,
    NatsSettings,
    OrdersDatabaseSettings,
    OutboxRelaySettings,
    SagaSettings,
    ServerSettings,
)
from otc_orders.presentation.orders_create_responder import OrdersCreateResponder
from otc_orders.presentation.saga_facts_consumer import SagaFactsConsumerTask

log = logging.getLogger("otc_orders.composition")


@dataclass(frozen=True, slots=True)
class OrdersSettings:
    """Every settings class of the service, each constructed exactly once, here."""

    database: OrdersDatabaseSettings
    outbox: OutboxRelaySettings
    kafka: KafkaSettings
    nats: NatsSettings
    saga: SagaSettings
    server: ServerSettings


def load_settings() -> OrdersSettings:
    return OrdersSettings(
        database=OrdersDatabaseSettings(),
        outbox=OutboxRelaySettings(),
        kafka=KafkaSettings(),
        nats=NatsSettings(),
        saga=SagaSettings(),
        server=ServerSettings(),
    )


# ------------------------------------------------------------------------------ the dispatcher


def register_handlers(registry: HandlerRegistry[OrdersScope]) -> None:
    """Explicit registration: one statement per message type, no loop, no decorator."""
    registry.register_command(PlaceOrderCommand, PlaceOrderCommandHandler)
    # The saga's ten fact commands: one handler class, registered once per command.
    registry.register_command(HandleOrderPlacedFactCommand, SagaFactCommandHandler)
    registry.register_command(HandleStockReservedFactCommand, SagaFactCommandHandler)
    registry.register_command(HandleStockRejectedFactCommand, SagaFactCommandHandler)
    registry.register_command(HandleStockReleasedFactCommand, SagaFactCommandHandler)
    registry.register_command(HandleCreditApprovedFactCommand, SagaFactCommandHandler)
    registry.register_command(HandleCreditRejectedFactCommand, SagaFactCommandHandler)
    registry.register_command(HandleOrderDespatchedFactCommand, SagaFactCommandHandler)
    registry.register_command(HandleInvoiceIssuedFactCommand, SagaFactCommandHandler)
    registry.register_command(HandlePaymentReceivedFactCommand, SagaFactCommandHandler)
    registry.register_command(HandleCreditReleasedFactCommand, SagaFactCommandHandler)
    # The five dispatch-owed events, each signalling its own command to the fast path. A missing
    # statement here would silently drop the fast path (an event with no handler is not a boot
    # error), so `unit/saga/test_order_sagas.py` publishes each through the built dispatcher.
    registry.register_event(
        OrderPlacedFactRecorded, lambda scope: OrderPlacedSaga(scope.required_saga_signal())
    )
    registry.register_event(
        OrderMarkedStockReserved, lambda scope: StockReservedSaga(scope.required_saga_signal())
    )
    registry.register_event(
        CreditRejectionRecorded, lambda scope: CreditRejectedSaga(scope.required_saga_signal())
    )
    registry.register_event(
        OrderConfirmedBySaga, lambda scope: CreditApprovedSaga(scope.required_saga_signal())
    )
    registry.register_event(
        OrderMarkedDespatched, lambda scope: OrderDespatchedSaga(scope.required_saga_signal())
    )


def _wire() -> tuple[Dispatcher[OrdersScope], list[Callable[[OrdersScope], object]]]:
    registry = HandlerRegistry[OrdersScope]()
    register_handlers(registry)
    return (
        registry.build(otc_orders.application, fact_commands_module),
        registry.registered_factories(),
    )


def build_dispatcher() -> Dispatcher[OrdersScope]:
    """Register, then validate against every command and query under `otc_orders.application`.

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
    """Refuse a deployment that would run more than one relay (design.md 5.2).

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


class OrdersRuntime:
    """What the lifespan holds while the service runs."""

    def __init__(
        self,
        *,
        settings: OrdersSettings,
        dispatcher: Dispatcher[OrdersScope],
        tasks: dict[str, asyncio.Task[None]],
        connection: Client,
        stages: list[StopStage],
        stack: AsyncExitStack,
    ) -> None:
        self.settings = settings
        self.dispatcher = dispatcher
        self.tasks = tasks
        self.connection = connection
        self._stages = stages
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
        await _stop_stages(self._stages, self.tasks)
        await self._stack.aclose()


async def _close_nats(connection: Client) -> None:
    with suppress(nats.errors.Error):
        await connection.drain()


@dataclass(frozen=True, slots=True)
class StopStage:
    """The tasks that share one stop signal. Stages are listed in START order and stopped in
    REVERSE: each stage's tasks are awaited before the next stage is asked to stop."""

    event: asyncio.Event
    names: tuple[str, ...]


async def _stop_stages(stages: list[StopStage], tasks: dict[str, asyncio.Task[None]]) -> None:
    """Ask each stage's tasks to end, last started first, and await them before moving on (a
    failure is logged, never swallowed silently). `start_runtime` runs it when a step fails after a
    task was created; `OrdersRuntime.stop` runs it on shutdown."""
    for stage in reversed(stages):
        stage.event.set()
        results = await asyncio.gather(*(tasks[n] for n in stage.names), return_exceptions=True)
        for name, result in zip(stage.names, results, strict=True):
            if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                log.error("transport task %s ended with an error", name, exc_info=result)


async def start_runtime(settings: OrdersSettings) -> OrdersRuntime:
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

        engine = create_async_engine(settings.database.url)
        stack.push_async_callback(engine.dispose)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        clock = SystemClock()

        connection = await nats.connect(settings.nats.url)
        stack.push_async_callback(_close_nats, connection)

        unit_of_work = SqlAlchemyUnitOfWork(
            sessions=sessions, outbox=OutboxWriter(clock=clock), clock=clock
        )
        catalog = SqlAlchemyReferenceCatalog(sessions)
        stock = NatsStockAvailability(connection, timeout_ms=settings.nats.stock_check_timeout_ms)

        # The saga (feature 16): ONE adapter over the one NATS connection (no second connection),
        # one dispatcher, one fast path, one sweeper, over the lifespan's own session factory.
        saga = settings.saga
        ledger = SqlAlchemySagaCommandLedger(
            sessions, clock, lease_ms=saga.command_lease_ms, pending_grace_ms=saga.pending_grace_ms
        )
        saga_dispatcher = SagaCommandDispatcher(
            ledger=ledger,
            commands=NatsSagaCommandsAdapter(connection, timeout_ms=saga.command_timeout_ms),
            clock=clock,
            max_attempts=saga.command_max_attempts,
            backoff_ms=saga.command_backoff_ms,
            park_cap_ms=saga.park_retry_cap_ms,
        )
        fast_path = SagaFastPath(
            dispatcher=saga_dispatcher, max_in_flight=saga.fast_path_max_in_flight
        )
        fact_consumption = SqlAlchemyFactConsumption(unit_of_work, clock)

        def scope_factory() -> OrdersScope:
            return OrdersScope(
                unit_of_work=unit_of_work,
                catalog=catalog,
                stock=stock,
                clock=clock,
                dispatcher=dispatcher,
                fact_consumption=fact_consumption,
                saga_signal=fast_path,
            )

        # Every binding is proven at boot, never on the first message: the scope refuses a port
        # that is bound to nothing, and each registered handler is built once.
        for factory in registered_factories:
            factory(scope_factory())

        responder = OrdersCreateResponder(
            connection=connection, dispatcher=dispatcher, scope_factory=scope_factory, clock=clock
        )
        await responder.start()

        stop_event = asyncio.Event()
        tasks: dict[str, asyncio.Task[None]] = {}
        stages: list[StopStage] = [StopStage(stop_event, ())]
        # Every step from here on can fail (Kafka down at boot) and a task may already exist: a
        # failure stops and awaits the tasks FIRST, then the stack closes what they used.
        try:
            tasks["nats-responder"] = asyncio.create_task(
                responder.run(stop_event), name="nats-responder"
            )
            stages[0] = StopStage(stop_event, ("nats-responder",))
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
                stages[0] = StopStage(stop_event, ("nats-responder", "outbox-relay"))
            # The saga's three tasks, in start order: the fast path, the sweeper, then the consumer
            # (last, so its first signal finds the fast path running). Each has its own stop signal.
            fast_path_stop = asyncio.Event()
            tasks["saga-fast-path"] = asyncio.create_task(
                fast_path.run(fast_path_stop), name="saga-fast-path"
            )
            stages.append(StopStage(fast_path_stop, ("saga-fast-path",)))
            if saga.sweeper_enabled:
                sweeper_stop = asyncio.Event()
                sweeper_task = SagaCommandSweeperTask(
                    SagaCommandSweeper(
                        ledger=ledger,
                        dispatcher=saga_dispatcher,
                        batch_limit=saga.sweeper_batch_limit,
                    ),
                    interval=saga.sweeper_interval_seconds,
                    enabled=True,
                )
                tasks["saga-sweeper"] = asyncio.create_task(
                    sweeper_task.run(sweeper_stop), name="saga-sweeper"
                )
                stages.append(StopStage(sweeper_stop, ("saga-sweeper",)))
            else:
                log.warning(
                    "SAGA_SWEEPER_ENABLED=false: owed commands are issued by the fast path only"
                )
            if saga.consumer_enabled:
                consumer_stop = asyncio.Event()
                consumer_task = SagaFactsConsumerTask(
                    subscriber=KafkaFactSubscriber(settings.kafka),
                    dispatcher=dispatcher,
                    scope_factory=scope_factory,
                )
                tasks["saga-consumer"] = asyncio.create_task(
                    consumer_task.run(consumer_stop), name="saga-consumer"
                )
                stages.append(StopStage(consumer_stop, ("saga-consumer",)))
            else:
                log.warning("SAGA_CONSUMER_ENABLED=false: this process consumes no facts")
            # The runtime is built BEFORE the stack is handed over: a constructor that raises
            # still finds everything owned by `stack`. `pop_all()` is the last statement.
            owned = AsyncExitStack()
            runtime = OrdersRuntime(
                settings=settings,
                dispatcher=dispatcher,
                tasks=tasks,
                connection=connection,
                stages=stages,
                stack=owned,
            )
            owned.push_async_callback(stack.pop_all().aclose)
        except BaseException:
            await _stop_stages(stages, tasks)
            raise
    return runtime
