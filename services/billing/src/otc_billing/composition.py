"""The composition root of the Billing service: the only place adapters are chosen.

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
  down (`BillingRuntime.readiness`, served by `/health/ready`).
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
from collections.abc import Callable, Mapping, Sequence
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass

import nats
import nats.errors
from nats.aio.client import Client
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.trace import SpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

import otc_billing.application
from otc_billing.application.handlers import (
    HoldCreditHandler,
    IssueInvoiceHandler,
    ListCreditHandler,
    ListInvoicesHandler,
    RegisterPaymentHandler,
    ReleaseCreditHandler,
)
from otc_billing.application.messages import (
    HoldCreditCommand,
    IssueInvoiceCommand,
    ListCreditQuery,
    ListInvoicesQuery,
    RegisterPaymentCommand,
    ReleaseCreditCommand,
)
from otc_billing.application.ports.credit_decision import CreditDecisionPort
from otc_billing.application.scope import BillingScope
from otc_billing.infrastructure.clock import SystemClock
from otc_billing.infrastructure.credit.simulator import SimulatorCreditDecision
from otc_billing.infrastructure.health.checks import (
    CheckResult,
    HealthCheck,
    Probe,
    dead_tasks,
    run_checks,
)
from otc_billing.infrastructure.health.nats_probe import NatsProbe
from otc_billing.infrastructure.health.postgres_probe import PostgresProbe
from otc_billing.infrastructure.ids import UuidIdSource
from otc_billing.infrastructure.observability.metrics import outbox_lag
from otc_billing.infrastructure.observability.telemetry import build_telemetry
from otc_billing.infrastructure.outbox.kafka_publisher import KafkaFactPublisher
from otc_billing.infrastructure.outbox.relay import OutboxRelay
from otc_billing.infrastructure.outbox.relay_task import OutboxRelayTask
from otc_billing.infrastructure.outbox.writer import OutboxWriter
from otc_billing.infrastructure.persistence.credit_reads import SqlAlchemyCreditReads
from otc_billing.infrastructure.persistence.credit_transactions import (
    SqlAlchemyCreditTransactions,
)
from otc_billing.infrastructure.persistence.invoice_reads import SqlAlchemyInvoiceReads
from otc_billing.infrastructure.settings import (
    BillingDatabaseSettings,
    CreditSimulatorSettings,
    KafkaSettings,
    NatsSettings,
    OutboxRelaySettings,
    ResponderSettings,
    ServerSettings,
    TelemetrySettings,
)
from otc_billing.presentation.credit_responder import CreditResponder
from otc_cqrs import Dispatcher, HandlerRegistry

log = logging.getLogger("otc_billing.composition")


@dataclass(frozen=True, slots=True)
class BillingSettings:
    """Every settings class of the service, each constructed exactly once, here."""

    database: BillingDatabaseSettings
    outbox: OutboxRelaySettings
    kafka: KafkaSettings
    nats: NatsSettings
    server: ServerSettings
    responder: ResponderSettings
    credit_simulator: CreditSimulatorSettings
    telemetry: TelemetrySettings


def load_settings() -> BillingSettings:
    return BillingSettings(
        database=BillingDatabaseSettings(),
        outbox=OutboxRelaySettings(),
        kafka=KafkaSettings(),
        nats=NatsSettings(),
        server=ServerSettings(),
        responder=ResponderSettings(),
        credit_simulator=CreditSimulatorSettings(),
        telemetry=TelemetrySettings(),
    )


# ------------------------------------------------------------------------------ the dispatcher


def register_handlers(registry: HandlerRegistry[BillingScope]) -> None:
    """Explicit registration: one statement per message type, no loop, no decorator."""
    registry.register_query(ListCreditQuery, ListCreditHandler)
    registry.register_command(HoldCreditCommand, HoldCreditHandler)
    registry.register_command(ReleaseCreditCommand, ReleaseCreditHandler)
    registry.register_command(IssueInvoiceCommand, IssueInvoiceHandler)
    registry.register_query(ListInvoicesQuery, ListInvoicesHandler)
    registry.register_command(RegisterPaymentCommand, RegisterPaymentHandler)


def _wire() -> tuple[Dispatcher[BillingScope], list[Callable[[BillingScope], object]]]:
    registry = HandlerRegistry[BillingScope]()
    register_handlers(registry)
    return registry.build(otc_billing.application), registry.registered_factories()


def build_dispatcher() -> Dispatcher[BillingScope]:
    """Register, then validate against every command and query under `otc_billing.application`.

    Pure (no I/O): `tests/architecture/test_registration_behaviour.py` runs it without a database.
    """
    return _wire()[0]


# ------------------------------------------------------------------------------------ readiness


def build_health_checks(
    *,
    tasks: Mapping[str, asyncio.Task[None]],
    write_model: Probe,
    rpc_transport: Probe,
) -> list[HealthCheck]:
    """The runtime's checks (`R60`), each task attributed to the dependency it serves: the relay
    drains the write model's outbox (`writeModel`), the responder serves `rpcTransport`. No
    fact-stream check: with Kafka down this service still accepts commands and commits its facts
    durably, and withdrawing it would stop the saga for nothing (the outbox lag is the signal,
    `R59`)."""
    return [
        HealthCheck("writeModel", write_model, task_reasons=dead_tasks(tasks, ("outbox-relay",))),
        HealthCheck(
            "rpcTransport", rpc_transport, task_reasons=dead_tasks(tasks, ("nats-responder",))
        ),
    ]


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


class BillingRuntime:
    """What the lifespan holds while the service runs."""

    def __init__(
        self,
        *,
        settings: BillingSettings,
        dispatcher: Dispatcher[BillingScope],
        tasks: dict[str, asyncio.Task[None]],
        connection: Client,
        engine: AsyncEngine,
        responder: CreditResponder,
        stop_event: asyncio.Event,
        stack: AsyncExitStack,
        checks: Sequence[HealthCheck] = (),
    ) -> None:
        self.settings = settings
        self.checks = checks
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

    async def readiness(self) -> list[CheckResult]:
        """One bounded check per dependency (`R60`, served by `/health/ready`). A task that is done
        while running makes the check of the dependency it serves `down`, read live from the task
        (not from a callback that may not have run yet); a runtime that is stopping answers `down`
        for every check without probing. No fact-stream check: with Kafka down this service still
        accepts commands and commits its facts durably, and withdrawing it would stop the saga for
        nothing; the outbox lag is the signal (`R59`). The relay task serves the write model's
        outbox, so its death is attributed to `writeModel`."""
        return await run_checks(self.checks, shutting_down=self._stopping)

    async def stop(self) -> None:
        """Stop the tasks (after their in-flight work), then close what `start_runtime` opened."""
        self._stopping = True
        await _stop_tasks(self._stop_event, self.tasks)
        await self._stack.aclose()


# `nats.connect` with its defaults keeps retrying 60 x 2 s before raising (measured: still
# connecting after 60 s), so the boot's connection is bounded here; reconnects at runtime keep the
# client's defaults (backlog 214, as the projector's `PR45`).
NATS_CONNECT_SECONDS = 10.0


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


async def start_runtime(
    settings: BillingSettings,
    *,
    credit_decision: CreditDecisionPort | None = None,
    nats_connect_seconds: float = NATS_CONNECT_SECONDS,
    span_processors: Sequence[SpanProcessor] = (),
    metric_readers: Sequence[MetricReader] = (),
) -> BillingRuntime:
    async with AsyncExitStack() as stack:
        # This runtime's own tracer and meter providers (`R56`), first so that everything below can
        # make spans, and closed LAST (the stack unwinds in reverse, so the flush follows every
        # adapter's close). Never the process-global provider (`telemetry.py`).
        telemetry = build_telemetry(
            "billing",
            settings.telemetry.otlp_endpoint,
            span_processors=span_processors,
            metric_readers=metric_readers,
        )
        stack.push_async_callback(telemetry.aclose)

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

        try:
            async with asyncio.timeout(nats_connect_seconds):
                connection = await nats.connect(settings.nats.url)
        except TimeoutError as error:
            raise RuntimeError(
                f"NATS_URL {settings.nats.url} did not accept a connection within "
                f"{nats_connect_seconds} s"
            ) from error
        stack.push_async_callback(_close_nats, connection)

        transactions = SqlAlchemyCreditTransactions(
            sessions=sessions,
            outbox=OutboxWriter(clock=clock),
            clock=clock,
            tracer=telemetry.tracer,
        )
        reads = SqlAlchemyCreditReads(sessions)
        invoice_reads = SqlAlchemyInvoiceReads(sessions)
        ids = UuidIdSource()
        # The one place the credit-decision adapter is chosen (BC15): the simulator is the default
        # binding, as in #7 (`app.module.ts`) and #8 (`BillingProgramConfiguration.cs`); at rate 0
        # it approves everything the aggregate lets through. `AlwaysApproveCreditDecision` stays in
        # the tree for tests that want no simulation at all.
        decision = credit_decision or SimulatorCreditDecision(
            settings.credit_simulator.failure_rate
        )

        def scope_factory() -> BillingScope:
            return BillingScope(
                transactions=transactions,
                reads=reads,
                invoice_reads=invoice_reads,
                clock=clock,
                ids=ids,
                credit_decision=decision,
            )

        # Every binding is proven at boot, never on the first message: the scope refuses a port
        # that is bound to nothing, and each registered handler is built once.
        for factory in registered_factories:
            factory(scope_factory())

        responder = CreditResponder(
            connection=connection,
            dispatcher=dispatcher,
            scope_factory=scope_factory,
            clock=clock,
            max_concurrent_requests=bound,
            tracer=telemetry.tracer,
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
                    tracer=telemetry.tracer,
                    lag=outbox_lag(telemetry.meter),
                )
                relay_task = OutboxRelayTask(
                    relay, poll_interval=settings.outbox.poll_interval_seconds, enabled=True
                )
                tasks["outbox-relay"] = asyncio.create_task(
                    relay_task.run(stop_event), name="outbox-relay"
                )
            # Readiness (`R60`): the write model and the RPC transport, each bounded.
            postgres_probe = PostgresProbe(settings.database.url)
            stack.push_async_callback(postgres_probe.aclose)
            checks = build_health_checks(
                tasks=tasks, write_model=postgres_probe, rpc_transport=NatsProbe(connection)
            )
            # The runtime is built BEFORE the stack is handed over: a constructor that raises
            # still finds everything owned by `stack`. `pop_all()` is the last statement.
            owned = AsyncExitStack()
            runtime = BillingRuntime(
                settings=settings,
                dispatcher=dispatcher,
                tasks=tasks,
                connection=connection,
                engine=engine,
                responder=responder,
                stop_event=stop_event,
                stack=owned,
                checks=checks,
            )
            owned.push_async_callback(stack.pop_all().aclose)
        except BaseException:
            await _stop_tasks(stop_event, tasks)
            raise
    return runtime
