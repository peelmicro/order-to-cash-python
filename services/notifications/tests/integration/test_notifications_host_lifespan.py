"""The Notifications host: what its REAL lifespan starts, owns, awaits and refuses (acceptance 5,
carried from feature 43; CLAUDE.md "one asyncio task class per transport").

Every test drives `otc_notifications.main.create_app()` and its lifespan with NO argument: the host
reads its own configuration from the process environment (the `host_environment` fixture sets only
that), which is what a deployment does (#8's D6 was a guard that supplied the options itself).
Ported from Billing's `test_billing_host_lifespan.py`; the NATS and relay halves do not apply (this
service has neither), the consumer's own are added.

Loop scope: function.
"""

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import pytest

import otc_notifications.application.messages as messages_module
import otc_notifications.composition as composition
import otc_notifications.infrastructure.messaging.kafka_fact_subscriber as subscriber_module
from otc_cqrs import Command, DispatcherValidationError, Query
from otc_notifications.application.handlers import NotifyOrderPlacedHandler
from otc_notifications.application.messages import NotifyOrderPlacedCommand
from otc_notifications.application.scope import MissingBindingError

HostFactory = Callable[..., AbstractAsyncContextManager[Any]]

NOTIFY_COMMANDS = (
    "NotifyOrderPlacedCommand",
    "NotifyOrderConfirmedCommand",
    "NotifyOrderDespatchedCommand",
    "NotifyInvoiceIssuedCommand",
    "NotifyPaymentReceivedCommand",
    "NotifyOrderCompletedCommand",
    "NotifyOrderCancelledCommand",
)


async def readiness(app: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health/ready")


# ------------------------------------------------------------- the task the lifespan owns


async def test_the_lifespan_starts_the_fact_consumer_and_awaits_it_on_shutdown(
    notifications_host_factory: HostFactory,
) -> None:
    async with notifications_host_factory() as host:
        tasks = dict(host.runtime.tasks)
        assert set(tasks) == {"fact-consumer"}, (
            "one task class per transport: no relay, no responder"
        )
        assert all(not task.done() for task in tasks.values())
        response = await readiness(host.app)
        assert (response.status_code, response.json()) == (200, {"status": "ready"})

    # the lifespan has exited: every task it created has been awaited to completion, none cancelled
    assert all(task.done() and not task.cancelled() for task in tasks.values())
    assert [task.exception() for task in tasks.values()] == [None] * len(tasks)
    assert (await readiness(host.app)).status_code == 503, "a stopped service is not ready"
    assert not host.runtime.subscriber.ready


async def test_a_fact_consumer_that_dies_takes_readiness_down_and_names_it(
    notifications_host_factory: HostFactory,
) -> None:
    async with notifications_host_factory() as host:
        assert (await readiness(host.app)).status_code == 200
        victim = host.runtime.tasks["fact-consumer"]

        victim.cancel()
        await asyncio.wait({victim}, timeout=5)

        response = await readiness(host.app)
        assert response.status_code == 503
        reasons = response.json()["reasons"]
        assert "transport task fact-consumer is not running" in reasons


async def test_readiness_is_503_before_the_lifespan_has_started() -> None:
    from otc_notifications.main import create_app

    response = await readiness(create_app())
    assert response.status_code == 503
    assert response.json()["reasons"] == ["the service has not started"]


async def test_readiness_names_a_consumer_that_has_not_joined_its_group(
    notifications_host_factory: HostFactory,
) -> None:
    async with notifications_host_factory() as host:
        host.runtime.subscriber._ready.clear()
        response = await readiness(host.app)
        assert response.status_code == 503
        assert response.json()["reasons"] == ["the Kafka fact consumer has not joined its group"]


# ------------------------------------ a boot that fails part-way closes what it already opened


async def test_a_boot_with_kafka_unreachable_fails_and_leaves_no_task_behind(
    notifications_host_factory: HostFactory,
) -> None:
    with pytest.raises(Exception, match="Unable to bootstrap"):
        async with notifications_host_factory(KAFKA_BROKERS="127.0.0.1:1"):
            pytest.fail("the host must not come up while Kafka is unreachable")

    leaked = sorted(
        task.get_name()
        for task in asyncio.all_tasks()
        if task.get_name() in {"fact-consumer", "fact-consumer ready waiter"} and not task.done()
    )
    assert leaked == [], f"a failed boot leaked tasks: {leaked}"


async def test_a_consumer_that_cannot_start_is_stopped_before_the_boot_fails(
    notifications_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class UnstartableConsumer:
        def __init__(self, *topics: str, **options: Any) -> None:
            events.append("constructed")

        async def start(self) -> None:
            events.append("start")
            raise ConnectionError("broker is down")

        async def stop(self) -> None:
            events.append("stop")

    monkeypatch.setattr(subscriber_module, "AIOKafkaConsumer", UnstartableConsumer)
    # the default argument was bound at import; the subscriber takes the factory from there
    monkeypatch.setattr(
        subscriber_module.KafkaFactSubscriber.__init__,
        "__kwdefaults__",
        {
            **(subscriber_module.KafkaFactSubscriber.__init__.__kwdefaults__ or {}),
            "consumer_factory": UnstartableConsumer,
        },
    )

    with pytest.raises(ConnectionError, match="broker is down"):
        async with notifications_host_factory():
            pytest.fail("the host must not come up while the consumer cannot start")

    assert events == ["constructed", "start", "stop"]


async def test_a_consumer_that_never_joins_its_group_times_out_the_boot_and_leaves_no_task(
    notifications_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NeverAssigned:
        def __init__(self, *topics: str, **options: Any) -> None: ...

        async def start(self) -> None:
            await asyncio.Event().wait()

        async def stop(self) -> None: ...

    monkeypatch.setattr(
        subscriber_module.KafkaFactSubscriber.__init__,
        "__kwdefaults__",
        {
            **(subscriber_module.KafkaFactSubscriber.__init__.__kwdefaults__ or {}),
            "consumer_factory": NeverAssigned,
        },
    )
    real_start = composition.start_runtime

    async def quick(settings: Any, **kwargs: Any) -> Any:
        return await real_start(
            settings, consumer_startup_seconds=0.3, stop_grace_seconds=0.3, **kwargs
        )

    monkeypatch.setattr(composition, "start_runtime", quick)
    import otc_notifications.main as main_module

    monkeypatch.setattr(main_module, "start_runtime", quick)

    # The wait is bounded here, so a missing cancel after the grace period FAILS in seconds with
    # the claim named, instead of hanging `quality.sh` (review N1: the guard used to fail by hang).
    try:
        async with asyncio.timeout(15):
            with pytest.raises(TimeoutError, match="did not join its group"):
                async with notifications_host_factory():
                    pytest.fail("the host must not come up without a group assignment")
    except TimeoutError:
        pytest.fail(
            "the stuck consumer task was not cancelled after the grace period: "
            "the failed boot is still waiting for it"
        )

    assert not [t for t in asyncio.all_tasks() if t.get_name() == "fact-consumer" and not t.done()]


async def test_stop_cancels_a_send_that_never_returns_after_the_grace_and_forgets_its_row(
    notifications_host_factory: HostFactory,
    publisher: Any,
    facts: Any,
    topic_of: Any,
    ledger_rows: Any,
) -> None:
    """`runtime.stop()` uses the grace `start_runtime` was given (review N1), cancels the task that
    has not ended, and cancellation reaches `dispatch`, which forgets the ledger row first."""
    entered = asyncio.Event()

    class NeverReturns:
        async def send(self, message: Any) -> None:
            entered.set()
            await asyncio.Event().wait()

    event_type = "order.placed.v1"
    fact = facts.event(event_type)
    async with notifications_host_factory(sender=NeverReturns(), stop_grace_seconds=0.3) as host:
        await publisher.publish(topic_of[event_type], fact.correlation_id, facts.wire_from(fact))
        await asyncio.wait_for(entered.wait(), timeout=30)
        assert [event_id for event_id, _ in await ledger_rows()] == [fact.event_id], (
            "the row is recorded before the send"
        )
        task = host.runtime.tasks["fact-consumer"]
        try:
            async with asyncio.timeout(15):
                await host.runtime.stop()
        except TimeoutError:
            pytest.fail(
                "runtime.stop() did not return: the task was not cancelled after the grace period"
            )
        assert task.cancelled(), "the task was cancelled after the grace period, not left running"
        assert await ledger_rows() == [], "cancellation forgot the row, so the redelivery sends"


async def test_a_runtime_constructor_that_raises_still_unwinds_the_stack(
    notifications_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_runtime = composition.NotificationsRuntime
    attempts: list[int] = []
    engines: list[Any] = []
    real_create_engine = composition.create_async_engine  # type: ignore[attr-defined]

    def recording_engine(*args: Any, **kwargs: Any) -> Any:
        engine = real_create_engine(*args, **kwargs)
        engines.append(engine)
        return engine

    def runtime_that_fails_once(**kwargs: Any) -> Any:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("the runtime could not be built")
        return real_runtime(**kwargs)

    monkeypatch.setattr(composition, "create_async_engine", recording_engine)
    monkeypatch.setattr(composition, "NotificationsRuntime", runtime_that_fails_once)

    with pytest.raises(RuntimeError, match="the runtime could not be built"):
        async with notifications_host_factory():
            pytest.fail("the host must not come up when the runtime cannot be built")

    assert not [t for t in asyncio.all_tasks() if t.get_name() == "fact-consumer" and not t.done()]
    async with notifications_host_factory() as again:
        assert "fact-consumer" in again.runtime.tasks, "a second boot must be allowed"
    assert len(engines) == 2


# --------------------------------------- the registry is validated by the lifespan (acceptance 5)


async def test_a_command_with_no_registered_handler_fails_the_boot_before_anything_is_opened(
    notifications_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composition, "register_handlers", lambda registry: None)
    opened: list[str] = []

    def must_not_open(*args: Any, **kwargs: Any) -> Any:
        opened.append("engine")
        raise AssertionError("the boot opened an engine before validating the registry")

    monkeypatch.setattr(composition, "create_async_engine", must_not_open)

    with pytest.raises(DispatcherValidationError) as refused:
        async with notifications_host_factory(KAFKA_BROKERS="127.0.0.1:1"):
            pytest.fail("the host must not come up with nothing registered")

    assert opened == [], "validation happens before anything is opened"
    assert sorted(refused.value.problems) == sorted(
        f"No command handler is registered for {name}. Exactly one is required."
        for name in NOTIFY_COMMANDS
    )


async def test_a_command_with_two_registered_handlers_fails_the_boot(
    notifications_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = composition.register_handlers

    def twice(registry: Any) -> None:
        original(registry)
        registry.register_command(NotifyOrderPlacedCommand, NotifyOrderPlacedHandler)

    monkeypatch.setattr(composition, "register_handlers", twice)

    with pytest.raises(DispatcherValidationError) as refused:
        async with notifications_host_factory():
            pytest.fail("the host must not come up with two handlers for one command")

    assert len(refused.value.problems) == 1
    assert refused.value.problems[0].startswith(
        "2 command handlers are registered for NotifyOrderPlacedCommand:"
    )


async def test_a_new_command_nobody_registered_fails_the_boot_by_name(
    notifications_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ChargebackCommand(Command[None]):
        pass

    monkeypatch.setattr(messages_module, "ChargebackCommand", ChargebackCommand, raising=False)

    with pytest.raises(DispatcherValidationError) as refused:
        async with notifications_host_factory():
            pytest.fail("the host must not come up with a command that has no handler")

    assert "No command handler is registered for" in refused.value.problems[0]
    assert "ChargebackCommand" in refused.value.problems[0]


async def test_a_port_bound_to_nothing_fails_the_boot_not_the_first_message(
    notifications_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composition, "SqlAlchemyDeliveryLedger", lambda *args, **kwargs: None)

    with pytest.raises(MissingBindingError) as refused:
        async with notifications_host_factory():
            pytest.fail("the host must not come up with the ledger port unbound")

    assert refused.value.binding == "ledger"


async def test_a_sender_bound_to_nothing_fails_the_boot_naming_it(
    notifications_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composition, "build_sender", lambda settings: None)

    with pytest.raises(MissingBindingError) as refused:
        async with notifications_host_factory():
            pytest.fail("the host must not come up with the sender port unbound")

    assert refused.value.binding == "sender"


@pytest.mark.parametrize("kind", ["command", "query"])
async def test_a_registered_handler_that_cannot_be_built_fails_the_boot_whoever_registered_it(
    notifications_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    class LateCommand(Command[None]):
        pass

    class LateQuery(Query[int]):
        pass

    class UnbuildableHandler:
        def __init__(self, scope: Any) -> None:
            raise RuntimeError(f"the {kind} handler needs a port nobody bound")

    if kind == "command":
        monkeypatch.setattr(messages_module, "LateCommand", LateCommand, raising=False)
    else:
        monkeypatch.setattr(messages_module, "LateQuery", LateQuery, raising=False)
    original = composition.register_handlers

    def with_late_handler(registry: Any) -> None:
        original(registry)
        if kind == "command":
            registry.register_command(LateCommand, UnbuildableHandler)
        else:
            registry.register_query(LateQuery, UnbuildableHandler)

    monkeypatch.setattr(composition, "register_handlers", with_late_handler)

    with pytest.raises(RuntimeError, match=f"the {kind} handler needs a port nobody bound"):
        async with notifications_host_factory():
            pytest.fail("the host must not come up with a registered handler that cannot be built")


# ------------------------------- every environment read reaches the thing it configures


async def test_each_setting_reaches_the_adapter_it_configures(
    notifications_host_factory: HostFactory, migrated_db: Any, mailpit_server: Any
) -> None:
    async with notifications_host_factory(
        NOTIFICATIONS_KAFKA_CLIENT_ID="client-sentinel",
        NOTIFICATIONS_CONSUMER_GROUP="group-sentinel",
        SMTP_FROM_EMAIL="from-sentinel@order-to-cash.example",
    ) as host:
        options = host.runtime.subscriber.consumer_options()
        assert (options["client_id"], options["group_id"]) == ("client-sentinel", "group-sentinel")
        assert options["bootstrap_servers"] == host.runtime.settings.kafka.brokers
        sender = host.runtime.sender
        inner = sender.inner
        assert inner._settings.host == mailpit_server.smtp_host
        assert inner._settings.port == mailpit_server.smtp_port
        assert inner._settings.from_email == "from-sentinel@order-to-cash.example"
        assert str(host.runtime.engine.url.database) == migrated_db.name, "the database reached"


async def test_the_console_sender_is_bound_when_asked_and_nothing_contacts_smtp(
    notifications_host_factory: HostFactory,
) -> None:
    from otc_notifications.infrastructure.notification.console_sender import (
        ConsoleNotificationSender,
    )

    async with notifications_host_factory(NOTIFICATIONS_SENDER="console", SMTP_PORT="1") as host:
        assert type(host.runtime.sender) is ConsoleNotificationSender
