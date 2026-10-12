"""The composition root of the Gateway: the only place adapters are chosen.

* Configuration is read through pydantic-settings ONLY (`load_settings`); no other module of the
  service touches the environment (`tests/architecture/test_composition_env_reads.py`), and
  `python -m otc_gateway` takes its port from here too (#8 id 96).
* Every handler is registered explicitly, one statement each, in `register_handlers` (no
  decorator, no loop, no lambda: `tests/architecture/test_registration_behaviour.py` runs this root
  and checks each registration against its own statement); the registry is validated by
  `build_dispatcher`, so a command or query with zero handlers or two fails the boot.
* `start_runtime` is what the lifespan runs. Its STATEMENT ORDER is the boot order: the dispatcher's
  validation (before anything is opened), the committed contract read, a MongoDB round trip, the
  NATS connection WITHIN A BOUND (`nats.connect` keeps retrying 60 x 2 s by default: Phase 11's
  `1a9ac06`), the adapters, and every registered factory built once so a missing binding raises
  here and not as an `AttributeError` on the first request. Everything it opens is owned by one
  `AsyncExitStack`: a failure at any step closes what was already opened, in reverse.
* The Gateway starts ONE asyncio task, the stream signal subscriber (feature 26, one task per
  transport): started here, bounded, stopped and AWAITED by `RunningGateway.stop` BEFORE the NATS
  connection it reads from is drained (the exit stack closes in reverse), and its death takes
  `/health/ready` down (`streamSignals`). The two connections the Gateway owns (the NATS client, the
  MongoDB client) belong to this lifespan and are closed in the loop that opened them.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from typing import Any

import nats.errors
from nats.aio.client import Client as NatsClient
from pymongo import AsyncMongoClient

import otc_gateway.application
from otc_cqrs import Dispatcher, HandlerRegistry
from otc_gateway.application.auth_handlers import GetCurrentUserHandler, LoginHandler
from otc_gateway.application.billing_handlers import ListCreditsHandler, ListInvoicesHandler
from otc_gateway.application.catalog_handlers import (
    ListCompaniesHandler,
    ListProductsHandler,
    ListRetailersHandler,
)
from otc_gateway.application.messages import (
    CancelOrderCommand,
    GetCurrentUserQuery,
    GetOrderQuery,
    ListCompaniesQuery,
    ListCreditsQuery,
    ListInvoicesQuery,
    ListOrdersQuery,
    ListProductsQuery,
    ListRetailersQuery,
    ListStockQuery,
    LoginCommand,
    PlaceOrderCommand,
    RegisterInvoicePaymentCommand,
    ReplenishStockCommand,
)
from otc_gateway.application.order_commands import CancelOrderHandler, PlaceOrderHandler
from otc_gateway.application.order_queries import GetOrderHandler, ListOrdersHandler
from otc_gateway.application.payment_handlers import RegisterPaymentHandler
from otc_gateway.application.scope import GatewayScope
from otc_gateway.application.stock_handlers import ListStockHandler, ReplenishStockHandler
from otc_gateway.application.stream.hub import StreamHub
from otc_gateway.domain.issued_order_window import IssuedOrderWindow
from otc_gateway.domain.login_throttle import LoginThrottle
from otc_gateway.infrastructure.health_checks import HealthCheck
from otc_gateway.infrastructure.jwt_token_service import JwtTokenService
from otc_gateway.infrastructure.mongo_order_read_model import COLLECTION, MongoOrderReadModel
from otc_gateway.infrastructure.nats_rpc_client import NatsRpcClient
from otc_gateway.infrastructure.operator_directory import ConfiguredOperator
from otc_gateway.infrastructure.settings import (
    DocsSettings,
    IssuedOrderWindowSettings,
    JwtSettings,
    LoginThrottleSettings,
    MongoSettings,
    NatsSettings,
    OperatorSettings,
    ServerSettings,
    SseSettings,
)
from otc_gateway.infrastructure.stream_signal_subscriber import (
    StreamSubscriberDown,
    StreamSubscriberHandle,
    start_stream_subscriber,
)
from otc_gateway.infrastructure.system_clock import SystemClock, monotonic_ms
from otc_gateway.presentation.runtime import GatewayRuntime

log = logging.getLogger("otc_gateway.composition")

# `nats.connect` with its defaults keeps retrying 60 x 2 s before raising (measured by the
# Projector's `PR45`: still connecting after 60 s), so the bound on the boot's connection is ours.
NATS_CONNECT_SECONDS = 10.0
MONGO_PING_SECONDS = 10.0
STREAM_SUBSCRIBE_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class GatewaySettings:
    """Every settings class of the service, each constructed exactly once, here."""

    server: ServerSettings
    nats: NatsSettings
    mongo: MongoSettings
    jwt: JwtSettings
    operator: OperatorSettings
    login_throttle: LoginThrottleSettings
    issued_orders: IssuedOrderWindowSettings
    docs: DocsSettings
    sse: SseSettings


def load_settings() -> GatewaySettings:
    return GatewaySettings(
        server=ServerSettings(),
        nats=NatsSettings(),
        mongo=MongoSettings(),
        jwt=JwtSettings(),
        operator=OperatorSettings(),
        login_throttle=LoginThrottleSettings(),
        issued_orders=IssuedOrderWindowSettings(),
        docs=DocsSettings(),
        sse=SseSettings(),
    )


# ------------------------------------------------------------------------------ the dispatcher

type Wiring = tuple[Dispatcher[GatewayScope], list[Callable[[GatewayScope], object]]]


def register_handlers(registry: HandlerRegistry[GatewayScope]) -> None:
    """Explicit registration: one statement per message type, no loop, no lambda, no decorator."""
    registry.register_command(LoginCommand, LoginHandler)
    registry.register_command(PlaceOrderCommand, PlaceOrderHandler)
    registry.register_command(CancelOrderCommand, CancelOrderHandler)
    registry.register_command(RegisterInvoicePaymentCommand, RegisterPaymentHandler)
    registry.register_command(ReplenishStockCommand, ReplenishStockHandler)
    registry.register_query(GetCurrentUserQuery, GetCurrentUserHandler)
    registry.register_query(ListOrdersQuery, ListOrdersHandler)
    registry.register_query(GetOrderQuery, GetOrderHandler)
    registry.register_query(ListStockQuery, ListStockHandler)
    registry.register_query(ListInvoicesQuery, ListInvoicesHandler)
    registry.register_query(ListCreditsQuery, ListCreditsHandler)
    registry.register_query(ListProductsQuery, ListProductsHandler)
    registry.register_query(ListRetailersQuery, ListRetailersHandler)
    registry.register_query(ListCompaniesQuery, ListCompaniesHandler)


def _wire() -> Wiring:
    registry = HandlerRegistry[GatewayScope]()
    register_handlers(registry)
    return registry.build(otc_gateway.application), registry.registered_factories()


def build_dispatcher() -> Dispatcher[GatewayScope]:
    """Register, then validate against every command and query under the application package.

    Pure (no I/O): `tests/architecture/test_registration_behaviour.py` runs it without a server."""
    return _wire()[0]


# --------------------------------------------------------------------------- the externals


async def connect_nats(url: str) -> NatsClient:
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


def _mongo_client(uri: str, server_selection_timeout_ms: int) -> AsyncMongoClient[dict[str, Any]]:
    return AsyncMongoClient(uri, serverSelectionTimeoutMS=server_selection_timeout_ms)


def _read_contract(settings: DocsSettings) -> str:
    return settings.openapi_path.read_text(encoding="utf-8")


async def _start_stream_subscriber(
    connection: NatsClient, hub: StreamHub, subscribe_seconds: float
) -> StreamSubscriberHandle:
    return await start_stream_subscriber(connection, hub, subscribe_seconds=subscribe_seconds)


@dataclass(frozen=True, slots=True)
class Externals:
    """The external collaborators, real by default and replaceable by a test that wants to observe
    the ORDER of the boot steps with recording fakes."""

    wire: Callable[[], Wiring] = _wire
    read_contract: Callable[[DocsSettings], str] = _read_contract
    mongo_client: Callable[[str, int], AsyncMongoClient[dict[str, Any]]] = _mongo_client
    nats_connect: Callable[[str], Awaitable[NatsClient]] = connect_nats
    stream_subscriber: Callable[
        [NatsClient, StreamHub, float], Awaitable[StreamSubscriberHandle]
    ] = _start_stream_subscriber
    clock: SystemClock = field(default_factory=SystemClock)


# ------------------------------------------------------------------------------------ the runtime


class RunningGateway:
    """What the lifespan holds while the service runs."""

    def __init__(self, *, runtime: GatewayRuntime, stack: AsyncExitStack) -> None:
        self.runtime = runtime
        self._stack = stack

    async def stop(self) -> None:
        """Close what `start_runtime` opened, in the loop that opened it."""
        await self._stack.aclose()


async def _close_nats(connection: NatsClient) -> None:
    with suppress(nats.errors.Error):
        await connection.drain()


async def start_runtime(
    settings: GatewaySettings,
    *,
    externals: Externals | None = None,
    nats_connect_seconds: float = NATS_CONNECT_SECONDS,
    mongo_ping_seconds: float = MONGO_PING_SECONDS,
    stream_subscribe_seconds: float = STREAM_SUBSCRIBE_SECONDS,
) -> RunningGateway:
    outside = externals if externals is not None else Externals()
    async with AsyncExitStack() as stack:
        # 1. The dispatcher is validated before anything is opened: a missing or duplicate handler
        #    is a boot failure that cost no connection.
        dispatcher, registered_factories = outside.wire()

        # 2. The committed contract `GET /docs` renders: absent, the boot fails.
        openapi_document = outside.read_contract(settings.docs)

        # 3. MongoDB, with a real round trip (an unreachable or unauthenticated server fails here).
        client = outside.mongo_client(
            settings.mongo.uri, settings.mongo.server_selection_timeout_ms
        )
        stack.push_async_callback(client.close)
        database = client.get_database(settings.mongo.database)
        async with asyncio.timeout(mongo_ping_seconds):
            await database.command("ping")
        collection = database.get_collection(COLLECTION)

        # 4. NATS, within a bound: an unreachable broker fails the boot, it does not run with every
        #    RPC route answering 503.
        try:
            async with asyncio.timeout(nats_connect_seconds):
                connection = await outside.nats_connect(settings.nats.url)
        except TimeoutError as error:
            raise RuntimeError(
                f"NATS_URL {settings.nats.url} did not accept a connection within "
                f"{nats_connect_seconds} s: the RPC routes cannot be served"
            ) from error
        stack.push_async_callback(_close_nats, connection)

        # 5. The stream: the hub, and the one task that feeds it from NATS, started within a bound
        #    (an unsubscribable broker fails the boot, it does not serve a stream that never moves).
        #    Pushed AFTER the NATS close, so the stack stops the task before it drains the
        # connection.
        clock = outside.clock
        hub = StreamHub(
            lambda: int(clock.now().timestamp() * 1000),
            replay_capacity=settings.sse.buffer_capacity,
            subscriber_capacity=settings.sse.client_queue_capacity,
        )
        subscriber = await outside.stream_subscriber(connection, hub, stream_subscribe_seconds)
        stack.push_async_callback(subscriber.stop)

        # 6. The adapters, and every registered factory built once so a missing binding raises
        #    here, never as an AttributeError on the first request.
        tokens = JwtTokenService(
            secret=settings.jwt.signing_key,
            issuer=settings.jwt.issuer,
            expires_in=settings.jwt.expires_in,
            clock=clock,
        )
        scope = GatewayScope(
            rpc=NatsRpcClient(connection, timeout_ms=settings.nats.rpc_timeout_ms),
            read_model=MongoOrderReadModel(collection),
            issued_orders=IssuedOrderWindow(
                monotonic_ms,
                ttl_ms=settings.issued_orders.ttl_ms,
                capacity=settings.issued_orders.capacity,
            ),
            tokens=tokens,
            operators=ConfiguredOperator(
                username=settings.operator.username,
                password=settings.operator.secret_password,
                display_name=settings.operator.display_name,
            ),
        )
        for factory in registered_factories:
            factory(scope)

        async def ping_nats() -> None:
            if not connection.is_connected:
                raise ConnectionError("the NATS connection is not connected")
            await connection.flush()

        async def stream_signals() -> None:
            reason = subscriber.unready_reason()
            if reason is not None:
                raise StreamSubscriberDown(reason)

        runtime = GatewayRuntime(
            dispatcher=dispatcher,
            scope=scope,
            tokens=tokens,
            login_throttle=LoginThrottle(
                monotonic_ms,
                limit=settings.login_throttle.limit,
                window_ms=settings.login_throttle.window_ms,
            ),
            clock=clock,
            health_checks=(
                HealthCheck("rpcTransport", ping_nats),
                HealthCheck("readModel", lambda: database.command("ping")),
                HealthCheck("streamSignals", stream_signals),
            ),
            openapi_document=openapi_document,
            stream_hub=hub,
            stream_ping_interval_seconds=settings.sse.ping_interval_ms / 1000,
        )
        # `pop_all()` is the last statement: from here the returned object owns the connections.
        return RunningGateway(runtime=runtime, stack=stack.pop_all())
