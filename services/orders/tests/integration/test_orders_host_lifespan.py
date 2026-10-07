"""The Orders host: what its REAL lifespan starts, owns, awaits and refuses (feature 15, items 4-8).

Every test drives `otc_orders.main.create_app()` and its lifespan with NO argument: the host reads
its own configuration from the process environment (the `host_environment` fixture sets only that),
which is what a deployment does. #8's D6 was a guard that supplied the options itself and so proved
the container validates when ASKED, not that the host asks; here nothing is supplied.
"""

import ast
import asyncio
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, cast

import httpx
import nats
import pytest
from nats.aio.client import Client as NatsClient

import otc_orders.application.commands.place_order as place_order_module
import otc_orders.composition as composition
import otc_orders.infrastructure.outbox.kafka_publisher as kafka_publisher_module
from otc_cqrs import Command, DispatcherValidationError, Query
from otc_orders.application.commands.place_order import (
    PlaceOrderCommand,
    PlaceOrderCommandHandler,
)
from otc_orders.application.saga.fact_command_handlers import SagaFactCommandHandler
from otc_orders.application.saga.fact_commands import HandleStockReservedFactCommand
from otc_orders.application.scope import MissingBindingError
from otc_orders.composition import MultipleOutboxRelaysError
from otc_orders.infrastructure.messaging.nats_saga_commands import NatsSagaCommandsAdapter
from otc_orders.infrastructure.messaging.nats_stock_availability import NatsStockAvailability
from otc_orders.infrastructure.outbox.kafka_publisher import KafkaFactPublisher
from otc_orders.infrastructure.outbox.relay import OutboxRelay
from otc_orders.infrastructure.outbox.relay_task import OutboxRelayTask
from otc_orders.infrastructure.saga.command_dispatcher import SagaCommandDispatcher
from otc_orders.infrastructure.saga.command_ledger import SqlAlchemySagaCommandLedger
from otc_orders.infrastructure.saga.fast_path import SagaFastPath
from otc_orders.infrastructure.saga.sweeper import SagaCommandSweeper
from otc_orders.infrastructure.saga.sweeper_task import SagaCommandSweeperTask

HostFactory = Callable[..., AbstractAsyncContextManager[Any]]


async def readiness(app: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health/ready")


# ------------------------------------------------------------- the tasks the lifespan owns


async def test_the_lifespan_starts_the_responder_and_the_relay_and_awaits_both_on_shutdown(
    orders_host_factory: HostFactory,
) -> None:
    async with orders_host_factory() as host:
        tasks = dict(host.runtime.tasks)
        # Feature 16 adds the saga's fast path and sweeper (the consumer stays off in this host:
        # `host_environment` sets SAGA_CONSUMER_ENABLED=false; `integration/saga` turns it on).
        assert set(tasks) == {"nats-responder", "outbox-relay", "saga-fast-path", "saga-sweeper"}
        assert all(not task.done() for task in tasks.values())
        response = await readiness(host.app)
        assert (response.status_code, response.json()) == (200, {"status": "ready"})

    # the lifespan has exited: every task it created has been awaited to completion, none cancelled
    assert all(task.done() and not task.cancelled() for task in tasks.values())
    assert [task.exception() for task in tasks.values()] == [None] * len(tasks)
    after = await readiness(host.app)
    assert after.status_code == 503, "a stopped service is not ready"


async def test_shutdown_waits_for_the_request_in_flight_before_closing_what_it_uses(
    orders_host_factory: HostFactory,
    nats_client: NatsClient,
    stock_reply: Callable[..., bytes],
    reference_data: Any,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def held_stock_check(message: Any) -> None:
        entered.set()
        await release.wait()
        await message.respond(stock_reply([("SKU-A", 3, 50)]))

    await nats_client.subscribe("fulfillment.stock.check", cb=held_stock_check)
    await nats_client.flush()
    lifespan = orders_host_factory()
    host = await lifespan.__aenter__()
    shutdown: asyncio.Task[bool | None] | None = None
    try:
        body = json.dumps(
            {
                "retailerCode": "RET-01",
                "companyCode": "CMP-01",
                "currency": "EUR",
                "lines": [{"productCode": "SKU-A", "quantity": 3, "unitPrice": 1999}],
            }
        ).encode()
        in_flight = asyncio.create_task(host.client.request("orders.create", body, timeout=20))
        await asyncio.wait_for(entered.wait(), timeout=10)

        shutdown = asyncio.create_task(lifespan.__aexit__(None, None, None))
        await asyncio.sleep(0.5)
        assert not shutdown.done(), "shutdown must wait for the request that is mid-flight"
        release.set()

        reply = json.loads((await asyncio.wait_for(in_flight, timeout=15)).data)
        assert reply["status"] == "placed", reply
        await asyncio.wait_for(shutdown, timeout=15)
        assert all(task.done() for task in host.runtime.tasks.values())
    finally:
        release.set()
        if shutdown is None:
            await lifespan.__aexit__(None, None, None)


async def test_with_the_relay_disabled_no_relay_task_exists_and_kafka_is_never_contacted(
    orders_host_factory: HostFactory,
) -> None:
    # KAFKA_BROKERS points at a port nothing listens on: a producer start would fail the boot.
    async with orders_host_factory(
        OUTBOX_RELAY_ENABLED="false", KAFKA_BROKERS="127.0.0.1:1"
    ) as host:
        assert set(host.runtime.tasks) == {"nats-responder", "saga-fast-path", "saga-sweeper"}
        assert "outbox-relay" not in host.runtime.tasks
        assert (await readiness(host.app)).status_code == 200


@pytest.mark.parametrize("task_name", ["outbox-relay", "nats-responder"])
async def test_a_transport_task_that_dies_takes_readiness_down_and_names_it(
    orders_host_factory: HostFactory, task_name: str
) -> None:
    async with orders_host_factory() as host:
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
    # shutdown still completes with a task already dead


async def test_a_closed_nats_connection_takes_readiness_down_even_though_no_task_ended(
    orders_host_factory: HostFactory,
) -> None:
    async with orders_host_factory() as host:
        assert (await readiness(host.app)).status_code == 200

        await host.runtime.connection.close()

        response = await readiness(host.app)
        assert response.status_code == 503
        assert "the NATS connection is closed" in response.json()["reasons"]


async def test_readiness_is_503_before_the_lifespan_has_started() -> None:
    response = await readiness(composition_less_app())
    assert response.status_code == 503
    assert response.json()["reasons"] == ["the service has not started"]


def composition_less_app() -> Any:
    from otc_orders.main import create_app

    return create_app()


# ------------------------------------ a boot that fails part-way closes what it already opened


async def test_a_boot_that_fails_after_the_responder_task_exists_leaves_no_task_behind(
    orders_host_factory: HostFactory,
) -> None:
    # Kafka is down at boot (the ordinary compose start-up race): the producer start raises AFTER
    # the responder task was created. `nats-responder` and its `orders.create stop waiter` must
    # not outlive the failed boot.
    with pytest.raises(Exception, match="Unable to bootstrap"):
        async with orders_host_factory(KAFKA_BROKERS="127.0.0.1:1"):
            pytest.fail("the host must not come up while Kafka is unreachable")

    leaked = sorted(
        task.get_name()
        for task in asyncio.all_tasks()
        if task.get_name() in {"nats-responder", "orders.create stop waiter"} and not task.done()
    )
    assert leaked == [], f"a failed boot leaked tasks: {leaked}"


async def test_a_boot_that_fails_after_the_responder_task_exists_awaited_it_to_completion(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[asyncio.Task[None]] = []
    real_create_task = asyncio.create_task

    def recording_create_task(coro: Any, **kwargs: Any) -> asyncio.Task[None]:
        task = real_create_task(coro, **kwargs)
        created.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", recording_create_task)

    with pytest.raises(Exception, match="Unable to bootstrap"):
        async with orders_host_factory(KAFKA_BROKERS="127.0.0.1:1"):
            pytest.fail("the host must not come up while Kafka is unreachable")

    [responder] = [task for task in created if task.get_name() == "nats-responder"]
    assert responder.done(), "the responder task must have been stopped and awaited"
    assert not responder.cancelled(), "the responder task must end on its stop event, not by cancel"
    assert all(task.done() for task in created), [t.get_name() for t in created if not t.done()]


async def test_a_kafka_producer_that_cannot_start_is_stopped_before_the_boot_fails(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
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
        async with orders_host_factory():
            pytest.fail("the host must not come up while the producer cannot start")

    assert events == ["constructed", "start", "stop"]


async def test_a_boot_cancelled_while_the_producer_is_starting_leaks_no_task_and_stops_the_producer(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Cancellation is not an `Exception`: a boot cancelled mid-bootstrap (a shutdown signal during
    # the compose start-up race) must still stop the tasks and the producer, then propagate.
    events: list[str] = []
    started = asyncio.Event()

    class HangingProducer:
        def __init__(self, **options: Any) -> None:
            events.append("constructed")

        async def start(self) -> None:
            events.append("start")
            started.set()
            await asyncio.Event().wait()

        async def stop(self) -> None:
            events.append("stop")

    monkeypatch.setattr(kafka_publisher_module, "AIOKafkaProducer", HangingProducer)

    async def boot() -> None:
        async with orders_host_factory():
            pytest.fail("the host must not come up while the producer start hangs")

    booting = asyncio.create_task(boot())
    await asyncio.wait_for(started.wait(), timeout=30)
    booting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await booting

    leaked = sorted(
        task.get_name()
        for task in asyncio.all_tasks()
        if task.get_name() in {"nats-responder", "orders.create stop waiter"} and not task.done()
    )
    assert leaked == [], f"a cancelled boot leaked tasks: {leaked}"
    assert events == ["constructed", "start", "stop"], "the producer must be stopped"


async def test_a_failed_boot_awaits_the_responder_so_the_request_it_is_serving_is_answered(
    orders_host_factory: HostFactory,
    nats_client: NatsClient,
    stock_reply: Callable[..., bytes],
    reference_data: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The responder is serving a request (held at the stock check) when the producer start fails.
    # `_stop_tasks` must AWAIT the responder before the stack closes NATS and the engine: the
    # request is then answered "placed". Without the await, the connection is closed under it.
    entered, release = asyncio.Event(), asyncio.Event()
    in_flight: list[asyncio.Task[Any]] = []

    async def held_stock_check(message: Any) -> None:
        entered.set()
        await release.wait()
        await message.respond(stock_reply([("SKU-A", 3, 50)]))

    await nats_client.subscribe("fulfillment.stock.check", cb=held_stock_check)
    await nats_client.flush()
    body = json.dumps(
        {
            "retailerCode": "RET-01",
            "companyCode": "CMP-01",
            "currency": "EUR",
            "lines": [{"productCode": "SKU-A", "quantity": 3, "unitPrice": 1999}],
        }
    ).encode()

    class FailingAfterTheRequestArrivedProducer:
        def __init__(self, **options: Any) -> None:
            pass

        async def start(self) -> None:
            in_flight.append(asyncio.create_task(nats_client.request("orders.create", body, 20)))
            await asyncio.wait_for(entered.wait(), timeout=10)
            asyncio.get_running_loop().call_later(0.5, release.set)
            raise ConnectionError("broker went away")

        async def stop(self) -> None:
            pass

    monkeypatch.setattr(
        kafka_publisher_module, "AIOKafkaProducer", FailingAfterTheRequestArrivedProducer
    )

    with pytest.raises(ConnectionError, match="broker went away"):
        async with orders_host_factory():
            pytest.fail("the host must not come up while the producer cannot start")

    [request] = in_flight
    reply = json.loads((await asyncio.wait_for(request, timeout=15)).data)
    assert reply["status"] == "placed", reply


async def test_a_runtime_constructor_that_raises_still_unwinds_the_stack(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    connections: list[NatsClient] = []
    real_connect = nats.connect
    real_runtime = composition.OrdersRuntime
    attempts: list[int] = []

    async def recording_connect(*args: Any, **kwargs: Any) -> NatsClient:
        connection: NatsClient = await real_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    def runtime_that_fails_once(**kwargs: Any) -> Any:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("the runtime could not be built")
        return real_runtime(**kwargs)

    monkeypatch.setattr(nats, "connect", recording_connect)
    monkeypatch.setattr(composition, "OrdersRuntime", runtime_that_fails_once)

    with pytest.raises(RuntimeError, match="the runtime could not be built"):
        async with orders_host_factory():
            pytest.fail("the host must not come up when the runtime cannot be built")

    [connection] = connections
    assert connection.is_closed, "NATS must be closed by the unwinding stack"
    assert composition._relay_owner is None, "the relay slot must be released"
    async with orders_host_factory() as again:
        assert "outbox-relay" in again.runtime.tasks, "a second boot must be allowed"


# --------------------------------------- the registry is validated by the lifespan (items 4, 6)


async def test_a_command_with_no_registered_handler_fails_the_boot(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composition, "register_handlers", lambda registry: None)

    with pytest.raises(DispatcherValidationError) as refused:
        async with orders_host_factory():
            pytest.fail("the host must not come up with PlaceOrderCommand unhandled")

    # PlaceOrderCommand (feature 15) and the ten saga fact commands (feature 16), each by name
    assert (
        "No command handler is registered for PlaceOrderCommand. Exactly one is required."
        in refused.value.problems
    )
    assert len(refused.value.problems) == 11
    assert all(
        problem.startswith("No command handler is registered for ")
        for problem in refused.value.problems
    )


async def test_a_command_with_two_registered_handlers_fails_the_boot(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = composition.register_handlers

    def twice(registry: Any) -> None:
        original(registry)
        registry.register_command(PlaceOrderCommand, PlaceOrderCommandHandler)

    monkeypatch.setattr(composition, "register_handlers", twice)

    with pytest.raises(DispatcherValidationError) as refused:
        async with orders_host_factory():
            pytest.fail("the host must not come up with two handlers for one command")

    assert len(refused.value.problems) == 1
    assert refused.value.problems[0].startswith(
        "2 command handlers are registered for PlaceOrderCommand:"
    )


async def test_the_boot_fails_when_a_fact_command_has_no_handler(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = composition.register_handlers

    class WithoutStockReserved:
        """The real registry, except that one of the ten fact commands is never registered."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def register_command(self, command_type: type, factory: Any) -> None:
            if command_type is not HandleStockReservedFactCommand:
                self._inner.register_command(command_type, factory)

        def register_event(self, event_type: type, factory: Any) -> None:
            self._inner.register_event(event_type, factory)

    monkeypatch.setattr(
        composition,
        "register_handlers",
        lambda registry: original(cast("Any", WithoutStockReserved(registry))),
    )

    with pytest.raises(DispatcherValidationError) as refused:
        async with orders_host_factory():
            pytest.fail("the host must not come up with a saga fact command unhandled")

    assert refused.value.problems == (
        "No command handler is registered for HandleStockReservedFactCommand. "
        "Exactly one is required.",
    )


async def test_the_boot_fails_when_a_fact_command_has_two_handlers(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = composition.register_handlers

    def twice(registry: Any) -> None:
        original(registry)
        registry.register_command(HandleStockReservedFactCommand, SagaFactCommandHandler)

    monkeypatch.setattr(composition, "register_handlers", twice)

    with pytest.raises(DispatcherValidationError) as refused:
        async with orders_host_factory():
            pytest.fail("the host must not come up with two handlers for one fact command")

    assert len(refused.value.problems) == 1
    assert refused.value.problems[0].startswith(
        "2 command handlers are registered for HandleStockReservedFactCommand:"
    )


async def test_a_new_command_nobody_registered_fails_the_boot_by_name(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A command added to the application package tomorrow, with no `register_command` for it.
    class RefundOrderCommand(Command[None]):
        pass

    monkeypatch.setattr(place_order_module, "RefundOrderCommand", RefundOrderCommand, raising=False)

    with pytest.raises(DispatcherValidationError) as refused:
        async with orders_host_factory():
            pytest.fail("the host must not come up with a command that has no handler")

    assert "No command handler is registered for" in refused.value.problems[0]
    assert "RefundOrderCommand" in refused.value.problems[0]


async def test_a_port_bound_to_nothing_fails_the_boot_not_the_first_message(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composition, "NatsStockAvailability", lambda *args, **kwargs: None)

    with pytest.raises(MissingBindingError) as refused:
        async with orders_host_factory():
            pytest.fail("the host must not come up with the stock port unbound")

    assert refused.value.binding == "stock"


async def test_a_registered_handler_that_cannot_be_built_fails_the_boot_whoever_registered_it(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A command and a handler a later feature registers, whose construction raises. The boot has
    # no list of handlers of its own: it builds every one that `register_handlers` registered.
    class ShipOrderCommand(Command[None]):
        pass

    class UnbuildableHandler:
        def __init__(self, scope: Any) -> None:
            raise RuntimeError("ShipOrderCommandHandler needs a port nobody bound")

        async def handle(self, command: ShipOrderCommand) -> None: ...

    monkeypatch.setattr(place_order_module, "ShipOrderCommand", ShipOrderCommand, raising=False)
    original = composition.register_handlers

    def with_ship(registry: Any) -> None:
        original(registry)
        registry.register_command(ShipOrderCommand, UnbuildableHandler)

    monkeypatch.setattr(composition, "register_handlers", with_ship)

    with pytest.raises(RuntimeError, match="needs a port nobody bound"):
        async with orders_host_factory():
            pytest.fail("the host must not come up with a registered handler that cannot be built")


@pytest.mark.parametrize("kind", ["query", "event"])
async def test_an_unbuildable_query_or_event_handler_fails_the_boot_whoever_registered_it(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    class ListOrdersQuery(Query[int]):
        pass

    class OrderShipped:
        pass

    class UnbuildableHandler:
        def __init__(self, scope: Any) -> None:
            raise RuntimeError(f"the {kind} handler needs a port nobody bound")

    if kind == "query":
        monkeypatch.setattr(place_order_module, "ListOrdersQuery", ListOrdersQuery, raising=False)
    original = composition.register_handlers

    def with_late_handler(registry: Any) -> None:
        original(registry)
        if kind == "query":
            registry.register_query(ListOrdersQuery, UnbuildableHandler)
        else:
            registry.register_event(OrderShipped, UnbuildableHandler)

    monkeypatch.setattr(composition, "register_handlers", with_late_handler)

    with pytest.raises(RuntimeError, match=f"the {kind} handler needs a port nobody bound"):
        async with orders_host_factory():
            pytest.fail(f"the host must not come up with an unbuildable {kind} handler")


# ------------------------------- every environment read reaches the thing it configures (id 56)


class Recorded:
    def __init__(self) -> None:
        self.kafka: list[Any] = []
        self.relay: list[dict[str, Any]] = []
        self.relay_task: list[dict[str, Any]] = []
        self.stock: list[dict[str, Any]] = []


async def test_every_setting_the_composition_root_reads_reaches_its_adapter(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
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

    class RecordingStock(NatsStockAvailability):
        def __init__(self, connection: Any, **kwargs: Any) -> None:
            recorded.stock.append(kwargs)
            super().__init__(connection, **kwargs)

    monkeypatch.setattr(composition, "NatsStockAvailability", RecordingStock)
    monkeypatch.setattr(composition, "KafkaFactPublisher", RecordingPublisher)
    monkeypatch.setattr(composition, "OutboxRelay", RecordingRelay)
    monkeypatch.setattr(composition, "OutboxRelayTask", RecordingRelayTask)

    async with orders_host_factory(
        KAFKA_CLIENT_ID="otc-orders-sentinel",
        OUTBOX_BATCH_SIZE="37",
        OUTBOX_POLL_INTERVAL_MS="73",
        OUTBOX_PUBLISH_TIMEOUT_MS="4321",
        STOCK_CHECK_TIMEOUT_MS="1777",
    ) as host:
        assert host.runtime.settings.nats.stock_check_timeout_ms == 1777

    [stock] = recorded.stock
    assert stock == {"timeout_ms": 1777}, "STOCK_CHECK_TIMEOUT_MS must reach the stock adapter"
    [kafka] = recorded.kafka
    assert kafka.client_id == "otc-orders-sentinel"
    assert kafka.brokers != "localhost:9092", "KAFKA_BROKERS must come from the environment"
    [relay] = recorded.relay
    assert (relay["batch_size"], relay["publish_timeout"]) == (37, 4.321)
    [relay_task] = recorded.relay_task
    assert (relay_task["poll_interval"], relay_task["enabled"]) == (0.073, True)


# --------------------- every SAGA_* setting reaches the object it configures (#8 id 56, feature 16)

# Eleven non-default sentinels: the nine numeric ones pairwise distinct (asserted below); the two
# enable flags are booleans, and `SAGA_SWEEPER_ENABLED`'s default is already true, so its reach is
# proven by the second test's `false`. The lease rule (SO16) holds: the worst case is
# 4 x 1900 + 130 x (2**3 - 1) = 8510 ms, twice that is 17020 ms, and the lease is 91000 ms.
SAGA_SENTINELS = {
    "SAGA_COMMAND_TIMEOUT_MS": "1900",
    "SAGA_COMMAND_MAX_ATTEMPTS": "4",
    "SAGA_COMMAND_BACKOFF_MS": "130",
    "SAGA_COMMAND_LEASE_MS": "91000",
    "SAGA_PARK_RETRY_CAP_MS": "777000",
    "SAGA_SWEEPER_ENABLED": "true",
    "SAGA_SWEEPER_INTERVAL_MS": "41000",
    "SAGA_PENDING_GRACE_MS": "13300",
    "SAGA_SWEEPER_BATCH_LIMIT": "7",
    "SAGA_FAST_PATH_MAX_IN_FLIGHT": "33",
    "SAGA_CONSUMER_ENABLED": "true",
}


class SagaRecorded:
    def __init__(self) -> None:
        self.dispatcher: list[dict[str, Any]] = []
        self.adapter: list[dict[str, Any]] = []
        self.ledger: list[dict[str, Any]] = []
        self.fast_path: list[dict[str, Any]] = []
        self.sweeper: list[dict[str, Any]] = []
        self.sweeper_task: list[dict[str, Any]] = []


def _record_saga_constructors(monkeypatch: pytest.MonkeyPatch) -> SagaRecorded:
    recorded = SagaRecorded()

    class RecDispatcher(SagaCommandDispatcher):
        def __init__(self, **kwargs: Any) -> None:
            recorded.dispatcher.append(kwargs)
            super().__init__(**kwargs)

    class RecAdapter(NatsSagaCommandsAdapter):
        def __init__(self, connection: Any, **kwargs: Any) -> None:
            recorded.adapter.append(kwargs)
            super().__init__(connection, **kwargs)

    class RecLedger(SqlAlchemySagaCommandLedger):
        def __init__(self, sessions: Any, clock: Any, **kwargs: Any) -> None:
            recorded.ledger.append(kwargs)
            super().__init__(sessions, clock, **kwargs)

    class RecFastPath(SagaFastPath):
        def __init__(self, **kwargs: Any) -> None:
            recorded.fast_path.append(kwargs)
            super().__init__(**kwargs)

    class RecSweeper(SagaCommandSweeper):
        def __init__(self, **kwargs: Any) -> None:
            recorded.sweeper.append(kwargs)
            super().__init__(**kwargs)

    class RecSweeperTask(SagaCommandSweeperTask):
        def __init__(self, sweeper: Any, **kwargs: Any) -> None:
            recorded.sweeper_task.append(kwargs)
            super().__init__(sweeper, **kwargs)

    monkeypatch.setattr(composition, "SagaCommandDispatcher", RecDispatcher)
    monkeypatch.setattr(composition, "NatsSagaCommandsAdapter", RecAdapter)
    monkeypatch.setattr(composition, "SqlAlchemySagaCommandLedger", RecLedger)
    monkeypatch.setattr(composition, "SagaFastPath", RecFastPath)
    monkeypatch.setattr(composition, "SagaCommandSweeper", RecSweeper)
    monkeypatch.setattr(composition, "SagaCommandSweeperTask", RecSweeperTask)
    return recorded


async def test_every_saga_setting_the_composition_root_reads_reaches_the_object_it_configures(
    orders_host_factory: HostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    numeric = [v for v in SAGA_SENTINELS.values() if v != "true"]
    assert len(numeric) == 9, "nine numeric sentinels"
    assert len(set(numeric)) == 9, "the numeric sentinels must be pairwise distinct"
    recorded = _record_saga_constructors(monkeypatch)

    async with orders_host_factory(**SAGA_SENTINELS) as host:
        assert "saga-consumer" in host.runtime.tasks, "SAGA_CONSUMER_ENABLED=true: a consumer task"
        assert "saga-sweeper" in host.runtime.tasks, "SAGA_SWEEPER_ENABLED=true: a sweeper task"

    [dispatcher] = recorded.dispatcher
    assert dispatcher["max_attempts"] == 4, "SAGA_COMMAND_MAX_ATTEMPTS must reach the dispatcher"
    assert dispatcher["backoff_ms"] == 130, "SAGA_COMMAND_BACKOFF_MS must reach the dispatcher"
    assert dispatcher["park_cap_ms"] == 777_000, "SAGA_PARK_RETRY_CAP_MS must reach the dispatcher"
    [adapter] = recorded.adapter
    assert adapter == {"timeout_ms": 1900}, "SAGA_COMMAND_TIMEOUT_MS must reach the NATS adapter"
    [ledger] = recorded.ledger
    assert ledger["lease_ms"] == 91_000, "SAGA_COMMAND_LEASE_MS must reach the ledger"
    assert ledger["pending_grace_ms"] == 13_300, "SAGA_PENDING_GRACE_MS must reach the ledger"
    [fast_path] = recorded.fast_path
    assert fast_path["max_in_flight"] == 33, "SAGA_FAST_PATH_MAX_IN_FLIGHT must reach the fast path"
    [sweeper] = recorded.sweeper
    assert sweeper["batch_limit"] == 7, "SAGA_SWEEPER_BATCH_LIMIT must reach the sweeper"
    [sweeper_task] = recorded.sweeper_task
    assert (sweeper_task["interval"], sweeper_task["enabled"]) == (41.0, True), (
        "SAGA_SWEEPER_INTERVAL_MS and SAGA_SWEEPER_ENABLED must reach the sweeper task"
    )


async def test_the_saga_enable_flags_decide_which_tasks_exist(
    orders_host_factory: HostFactory,
) -> None:
    async with orders_host_factory(
        SAGA_SWEEPER_ENABLED="false", SAGA_CONSUMER_ENABLED="false"
    ) as host:
        assert "saga-sweeper" not in host.runtime.tasks, "SAGA_SWEEPER_ENABLED=false: no sweeper"
        assert "saga-consumer" not in host.runtime.tasks, "SAGA_CONSUMER_ENABLED=false: no consumer"
        assert "saga-fast-path" in host.runtime.tasks


def test_saga_sentinels_cover_all_saga_environment_variables() -> None:
    """SAGA_SENTINELS covers exactly the SAGA_* variables of the unit settings test."""
    unit_file = Path(__file__).resolve().parents[1] / "unit" / "test_orders_settings_env.py"
    tree = ast.parse(unit_file.read_text())
    env_keys = [
        key.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "ENV"
        and isinstance(node.value, ast.Dict)
        for key in node.value.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    ]
    unit_saga_vars = {name for name in env_keys if name.startswith("SAGA_")}
    assert unit_saga_vars, "ENV literal not found or holds no SAGA_ keys"
    sentinel_vars = set(SAGA_SENTINELS)
    assert sentinel_vars == unit_saga_vars, (
        f"SAGA_SENTINELS missing: {unit_saga_vars - sentinel_vars}\n"
        f"SAGA_SENTINELS extra: {sentinel_vars - unit_saga_vars}"
    )


# ---------------------------------- at most one relay per process; no multi-worker (item 8)


async def test_more_than_one_worker_with_the_relay_enabled_refuses_to_boot_before_connecting(
    orders_host_factory: HostFactory,
) -> None:
    # the database, NATS and Kafka addresses are dead: the refusal must come BEFORE any of them
    with pytest.raises(MultipleOutboxRelaysError, match="WEB_CONCURRENCY=2"):
        async with orders_host_factory(
            WEB_CONCURRENCY="2",
            ORDERS_DATABASE_URL="postgresql+asyncpg://nobody:x@127.0.0.1:1/none",
            NATS_URL="nats://127.0.0.1:1",
            KAFKA_BROKERS="127.0.0.1:1",
        ):
            pytest.fail("two workers must not each run a relay")


async def test_several_workers_are_fine_while_the_relay_is_disabled(
    orders_host_factory: HostFactory,
) -> None:
    async with orders_host_factory(WEB_CONCURRENCY="4", OUTBOX_RELAY_ENABLED="false") as host:
        assert (await readiness(host.app)).status_code == 200


async def test_a_second_relay_owning_runtime_in_one_process_is_refused_and_the_first_survives(
    orders_host_factory: HostFactory,
) -> None:
    async with orders_host_factory() as first:
        with pytest.raises(MultipleOutboxRelaysError, match="already runs an outbox relay"):
            async with orders_host_factory():
                pytest.fail("a second relay in this process must be refused")
        assert (await readiness(first.app)).status_code == 200
    # the slot is released by shutdown: a later start is allowed again
    async with orders_host_factory() as again:
        assert "outbox-relay" in again.runtime.tasks


def test_a_real_uvicorn_with_two_workers_and_the_relay_enabled_refuses_to_start_a_worker(
    tmp_path: Path,
) -> None:
    env = {
        "PATH": str(Path(sys.executable).parent),
        "ORDERS_DATABASE_URL": "postgresql+asyncpg://nobody:x@127.0.0.1:1/none",
        "OUTBOX_RELAY_ENABLED": "true",
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "otc_orders.main:app", "--workers", "2", "--port", "0"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert server.stdout is not None
    seen: list[str] = []
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            line = server.stdout.readline()
            if not line:
                break
            seen.append(line)
            if "every worker would run an outbox relay" in line:
                break
        else:
            pytest.fail("no refusal within 60 s:\n" + "".join(seen))
    finally:
        server.terminate()
        server.wait(timeout=30)
    output = "".join(seen)
    assert re.search(r"MultipleOutboxRelaysError: this process is a multi-worker", output), output
