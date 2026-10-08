"""The Fulfillment host: what its REAL lifespan starts, owns, awaits and refuses (G4, G6, G7).

Every test drives `otc_fulfillment.main.create_app()` and its lifespan with NO argument: the host
reads its own configuration from the process environment (the `host_environment` fixture sets only
that), which is what a deployment does. #8's D6 was a guard that supplied the options itself and so
proved the container validates when ASKED, not that the host asks; here nothing is supplied. The
reach test below was written WITH the composition root (#8 id 56 recurred three times in Phase 8).
"""

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import nats
import pytest
from sqlalchemy.ext.asyncio import create_async_engine as real_create_engine

import otc_fulfillment.application.messages as messages_module
import otc_fulfillment.composition as composition
import otc_fulfillment.infrastructure.outbox.kafka_publisher as kafka_publisher_module
from otc_cqrs import Command, DispatcherValidationError, Query
from otc_fulfillment.application.handlers import ReserveStockHandler
from otc_fulfillment.application.messages import ReserveStockCommand
from otc_fulfillment.application.scope import MissingBindingError
from otc_fulfillment.composition import MultipleOutboxRelaysError
from otc_fulfillment.infrastructure.outbox.kafka_publisher import KafkaFactPublisher
from otc_fulfillment.infrastructure.outbox.relay import OutboxRelay
from otc_fulfillment.infrastructure.outbox.relay_task import OutboxRelayTask
from otc_fulfillment.presentation.stock_responder import StockResponder

HostFactory = Callable[..., AbstractAsyncContextManager[Any]]


async def readiness(app: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health/ready")


# ------------------------------------------------------------- the tasks the lifespan owns (G7)


async def test_the_lifespan_starts_the_responder_and_the_relay_and_awaits_both_on_shutdown(
    fulfillment_host_factory: HostFactory,
) -> None:
    async with fulfillment_host_factory(OUTBOX_RELAY_ENABLED="true") as host:
        tasks = dict(host.runtime.tasks)
        assert set(tasks) == {"nats-responder", "outbox-relay"}
        assert all(not task.done() for task in tasks.values())
        response = await readiness(host.app)
        assert (response.status_code, response.json()) == (200, {"status": "ready"})

    # the lifespan has exited: every task it created has been awaited to completion, none cancelled
    assert all(task.done() and not task.cancelled() for task in tasks.values())
    assert [task.exception() for task in tasks.values()] == [None] * len(tasks)
    assert (await readiness(host.app)).status_code == 503, "a stopped service is not ready"


async def test_with_the_relay_disabled_no_relay_task_exists_and_kafka_is_never_contacted(
    fulfillment_host_factory: HostFactory,
) -> None:
    # KAFKA_BROKERS points at a port nothing listens on: a producer start would fail the boot.
    async with fulfillment_host_factory(
        OUTBOX_RELAY_ENABLED="false", KAFKA_BROKERS="127.0.0.1:1"
    ) as host:
        assert set(host.runtime.tasks) == {"nats-responder"}
        assert (await readiness(host.app)).status_code == 200


@pytest.mark.parametrize("task_name", ["outbox-relay", "nats-responder"])
async def test_a_transport_task_that_dies_takes_readiness_down_and_names_it(
    fulfillment_host_factory: HostFactory, task_name: str
) -> None:
    async with fulfillment_host_factory(OUTBOX_RELAY_ENABLED="true") as host:
        assert (await readiness(host.app)).status_code == 200
        victim = host.runtime.tasks[task_name]
        survivors = [t for name, t in host.runtime.tasks.items() if name != task_name]

        victim.cancel()
        await asyncio.wait({victim}, timeout=5)

        response = await readiness(host.app)
        assert response.status_code == 503
        assert response.json() == {
            "status": "unready",
            "reasons": [f"transport task {task_name} is not running"],
        }
        assert all(not t.done() for t in survivors), "only the dead task is named"


async def test_a_closed_nats_connection_takes_readiness_down_even_though_no_task_ended(
    fulfillment_host_factory: HostFactory,
) -> None:
    async with fulfillment_host_factory() as host:
        assert (await readiness(host.app)).status_code == 200

        await host.runtime.connection.close()

        response = await readiness(host.app)
        assert response.status_code == 503
        assert "the NATS connection is closed" in response.json()["reasons"]


async def test_readiness_is_503_before_the_lifespan_has_started() -> None:
    from otc_fulfillment.main import create_app

    response = await readiness(create_app())
    assert response.status_code == 503
    assert response.json()["reasons"] == ["the service has not started"]


# ------------------------------------ a boot that fails part-way closes what it already opened


async def test_a_boot_that_fails_after_the_responder_task_exists_leaves_no_task_behind(
    fulfillment_host_factory: HostFactory,
) -> None:
    # Kafka is down at boot (the ordinary compose start-up race): the producer start raises AFTER
    # the responder task was created. `nats-responder` and its stop waiter must not outlive it.
    with pytest.raises(Exception, match="Unable to bootstrap"):
        async with fulfillment_host_factory(
            OUTBOX_RELAY_ENABLED="true", KAFKA_BROKERS="127.0.0.1:1"
        ):
            pytest.fail("the host must not come up while Kafka is unreachable")

    leaked = sorted(
        task.get_name()
        for task in asyncio.all_tasks()
        if task.get_name() in {"nats-responder", "stock responder stop waiter"} and not task.done()
    )
    assert leaked == [], f"a failed boot leaked tasks: {leaked}"


async def test_a_kafka_producer_that_cannot_start_is_stopped_before_the_boot_fails(
    fulfillment_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class UnstartableProducer:
        def __init__(self, **options: Any) -> None:
            events.append("constructed")

        async def start(self) -> None:
            events.append("start")
            raise ConnectionError("broker is down")

        async def stop(self) -> None:
            events.append("stop")

    monkeypatch.setattr(kafka_publisher_module, "AIOKafkaProducer", UnstartableProducer)

    with pytest.raises(ConnectionError, match="broker is down"):
        async with fulfillment_host_factory(OUTBOX_RELAY_ENABLED="true"):
            pytest.fail("the host must not come up while the producer cannot start")

    assert events == ["constructed", "start", "stop"]


async def test_a_runtime_constructor_that_raises_still_unwinds_the_stack(
    fulfillment_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    connections: list[Any] = []
    real_connect = nats.connect
    real_runtime = composition.FulfillmentRuntime
    attempts: list[int] = []

    async def recording_connect(*args: Any, **kwargs: Any) -> Any:
        connection = await real_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    def runtime_that_fails_once(**kwargs: Any) -> Any:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("the runtime could not be built")
        return real_runtime(**kwargs)

    monkeypatch.setattr(nats, "connect", recording_connect)
    monkeypatch.setattr(composition, "FulfillmentRuntime", runtime_that_fails_once)

    with pytest.raises(RuntimeError, match="the runtime could not be built"):
        async with fulfillment_host_factory():
            pytest.fail("the host must not come up when the runtime cannot be built")

    [connection] = connections
    assert connection.is_closed, "NATS must be closed by the unwinding stack"
    async with fulfillment_host_factory() as again:
        assert "nats-responder" in again.runtime.tasks, "a second boot must be allowed"


# --------------------------------------- the registry is validated by the lifespan (G6)


async def test_a_command_or_query_with_no_registered_handler_fails_the_boot_before_connecting(
    fulfillment_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composition, "register_handlers", lambda registry: None)
    connected: list[str] = []

    async def must_not_connect(*args: Any, **kwargs: Any) -> Any:
        connected.append("nats.connect")
        raise AssertionError("the boot opened a NATS connection before validating the registry")

    monkeypatch.setattr(nats, "connect", must_not_connect)

    with pytest.raises(DispatcherValidationError) as refused:
        async with fulfillment_host_factory(NATS_URL="nats://127.0.0.1:1"):
            pytest.fail("the host must not come up with nothing registered")

    assert connected == [], "validation happens before anything is opened"
    assert sorted(refused.value.problems) == sorted(
        [
            f"No command handler is registered for {name}. Exactly one is required."
            for name in (
                "ReserveStockCommand",
                "ReleaseStockCommand",
                "ReplenishStockCommand",
                "CreateDespatchCommand",
            )
        ]
        + [
            f"No query handler is registered for {name}. Exactly one is required."
            for name in ("CheckStockQuery", "ListStockQuery")
        ]
    )


async def test_a_command_with_two_registered_handlers_fails_the_boot(
    fulfillment_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = composition.register_handlers

    def twice(registry: Any) -> None:
        original(registry)
        registry.register_command(ReserveStockCommand, ReserveStockHandler)

    monkeypatch.setattr(composition, "register_handlers", twice)

    with pytest.raises(DispatcherValidationError) as refused:
        async with fulfillment_host_factory():
            pytest.fail("the host must not come up with two handlers for one command")

    assert len(refused.value.problems) == 1
    assert refused.value.problems[0].startswith(
        "2 command handlers are registered for ReserveStockCommand:"
    )


async def test_a_new_command_nobody_registered_fails_the_boot_by_name(
    fulfillment_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DespatchOrderCommand(Command[None]):
        pass

    monkeypatch.setattr(
        messages_module, "DespatchOrderCommand", DespatchOrderCommand, raising=False
    )

    with pytest.raises(DispatcherValidationError) as refused:
        async with fulfillment_host_factory():
            pytest.fail("the host must not come up with a command that has no handler")

    assert "No command handler is registered for" in refused.value.problems[0]
    assert "DespatchOrderCommand" in refused.value.problems[0]


async def test_a_port_bound_to_nothing_fails_the_boot_not_the_first_message(
    fulfillment_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composition, "SqlAlchemyStockReads", lambda *args, **kwargs: None)

    with pytest.raises(MissingBindingError) as refused:
        async with fulfillment_host_factory():
            pytest.fail("the host must not come up with the reads port unbound")

    assert refused.value.binding == "reads"


@pytest.mark.parametrize("kind", ["command", "query"])
async def test_a_registered_handler_that_cannot_be_built_fails_the_boot_whoever_registered_it(
    fulfillment_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch, kind: str
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
        async with fulfillment_host_factory():
            pytest.fail("the host must not come up with a registered handler that cannot be built")


# ------------------------------- every environment read reaches the thing it configures (G4)


class Recorded:
    def __init__(self) -> None:
        self.kafka: list[Any] = []
        self.relay: list[dict[str, Any]] = []
        self.relay_task: list[dict[str, Any]] = []
        self.responder: list[dict[str, Any]] = []
        self.engine: list[dict[str, Any]] = []


async def test_every_setting_the_composition_root_reads_reaches_its_adapter(
    fulfillment_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch, kafka_server: Any
) -> None:
    recorded = Recorded()

    class RecordingPublisher(KafkaFactPublisher):
        def __init__(self, settings: Any) -> None:
            recorded.kafka.append(settings)
            super().__init__(settings)

    class RecordingRelay(OutboxRelay):
        def __init__(self, **kwargs: Any) -> None:
            recorded.relay.append(kwargs)
            super().__init__(**kwargs)

    class RecordingRelayTask(OutboxRelayTask):
        def __init__(self, relay: Any, **kwargs: Any) -> None:
            recorded.relay_task.append(kwargs)
            super().__init__(relay, **kwargs)

    class RecordingResponder(StockResponder):
        def __init__(self, **kwargs: Any) -> None:
            recorded.responder.append(kwargs)
            super().__init__(**kwargs)

    def recording_engine(url: str, **kwargs: Any) -> Any:
        recorded.engine.append(kwargs)
        return real_create_engine(url, **kwargs)

    monkeypatch.setattr(composition, "KafkaFactPublisher", RecordingPublisher)
    monkeypatch.setattr(composition, "OutboxRelay", RecordingRelay)
    monkeypatch.setattr(composition, "OutboxRelayTask", RecordingRelayTask)
    monkeypatch.setattr(composition, "StockResponder", RecordingResponder)
    monkeypatch.setattr(composition, "create_async_engine", recording_engine)

    async with fulfillment_host_factory(
        OUTBOX_RELAY_ENABLED="true",
        FULFILLMENT_KAFKA_CLIENT_ID="otc-fulfillment-sentinel",
        OUTBOX_BATCH_SIZE="37",
        OUTBOX_POLL_INTERVAL_MS="73",
        OUTBOX_PUBLISH_TIMEOUT_MS="4321",
        FULFILLMENT_MAX_CONCURRENT_REQUESTS="7",
    ) as host:
        assert host.runtime.settings.responder.max_concurrent_requests == 7
        assert host.runtime.engine.pool.size() == 8, "the engine's pool is sized from the bound + 1"

    [kafka] = recorded.kafka
    assert kafka.client_id == "otc-fulfillment-sentinel", (
        "FULFILLMENT_KAFKA_CLIENT_ID must reach it"
    )
    assert kafka.brokers == kafka_server.bootstrap_servers, "KAFKA_BROKERS must come from the env"
    assert kafka.brokers != "localhost:9092"
    [relay] = recorded.relay
    assert (relay["batch_size"], relay["publish_timeout"]) == (37, 4.321)
    [relay_task] = recorded.relay_task
    assert (relay_task["poll_interval"], relay_task["enabled"]) == (0.073, True)
    [responder] = recorded.responder
    assert responder["max_concurrent_requests"] == 7, "the responder's bound"
    [engine] = recorded.engine
    assert (engine["pool_size"], engine["max_overflow"]) == (8, 0)


# ---------------------------------- at most one relay per process; no multi-worker (G7)


async def test_more_than_one_worker_with_the_relay_enabled_refuses_to_boot_before_connecting(
    fulfillment_host_factory: HostFactory,
) -> None:
    # the database, NATS and Kafka addresses are dead: the refusal must come BEFORE any of them
    with pytest.raises(MultipleOutboxRelaysError, match="WEB_CONCURRENCY=2"):
        async with fulfillment_host_factory(
            OUTBOX_RELAY_ENABLED="true",
            WEB_CONCURRENCY="2",
            FULFILLMENT_DATABASE_URL="postgresql+asyncpg://nobody:x@127.0.0.1:1/none",
            NATS_URL="nats://127.0.0.1:1",
            KAFKA_BROKERS="127.0.0.1:1",
        ):
            pytest.fail("two workers must not each run a relay")


async def test_several_workers_are_fine_while_the_relay_is_disabled(
    fulfillment_host_factory: HostFactory,
) -> None:
    async with fulfillment_host_factory(WEB_CONCURRENCY="4", OUTBOX_RELAY_ENABLED="false") as host:
        assert (await readiness(host.app)).status_code == 200


async def test_a_second_relay_owning_runtime_in_one_process_is_refused_and_the_first_survives(
    fulfillment_host_factory: HostFactory,
) -> None:
    async with fulfillment_host_factory(OUTBOX_RELAY_ENABLED="true") as first:
        with pytest.raises(MultipleOutboxRelaysError, match="already runs an outbox relay"):
            async with fulfillment_host_factory(OUTBOX_RELAY_ENABLED="true"):
                pytest.fail("a second relay in this process must be refused")
        assert (await readiness(first.app)).status_code == 200
    # the slot is released by shutdown: a later start is allowed again
    async with fulfillment_host_factory(OUTBOX_RELAY_ENABLED="true") as again:
        assert "outbox-relay" in again.runtime.tasks


@pytest.mark.parametrize("value", ["0", "-3"])
async def test_a_concurrency_bound_below_one_refuses_to_boot(
    fulfillment_host_factory: HostFactory, value: str
) -> None:
    with pytest.raises(ValueError, match="FULFILLMENT_MAX_CONCURRENT_REQUESTS must be at least 1"):
        async with fulfillment_host_factory(FULFILLMENT_MAX_CONCURRENT_REQUESTS=value):
            pytest.fail("a bound of zero would handle no request")
