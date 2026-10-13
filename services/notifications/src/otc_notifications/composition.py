"""The composition root of the Notifications service: the only place adapters are chosen.

* Configuration is read through pydantic-settings ONLY (`load_settings`); no other module of the
  service touches the environment (`tests/architecture/test_composition_env_reads.py`).
* Handlers are registered explicitly, one statement each, in `register_handlers`; the registry is
  validated by `build_dispatcher` (a command or query with zero handlers or two fails the boot).
* `start_runtime` is what the lifespan runs: it validates the dispatcher BEFORE anything is opened,
  builds every adapter, proves the bindings, and starts the transport task. Everything it opens is
  owned by one `AsyncExitStack`, so a failure at any step closes what was already opened, and
  `stop()` closes everything in reverse order. The engine is created in the loop that runs the
  lifespan and disposed in it.
* One asyncio task per transport: the Kafka fact consumer, created here, owned by the runtime and
  awaited on shutdown. This service has NO outbox relay and NO RPC responder: it consumes facts and
  emits none (`tests/unit/test_notifications_consumes_only.py`). A task that ends while the runtime
  is running, or a consumer that has not (yet) joined its group, takes readiness down
  (`NotificationsRuntime.readiness`, served by `/health/ready`).
* `start_runtime` returns only once the consumer has joined its group and resolved its positions
  (or raises what stopped it, or a `TimeoutError`): with `auto_offset_reset=latest`, a fact
  published after the boot returns is guaranteed to be read.
* The sender is chosen here and nowhere else (`build_sender`): the console adapter, or the SMTP
  adapter wrapped by the degrading decorator (never the bare SMTP adapter).
"""

import asyncio
import functools
import logging
from collections.abc import Callable, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass

from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.trace import SpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

import otc_notifications.application
from otc_cqrs import Dispatcher, HandlerRegistry
from otc_notifications.application.handlers import (
    NotifyInvoiceIssuedHandler,
    NotifyOrderCancelledHandler,
    NotifyOrderCompletedHandler,
    NotifyOrderConfirmedHandler,
    NotifyOrderDespatchedHandler,
    NotifyOrderPlacedHandler,
    NotifyPaymentReceivedHandler,
)
from otc_notifications.application.messages import (
    NotifyInvoiceIssuedCommand,
    NotifyOrderCancelledCommand,
    NotifyOrderCompletedCommand,
    NotifyOrderConfirmedCommand,
    NotifyOrderDespatchedCommand,
    NotifyOrderPlacedCommand,
    NotifyPaymentReceivedCommand,
)
from otc_notifications.application.ports.notification_sender import NotificationSender
from otc_notifications.application.scope import NotificationsScope
from otc_notifications.infrastructure.clock import SystemClock
from otc_notifications.infrastructure.health.checks import (
    CheckResult,
    HealthCheck,
    Probe,
    dead_tasks,
    run_checks,
)
from otc_notifications.infrastructure.health.kafka_probe import KafkaAdminProbe
from otc_notifications.infrastructure.health.postgres_probe import PostgresProbe
from otc_notifications.infrastructure.messaging.consumer_name import ConsumerName
from otc_notifications.infrastructure.messaging.dead_letter_publisher import (
    KafkaDeadLetterPublisher,
    ProducerFactory,
)
from otc_notifications.infrastructure.messaging.fact_retry import (
    FactRetry,
    FactRetryPolicy,
    stop_aware_sleep,
)
from otc_notifications.infrastructure.messaging.fact_topics import NOTIFICATION_FACT_TOPICS
from otc_notifications.infrastructure.messaging.kafka_fact_subscriber import KafkaFactSubscriber
from otc_notifications.infrastructure.notification.console_sender import ConsoleNotificationSender
from otc_notifications.infrastructure.notification.degrading_sender import (
    DegradingNotificationSender,
)
from otc_notifications.infrastructure.notification.smtp_sender import SmtpNotificationSender
from otc_notifications.infrastructure.observability.metrics import (
    FactLatencyHistogram,
    fact_processing_latency,
)
from otc_notifications.infrastructure.observability.telemetry import build_telemetry
from otc_notifications.infrastructure.persistence.delivery_ledger import SqlAlchemyDeliveryLedger
from otc_notifications.infrastructure.settings import (
    FactRetrySettings,
    KafkaSettings,
    NotificationsDatabaseSettings,
    SenderKind,
    SmtpSettings,
    TelemetrySettings,
)
from otc_notifications.presentation.notification_facts_consumer import (
    NotificationFactsConsumerTask,
)

log = logging.getLogger("otc_notifications.composition")

CONSUMER_STARTUP_SECONDS = 60.0
STOP_GRACE_SECONDS = 30.0
# The dead-letter producer's own client id (`test_kafka_client_ids.py`), distinct from the
# consumer's `otc-notifications`.
DEAD_LETTER_CLIENT_ID = "otc-notifications-dlq"
# The readiness probe's own Kafka admin client (`test_kafka_client_ids.py`).
HEALTH_CLIENT_ID = "otc-notifications-health"


@dataclass(frozen=True, slots=True)
class NotificationsSettings:
    """Every settings class of the service, each constructed exactly once, here."""

    database: NotificationsDatabaseSettings
    kafka: KafkaSettings
    smtp: SmtpSettings
    telemetry: TelemetrySettings
    fact_retry: FactRetrySettings


def load_settings() -> NotificationsSettings:
    return NotificationsSettings(
        database=NotificationsDatabaseSettings(),
        kafka=KafkaSettings(),
        smtp=SmtpSettings(),
        telemetry=TelemetrySettings(),
        fact_retry=FactRetrySettings(),
    )


# ------------------------------------------------------------------------------ the dispatcher


def register_handlers(registry: HandlerRegistry[NotificationsScope]) -> None:
    """Explicit registration: one statement per message type, no loop, no decorator."""
    registry.register_command(NotifyOrderPlacedCommand, NotifyOrderPlacedHandler)
    registry.register_command(NotifyOrderConfirmedCommand, NotifyOrderConfirmedHandler)
    registry.register_command(NotifyOrderDespatchedCommand, NotifyOrderDespatchedHandler)
    registry.register_command(NotifyInvoiceIssuedCommand, NotifyInvoiceIssuedHandler)
    registry.register_command(NotifyPaymentReceivedCommand, NotifyPaymentReceivedHandler)
    registry.register_command(NotifyOrderCompletedCommand, NotifyOrderCompletedHandler)
    registry.register_command(NotifyOrderCancelledCommand, NotifyOrderCancelledHandler)


def _wire() -> tuple[Dispatcher[NotificationsScope], list[Callable[[NotificationsScope], object]]]:
    registry = HandlerRegistry[NotificationsScope]()
    register_handlers(registry)
    return registry.build(otc_notifications.application), registry.registered_factories()


def build_dispatcher() -> Dispatcher[NotificationsScope]:
    """Register, then validate against every command and query under the application package.

    Pure (no I/O): `tests/architecture/test_registration_behaviour.py` runs it without a database.
    """
    return _wire()[0]


# ---------------------------------------------------------------------------------- the sender


def build_sender(settings: SmtpSettings) -> NotificationSender:
    """The one place the notification adapter is chosen. `console` is the default and what every
    automated test binds; `smtp` is the SMTP adapter inside the degrading decorator."""
    if settings.sender is SenderKind.SMTP:
        return DegradingNotificationSender(
            SmtpNotificationSender(settings), ConsoleNotificationSender()
        )
    return ConsoleNotificationSender()


# ------------------------------------------------------------------------------------ readiness


def build_health_checks(
    *,
    tasks: Mapping[str, asyncio.Task[None]],
    write_model: Probe,
    fact_stream: Probe,
    consumer_joined: Callable[[], bool],
) -> list[HealthCheck]:
    """The runtime's checks (`R60`): the write model (the delivery ledger) and the fact stream. A
    consumer task that is done, or a consumer that has not joined its group, makes `factStream`
    `down` (read live from the task and the subscriber)."""
    dead_consumer = dead_tasks(tasks, ("fact-consumer",))

    def consumer_reasons() -> list[str]:
        reasons = list(dead_consumer())
        if not consumer_joined():
            reasons.append("the Kafka fact consumer has not joined its group")
        return reasons

    return [
        HealthCheck("writeModel", write_model),
        HealthCheck("factStream", fact_stream, task_reasons=consumer_reasons),
    ]


# ------------------------------------------------------------------------------------ the runtime


class NotificationsRuntime:
    """What the lifespan holds while the service runs."""

    def __init__(
        self,
        *,
        settings: NotificationsSettings,
        dispatcher: Dispatcher[NotificationsScope],
        tasks: dict[str, asyncio.Task[None]],
        engine: AsyncEngine,
        subscriber: KafkaFactSubscriber,
        sender: NotificationSender,
        stop_event: asyncio.Event,
        stack: AsyncExitStack,
        stop_grace_seconds: float = STOP_GRACE_SECONDS,
        checks: Sequence[HealthCheck] = (),
    ) -> None:
        self.settings = settings
        self.checks = checks
        self.dispatcher = dispatcher
        self.tasks = tasks
        self.engine = engine
        self.subscriber = subscriber
        self.sender = sender
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

    async def readiness(self) -> list[CheckResult]:
        """One bounded check per dependency (`R60`, served by `/health/ready`). A task that is done
        while running, or a consumer that has not joined its group, makes `factStream` `down`, read
        live from the task and the subscriber; a runtime that is stopping answers `down` for every
        check without probing."""
        return await run_checks(self.checks, shutting_down=self._stopping)

    async def stop(self) -> None:
        """Stop the task (after its in-flight record), then close what `start_runtime` opened."""
        self._stopping = True
        await _stop_tasks(self._stop_event, self.tasks, self._stop_grace_seconds)
        await self._stack.aclose()


async def _stop_tasks(
    stop_event: asyncio.Event,
    tasks: dict[str, asyncio.Task[None]],
    grace_seconds: float = STOP_GRACE_SECONDS,
) -> None:
    """Ask the tasks to end and await every one. A task that has not ended after the grace period
    (a consumer stuck in `start()`, a send that never answers) is CANCELLED and awaited: the
    lifespan must end, and cancellation propagates through `dispatch`, which forgets its ledger row
    first. A failure is logged, never swallowed silently."""
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
    subscriber: KafkaFactSubscriber, task: asyncio.Task[None], timeout_seconds: float
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
    settings: NotificationsSettings,
    *,
    sender: NotificationSender | None = None,
    consumer_startup_seconds: float = CONSUMER_STARTUP_SECONDS,
    stop_grace_seconds: float = STOP_GRACE_SECONDS,
    span_processors: Sequence[SpanProcessor] = (),
    metric_readers: Sequence[MetricReader] = (),
    fact_topics: Sequence[str] | None = None,
    dead_letter_producer_factory: ProducerFactory | None = None,
) -> NotificationsRuntime:
    """`sender`, `span_processors`, `metric_readers`, `fact_topics` and
    `dead_letter_producer_factory` are the test seams: the lifespan passes none of them.
    `fact_topics` points the consumer at topics a test created (its dead letters go to
    `<topic>.dlq`), so a test that publishes a poison fact never leaves it on the real topics;
    `dead_letter_producer_factory` replaces the aiokafka producer the dead-letter publisher builds
    (a test that makes the publication fail)."""
    async with AsyncExitStack() as stack:
        # This runtime's own tracer and meter providers (`R56`), first so that everything below can
        # make spans, and closed LAST (the stack unwinds in reverse, so the flush follows every
        # adapter's close). Never the process-global provider (`telemetry.py`).
        telemetry = build_telemetry(
            "notifications",
            settings.telemetry.otlp_endpoint,
            span_processors=span_processors,
            metric_readers=metric_readers,
        )
        stack.push_async_callback(telemetry.aclose)

        # The dispatcher is validated before anything is opened: a missing or duplicate handler is
        # a boot failure that cost no connection.
        dispatcher, registered_factories = _wire()

        engine = create_async_engine(
            settings.database.url,
            pool_size=2,  # one record at a time: the ledger's record, then its forget
            max_overflow=0,
        )
        stack.push_async_callback(engine.dispose)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        clock = SystemClock()

        ledger = SqlAlchemyDeliveryLedger(sessions, clock, tracer=telemetry.tracer)
        chosen_sender = sender if sender is not None else build_sender(settings.smtp)

        def scope_factory() -> NotificationsScope:
            return NotificationsScope(ledger=ledger, sender=chosen_sender)

        # Every binding is proven at boot, never on the first message: the scope refuses a port
        # that is bound to nothing, and each registered handler is built once.
        for factory in registered_factories:
            factory(scope_factory())

        # The dead-letter producer starts BEFORE the consumer task exists: a consumer that cannot
        # dead-letter must not start. It belongs to the stack, which closes after the task stops.
        dead_letters = KafkaDeadLetterPublisher(
            settings.kafka,
            client_id=DEAD_LETTER_CLIENT_ID,
            producer_factory=dead_letter_producer_factory,
        )
        await dead_letters.start()
        stack.push_async_callback(dead_letters.stop)

        stop_event = asyncio.Event()  # the consumer's stop signal: it also ends a retry back-off
        subscriber = KafkaFactSubscriber(
            settings.kafka,
            tracer=telemetry.tracer,
            topics=NOTIFICATION_FACT_TOPICS if fact_topics is None else fact_topics,
        )
        consumer = NotificationFactsConsumerTask(
            subscriber=subscriber,
            dispatcher=dispatcher,
            scope_factory=scope_factory,
            retry=FactRetry(
                consumer=ConsumerName.NOTIFICATIONS.value,
                policy=FactRetryPolicy(
                    max_attempts=settings.fact_retry.max_attempts,
                    backoff_ms=settings.fact_retry.backoff_ms,
                ),
                clock=clock,
                sleep=stop_aware_sleep(stop_event),
                dead_letters=dead_letters,
                latency=FactLatencyHistogram(fact_processing_latency(telemetry.meter)),
            ),
        )
        tasks: dict[str, asyncio.Task[None]] = {}
        # Every step from here on can fail (Kafka down at boot) and a task may already exist: a
        # failure stops and awaits the task FIRST, then the stack closes what it used.
        try:
            tasks["fact-consumer"] = asyncio.create_task(
                consumer.run(stop_event), name="fact-consumer"
            )
            await _await_consumer_ready(
                subscriber, tasks["fact-consumer"], consumer_startup_seconds
            )
            # Readiness (`R60`): the write model (the delivery ledger) and the fact stream.
            postgres_probe = PostgresProbe(settings.database.url)
            stack.push_async_callback(postgres_probe.aclose)
            kafka_probe = KafkaAdminProbe(settings.kafka.brokers, client_id=HEALTH_CLIENT_ID)
            stack.push_async_callback(kafka_probe.aclose)
            checks = build_health_checks(
                tasks=tasks,
                write_model=postgres_probe,
                fact_stream=kafka_probe,
                consumer_joined=lambda: subscriber.ready,
            )
            # The runtime is built BEFORE the stack is handed over: a constructor that raises
            # still finds everything owned by `stack`. `pop_all()` is the last statement.
            owned = AsyncExitStack()
            runtime = NotificationsRuntime(
                settings=settings,
                dispatcher=dispatcher,
                tasks=tasks,
                engine=engine,
                subscriber=subscriber,
                sender=chosen_sender,
                stop_event=stop_event,
                stack=owned,
                stop_grace_seconds=stop_grace_seconds,
                checks=checks,
            )
            owned.push_async_callback(stack.pop_all().aclose)
        except BaseException:
            await _stop_tasks(stop_event, tasks, stop_grace_seconds)
            raise
    return runtime
