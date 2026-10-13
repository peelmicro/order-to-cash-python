"""The composition root (feature 25, acceptance item 5's second half): the registry is validated in
the lifespan, so a command or query with zero handlers or two fails the boot BEFORE any connection
is opened; the boot's statement order; every setting reaches the adapter it configures; the NATS
connect is bounded; and a failure at any step closes what was already opened.

The external collaborators are the fields of `Externals`; here they are recording fakes, so the
ORDER of the steps is an observed fact (an ordered call log), not an inference.
"""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import jwt
import pytest

from otc_cqrs import DispatcherValidationError, HandlerRegistry
from otc_gateway import composition
from otc_gateway.application.ports.tokens import TokenClaims
from otc_gateway.application.scope import GatewayScope, MissingBindingError
from otc_gateway.composition import (
    Externals,
    GatewaySettings,
    build_dispatcher,
    load_settings,
    start_runtime,
)
from otc_gateway.infrastructure.nats_rpc_client import NatsRpcClient

REPO_ROOT = Path(__file__).resolve().parents[4]


class World:
    """Everything the boot touches, with a log of what it was asked to do and in which order."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.mongo_uri: str | None = None
        self.mongo_database: str | None = None
        self.mongo_timeout_ms: int | None = None
        self.nats_url: str | None = None
        self.contract_path: Path | None = None
        self.mongo_closed = False
        self.nats_drained = False
        self.ping_fails = False
        self.nats_connected = True

    def wire(self) -> Any:
        self.calls.append("wire")
        return composition._wire()

    def read_contract(self, settings: Any) -> str:
        self.calls.append("read_contract")
        self.contract_path = settings.openapi_path
        return "openapi: 3.1.0\n"

    def mongo_client(self, uri: str, server_selection_timeout_ms: int = 0) -> Any:
        self.mongo_timeout_ms = server_selection_timeout_ms
        self.calls.append("mongo_client")
        self.mongo_uri = uri
        world = self

        class Collection:
            pass

        class Database:
            async def command(self, name: str) -> dict[str, int]:
                world.calls.append(f"mongo.{name}")
                if world.ping_fails:
                    raise ConnectionError("mongo is down")
                return {"ok": 1}

            def get_collection(self, name: str) -> Collection:
                world.calls.append(f"collection:{name}")
                return Collection()

        class Client:
            def get_database(self, name: str) -> Database:
                world.mongo_database = name
                return Database()

            async def close(self) -> None:
                world.mongo_closed = True
                world.calls.append("mongo.close")

        return Client()

    async def nats_connect(self, url: str) -> Any:
        self.calls.append("nats_connect")
        self.nats_url = url
        world = self

        class Subscription:
            def __init__(self, subject: str) -> None:
                self.subject = subject

            @property
            def messages(self) -> Any:
                return self._messages()

            async def _messages(self) -> Any:
                try:
                    await asyncio.Event().wait()  # no signal ever arrives
                    yield None
                finally:
                    world.calls.append(f"stream.cancelled:{self.subject}")

        class Connection:
            is_connected = world.nats_connected
            _timeout_ms = 0

            async def subscribe(self, subject: str) -> Subscription:
                world.calls.append(f"nats.subscribe:{subject}")
                return Subscription(subject)

            async def flush(self, timeout: int = 10) -> None:  # noqa: ASYNC109 - nats-py's name
                world.calls.append("nats.flush")

            async def drain(self) -> None:
                world.nats_drained = True
                world.calls.append("nats.drain")

        return Connection()

    def externals(self, **override: Any) -> Externals:
        values: dict[str, Any] = {
            "wire": self.wire,
            "read_contract": self.read_contract,
            "mongo_client": self.mongo_client,
            "nats_connect": self.nats_connect,
        }
        return Externals(**(values | override))


@pytest.fixture
def settings(required_environment: pytest.MonkeyPatch) -> GatewaySettings:
    return load_settings()


def leftover_tasks() -> set[asyncio.Task[Any]]:
    return {t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()}


# ----------------------------------------------------------------- acceptance 5: zero and two


class DroppingRegistry[S](HandlerRegistry[S]):
    """The real registry whose `register_command` registers NOTHING (zero handlers)."""

    def register_command(self, command_type: Any, factory: Any) -> None:
        return None


class DoublingRegistry[S](HandlerRegistry[S]):
    """The real registry whose `register_query` registers TWICE (two handlers)."""

    def register_query(self, query_type: Any, factory: Any) -> None:
        super().register_query(query_type, factory)
        super().register_query(query_type, factory)


def test_the_real_registration_builds_a_dispatcher_with_fourteen_handlers() -> None:
    dispatcher, factories = composition._wire()

    assert dispatcher is not None
    assert len(factories) == 14  # 5 commands + 9 queries, counted from `register_handlers`
    assert len(dispatcher._commands) == 5
    assert len(dispatcher._queries) == 9


async def test_zero_handlers_fail_the_boot_before_anything_is_opened(
    monkeypatch: pytest.MonkeyPatch, settings: GatewaySettings
) -> None:
    monkeypatch.setattr(composition, "HandlerRegistry", DroppingRegistry)
    world = World()
    with pytest.raises(DispatcherValidationError) as raised:
        await start_runtime(settings, externals=world.externals(wire=composition._wire))

    assert "PlaceOrderCommand" in str(raised.value)
    assert "LoginCommand" in str(raised.value)
    assert world.calls == [], f"a connection was opened before the dispatcher failed: {world.calls}"


async def test_two_handlers_fail_the_boot_before_anything_is_opened(
    monkeypatch: pytest.MonkeyPatch, settings: GatewaySettings
) -> None:
    monkeypatch.setattr(composition, "HandlerRegistry", DoublingRegistry)
    world = World()
    with pytest.raises(DispatcherValidationError) as raised:
        await start_runtime(settings, externals=world.externals(wire=composition._wire))

    assert "2 query handlers are registered for GetOrderQuery" in str(raised.value)
    assert world.calls == []
    assert world.mongo_uri is None
    assert world.nats_url is None


def test_every_command_and_query_of_the_application_has_exactly_one_handler() -> None:
    """The validation `build` runs, stated as a test: the universe is every message under the
    application package, and `build_dispatcher` raises on any that is missing or doubled."""
    dispatcher = build_dispatcher()

    assert dispatcher is not None


# ----------------------------------------------------------------- the boot, in order


async def test_the_boot_runs_in_the_documented_order(settings: GatewaySettings) -> None:
    world = World()

    running = await start_runtime(settings, externals=world.externals())

    assert world.calls == [
        "wire",
        "read_contract",
        "mongo_client",
        "mongo.ping",
        "collection:order_timeline",
        "nats_connect",
        "nats.subscribe:readmodel.order.updated.*",
        "nats.subscribe:readmodel.timeline.appended.*",
        "nats.flush",  # the server knows both subscriptions before the boot returns
    ]
    await running.stop()
    # closed in reverse order of opening: the subscriber's loops are cancelled BEFORE the connection
    # they read from is drained (two loops, so two cancellations, in either order)
    assert sorted(world.calls[-4:-2]) == [
        "stream.cancelled:readmodel.order.updated.*",
        "stream.cancelled:readmodel.timeline.appended.*",
    ], "the stream subscriber's loops were not cancelled before the NATS connection was drained"
    assert world.calls[-2:] == ["nats.drain", "mongo.close"]


async def test_a_failing_mongo_ping_fails_the_boot_and_closes_the_client(
    settings: GatewaySettings,
) -> None:
    world = World()
    world.ping_fails = True
    before = leftover_tasks()

    with pytest.raises(ConnectionError, match="mongo is down"):
        await start_runtime(settings, externals=world.externals())

    assert world.mongo_closed
    assert world.nats_url is None  # NATS was never contacted
    assert leftover_tasks() == before


async def test_an_unreachable_nats_fails_the_boot_within_the_bound_naming_nats_url_and_closes_mongo(
    settings: GatewaySettings,
) -> None:
    world = World()

    async def never(url: str) -> Any:
        world.calls.append("nats_connect")
        await asyncio.sleep(3600)

    before = leftover_tasks()

    async def boot() -> None:
        try:
            async with asyncio.timeout(5):
                await start_runtime(
                    settings,
                    externals=world.externals(
                        nats_connect=cast("Callable[[str], Awaitable[Any]]", never)
                    ),
                    nats_connect_seconds=0.05,
                )
        except TimeoutError:
            pytest.fail("the Gateway's boot did not fail within 5 s against a 0.05 s NATS bound")

    with pytest.raises(RuntimeError) as raised:
        await boot()

    assert "NATS_URL nats://localhost:4222" in str(raised.value)
    assert "0.05 s" in str(raised.value)
    assert world.mongo_closed
    assert leftover_tasks() == before


async def test_a_missing_contract_file_fails_the_boot_before_any_connection(
    settings: GatewaySettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GATEWAY_OPENAPI_PATH", str(tmp_path / "absent.yaml"))
    world = World()
    reading = Externals(
        wire=world.wire, mongo_client=world.mongo_client, nats_connect=world.nats_connect
    )

    with pytest.raises(FileNotFoundError):
        await start_runtime(load_settings(), externals=reading)

    assert world.mongo_uri is None
    assert world.nats_url is None


# ----------------------------------------------------------------- each setting reaches its adapter


async def test_each_setting_reaches_the_adapter_it_configures(
    required_environment: pytest.MonkeyPatch,
) -> None:
    required_environment.setenv("NATS_URL", "nats://nats.sentinel:4999")
    required_environment.setenv("MONGO_INITDB_ROOT_PASSWORD", "mongo-sentinel-pw")
    required_environment.setenv("MONGO_HOST", "mongo.sentinel")
    required_environment.setenv("MONGO_DB_READMODEL", "readmodel_sentinel")
    required_environment.setenv("GATEWAY_READ_MODEL_TIMEOUT_MS", "1234")
    required_environment.setenv("GATEWAY_RPC_TIMEOUT_MS", "4321")
    required_environment.setenv("JWT_ISSUER", "issuer-sentinel")
    required_environment.setenv("JWT_EXPIRES_IN", "777")
    required_environment.setenv("JWT_SECRET", "sentinel-signing-key-0123456789abcdef")
    required_environment.setenv("GATEWAY_LOGIN_RATE_LIMIT", "2")
    required_environment.setenv("GATEWAY_ISSUED_ORDER_WINDOW_CAPACITY", "1")
    required_environment.setenv("GATEWAY_SSE_BUFFER_CAPACITY", "7")
    required_environment.setenv("GATEWAY_SSE_PING_INTERVAL_MS", "4321")
    required_environment.setenv("GATEWAY_SSE_CLIENT_QUEUE_CAPACITY", "3")
    required_environment.setenv("GATEWAY_OPERATOR_USERNAME", "operator-sentinel")
    required_environment.setenv("GATEWAY_OPERATOR_PASSWORD", "operator-pw-sentinel")
    required_environment.setenv(
        "GATEWAY_OPENAPI_PATH", str(REPO_ROOT / "specs/shared/openapi.yaml")
    )
    world = World()
    reading = Externals(
        wire=world.wire, mongo_client=world.mongo_client, nats_connect=world.nats_connect
    )

    running = await start_runtime(load_settings(), externals=reading)
    runtime = running.runtime

    assert world.nats_url == "nats://nats.sentinel:4999"
    assert world.mongo_uri is not None
    assert "mongo.sentinel" in world.mongo_uri
    assert "mongo-sentinel-pw" in world.mongo_uri
    assert world.mongo_database == "readmodel_sentinel"
    assert world.mongo_timeout_ms == 1234
    rpc = runtime.scope.rpc
    assert isinstance(rpc, NatsRpcClient)
    assert rpc._timeout_ms == 4321
    issued = runtime.tokens.issue(TokenClaims("operator-sentinel", ()))
    assert issued.expires_in == 777
    claims = jwt.decode(
        issued.access_token,
        "sentinel-signing-key-0123456789abcdef",
        algorithms=["HS256"],
        issuer="issuer-sentinel",
    )
    assert claims["sub"] == "operator-sentinel"
    assert runtime.scope.operators.authenticate("operator-sentinel", "operator-pw-sentinel")
    assert runtime.scope.operators.authenticate("operator-sentinel", "operator") is None
    assert [runtime.login_throttle.check("x") for _ in range(3)][-1] > 0  # limit 2
    runtime.scope.issued_orders.record(UUID(int=1))
    runtime.scope.issued_orders.record(UUID(int=2))
    assert len(runtime.scope.issued_orders) == 1  # capacity 1
    assert runtime.openapi_document.startswith("openapi: 3.1.0")
    assert runtime.stream_ping_interval_seconds == 4.321, "GATEWAY_SSE_PING_INTERVAL_MS (ms -> s)"
    hub = runtime.stream_hub
    frames = [hub.publish("order.updated", UUID(int=9), "{}") for _ in range(8)]
    assert hub.replay_after(frames[0].cursor).resumed is False  # buffer 7: the first aged out
    assert hub.replay_after(frames[1].cursor).resumed is True
    queue = hub.subscribe()
    for _ in range(4):
        hub.publish("order.updated", UUID(int=9), "{}")
    assert queue.overflowed is True  # client queue 3: the fourth frame overflowed it
    await running.stop()


async def test_the_readiness_probes_are_the_real_connections_probes(
    settings: GatewaySettings,
) -> None:
    world = World()
    running = await start_runtime(settings, externals=world.externals())
    world.calls.clear()

    results = await asyncio.gather(*(c.run() for c in running.runtime.health_checks))

    assert [(r.name, r.up) for r in results] == [
        ("rpcTransport", True),
        ("readModel", True),
        ("streamSignals", True),
    ]
    assert sorted(world.calls) == ["mongo.ping", "nats.flush"]
    await running.stop()


async def test_a_nats_connection_that_is_not_connected_is_down_even_if_flush_would_buffer(
    settings: GatewaySettings,
) -> None:
    world = World()
    world.nats_connected = False
    running = await start_runtime(settings, externals=world.externals())

    results = {
        r.name: r for r in await asyncio.gather(*(c.run() for c in running.runtime.health_checks))
    }

    assert results["rpcTransport"].up is False
    assert results["rpcTransport"].detail == "NatsNotConnectedError"
    assert results["readModel"].up is True
    await running.stop()


async def test_r55_a_dead_stream_subscriber_takes_readiness_down_naming_the_check(
    settings: GatewaySettings,
) -> None:
    world = World()
    running = await start_runtime(settings, externals=world.externals())
    try:
        subscriber_task = next(
            t for t in asyncio.all_tasks() if t.get_name() == "gateway-stream-signal"
        )
        subscriber_task.cancel()
        await asyncio.wait({subscriber_task})
        results = {
            r.name: r
            for r in await asyncio.gather(*(c.run() for c in running.runtime.health_checks))
        }
    finally:
        await running.stop()

    assert "streamSignals" in results, "readiness has no check for the stream subscriber"
    assert results["streamSignals"].up is False
    assert results["streamSignals"].detail == "StreamSubscriberDown"
    assert results["rpcTransport"].up is True
    assert results["readModel"].up is True


async def test_r55_a_stream_subscriber_that_cannot_subscribe_fails_the_boot_and_leaves_no_task(
    settings: GatewaySettings,
) -> None:
    world = World()
    before = leftover_tasks()

    async def hangs(connection: Any, hub: Any, seconds: float) -> Any:
        from otc_gateway.infrastructure.stream_signal_subscriber import start_stream_subscriber

        class Mute:
            async def subscribe(self, subject: str) -> Any:
                await asyncio.Event().wait()

        return await start_stream_subscriber(Mute(), hub, subscribe_seconds=0.1)  # type: ignore[arg-type]

    with pytest.raises(TimeoutError):
        await start_runtime(settings, externals=world.externals(stream_subscriber=hangs))

    assert world.mongo_closed
    assert world.nats_drained, "the NATS connection was left open by a failed boot"
    assert leftover_tasks() == before


# ----------------------------------------------------------------- a missing binding raises at boot


def test_the_scope_refuses_a_binding_the_root_forgot() -> None:
    with pytest.raises(MissingBindingError, match="'operators'"):
        GatewayScope(
            rpc=cast("Any", object()),
            read_model=cast("Any", object()),
            issued_orders=cast("Any", object()),
            tokens=cast("Any", object()),
            operators=cast("Any", None),
        )


async def test_a_handler_that_cannot_be_built_fails_the_boot_not_the_first_request(
    settings: GatewaySettings,
) -> None:
    class Unbuildable:
        def __init__(self, scope: GatewayScope) -> None:
            raise RuntimeError("a binding this handler needs is missing")

    world = World()

    def broken_wire() -> Any:
        dispatcher, _ = composition._wire()
        return dispatcher, [Unbuildable]

    with pytest.raises(RuntimeError, match="a binding this handler needs is missing"):
        await start_runtime(settings, externals=world.externals(wire=broken_wire))

    assert world.mongo_closed  # what the boot had opened was closed
    assert world.nats_drained
