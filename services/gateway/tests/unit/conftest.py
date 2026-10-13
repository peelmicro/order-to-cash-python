"""Unit fixtures of the Gateway: the REAL application (routes, middlewares, dispatcher, JWT service,
operator check, login throttle, issued-order window) over a FAKE RPC client and a FAKE read model.

Loop scope: nothing here owns a loop; the harness's `httpx.AsyncClient` is created and closed by the
test that asks for it, in that test's own (function) loop.

Test modules cannot import this conftest (importlib mode), so the harness is returned by a fixture
and its pieces are reached by attribute.
"""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio

from otc_contracts import WireModel, to_wire_json
from otc_gateway.application.errors import RpcCallError
from otc_gateway.application.ports.order_read_model import (
    OrderListFilter,
    ReadModelOrder,
    ReadModelPage,
)
from otc_gateway.application.scope import GatewayScope
from otc_gateway.application.stream.hub import StreamHub
from otc_gateway.composition import build_dispatcher
from otc_gateway.domain.issued_order_window import IssuedOrderWindow
from otc_gateway.domain.login_throttle import LoginThrottle
from otc_gateway.infrastructure.health_checks import HealthCheck
from otc_gateway.infrastructure.jwt_token_service import JwtTokenService
from otc_gateway.infrastructure.observability.telemetry import build_telemetry
from otc_gateway.infrastructure.operator_directory import ConfiguredOperator
from otc_gateway.presentation.app import create_app
from otc_gateway.presentation.runtime import GatewayRuntime

REPO_ROOT = Path(__file__).resolve().parents[4]
JWT_SECRET = "unit-test-secret-0123456789abcdef-0123"  # 39 bytes: above RFC 7518's 32
JWT_ISSUER = "order-to-cash"
OPERATOR_USERNAME = "operator"
OPERATOR_PASSWORD = "unit-test-operator-password"
DISPLAY_NAME = "Order-To-Cash Operator"


@dataclass
class RpcCall:
    subject: str
    request: WireModel
    reply_type: type[WireModel]
    correlation_id: UUID
    request_id: UUID

    @property
    def wire(self) -> dict[str, Any]:
        """What the responder would receive as the body: the one serializer's bytes, parsed."""
        parsed: dict[str, Any] = json.loads(to_wire_json(self.request))
        return parsed


type Reply = WireModel | RpcCallError | Callable[[RpcCall], WireModel | RpcCallError]


class FakeRpc:
    """Answers each subject with a queued reply (a model, an error to raise, or a callable)."""

    def __init__(self) -> None:
        self.calls: list[RpcCall] = []
        self.replies: dict[str, list[Reply]] = {}

    def will_reply(self, subject: str, *replies: Reply) -> None:
        self.replies.setdefault(subject, []).extend(replies)

    async def call[R: WireModel](
        self,
        subject: str,
        request: WireModel,
        reply_type: type[R],
        *,
        correlation_id: UUID,
        request_id: UUID,
    ) -> R:
        call = RpcCall(subject, request, reply_type, correlation_id, request_id)
        self.calls.append(call)
        queue = self.replies.get(subject)
        if not queue:
            raise AssertionError(f"the fake RPC was given no reply for {subject}")
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        answer = reply(call) if callable(reply) and not isinstance(reply, WireModel) else reply
        if isinstance(answer, RpcCallError):
            raise answer
        assert isinstance(answer, reply_type), f"{subject}: {type(answer)} is not {reply_type}"
        return answer


class FakeReadModel:
    def __init__(self) -> None:
        self.orders: dict[UUID, ReadModelOrder] = {}
        self.headers_in_list: list[ReadModelOrder] = []
        self.list_calls: list[OrderListFilter] = []
        self.list_total: int | None = None
        self.by_reference: dict[str, UUID] = {}
        self.lookups: list[str] = []

    async def find_by_id(self, order_id: UUID) -> ReadModelOrder | None:
        return self.orders.get(order_id)

    async def find_order_id_by_reference(self, order_reference: str) -> UUID | None:
        self.lookups.append(order_reference)
        return self.by_reference.get(order_reference)

    async def list_orders(self, order_filter: OrderListFilter) -> ReadModelPage:
        self.list_calls.append(order_filter)
        items = tuple(o.header for o in self.headers_in_list)
        return ReadModelPage(
            items=items, total=len(items) if self.list_total is None else self.list_total
        )


class Clock:
    """A settable wall clock and a settable monotonic millisecond count."""

    def __init__(self) -> None:
        # PyJWT reads the real clock when it verifies, so the fixture's "now" is the real now
        self.wall = datetime.now(UTC).replace(microsecond=123000)
        self.mono_ms = 1_000_000

    def now(self) -> datetime:
        return self.wall

    def monotonic_ms(self) -> int:
        return self.mono_ms


@dataclass
class Harness:
    app: Any
    client: httpx.AsyncClient
    rpc: FakeRpc
    read_model: FakeReadModel
    clock: Clock
    tokens: JwtTokenService
    window: IssuedOrderWindow
    runtime: GatewayRuntime
    health_probes: dict[str, Callable[[], Awaitable[object]]] = field(default_factory=dict)
    hub: StreamHub | None = None

    def with_stream(
        self, *, ping_interval_seconds: float | None = None, hub: StreamHub | None = None
    ) -> StreamHub:
        """Replace the stream settings the route reads (the runtime is a frozen value)."""
        import dataclasses

        changes: dict[str, Any] = {}
        if ping_interval_seconds is not None:
            changes["stream_ping_interval_seconds"] = ping_interval_seconds
        if hub is not None:
            changes["stream_hub"] = hub
        self.runtime = dataclasses.replace(self.runtime, **changes)
        self.app.state.runtime = self.runtime
        self.hub = self.runtime.stream_hub
        return self.runtime.stream_hub

    def bearer(self, subject: str = OPERATOR_USERNAME) -> dict[str, str]:
        from otc_gateway.application.ports.tokens import TokenClaims

        issued = self.tokens.issue(TokenClaims(subject, ("operator",)))
        return {"Authorization": f"Bearer {issued.access_token}"}

    async def login(
        self, username: str = OPERATOR_USERNAME, password: str = OPERATOR_PASSWORD
    ) -> httpx.Response:
        return await self.client.post(
            "/auth/login", json={"username": username, "password": password}
        )


@pytest.fixture
def clean_gateway_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> pytest.MonkeyPatch:
    """No developer `.env` and no developer shell value can reach a settings class."""
    monkeypatch.chdir(tmp_path)
    for name in (
        "GATEWAY_HOST",
        "GATEWAY_PORT",
        "GATEWAY_RPC_TIMEOUT_MS",
        "GATEWAY_OPERATOR_USERNAME",
        "GATEWAY_OPERATOR_PASSWORD",
        "GATEWAY_OPERATOR_DISPLAY_NAME",
        "GATEWAY_LOGIN_RATE_LIMIT",
        "GATEWAY_LOGIN_RATE_WINDOW_MS",
        "GATEWAY_ISSUED_ORDER_WINDOW_TTL_MS",
        "GATEWAY_ISSUED_ORDER_WINDOW_CAPACITY",
        "GATEWAY_OPENAPI_PATH",
        "GATEWAY_SSE_BUFFER_CAPACITY",
        "GATEWAY_SSE_PING_INTERVAL_MS",
        "GATEWAY_SSE_CLIENT_QUEUE_CAPACITY",
        "JWT_SECRET",
        "JWT_ISSUER",
        "JWT_EXPIRES_IN",
        "NATS_URL",
        "MONGO_URI",
        "MONGO_HOST",
        "MONGO_HOST_PORT",
        "MONGO_INITDB_ROOT_USERNAME",
        "MONGO_INITDB_ROOT_PASSWORD",
        "MONGO_DB_READMODEL",
        "GATEWAY_READ_MODEL_TIMEOUT_MS",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def required_environment(clean_gateway_environment: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """The three values that have no default."""
    clean_gateway_environment.setenv("JWT_SECRET", JWT_SECRET)
    clean_gateway_environment.setenv("GATEWAY_OPERATOR_PASSWORD", OPERATOR_PASSWORD)
    clean_gateway_environment.setenv("MONGO_INITDB_ROOT_PASSWORD", "unit-test-mongo-password")
    return clean_gateway_environment


@pytest_asyncio.fixture
async def harness() -> AsyncIterator[Harness]:
    clock = Clock()
    rpc, read_model = FakeRpc(), FakeReadModel()
    tokens = JwtTokenService(secret=JWT_SECRET, issuer=JWT_ISSUER, expires_in=3600, clock=clock)
    window = IssuedOrderWindow(clock.monotonic_ms, ttl_ms=300_000, capacity=100)
    scope = GatewayScope(
        rpc=rpc,
        read_model=read_model,
        issued_orders=window,
        tokens=tokens,
        operators=ConfiguredOperator(
            username=OPERATOR_USERNAME, password=OPERATOR_PASSWORD, display_name=DISPLAY_NAME
        ),
    )
    probes: dict[str, Callable[[], Awaitable[object]]] = {}

    def probe(name: str) -> Callable[[], Awaitable[object]]:
        async def run() -> object:
            return await probes[name]()

        return run

    async def up() -> object:
        return None

    probes["rpcTransport"] = up
    probes["readModel"] = up
    hub = StreamHub(
        lambda: int(clock.wall.timestamp() * 1000), replay_capacity=500, subscriber_capacity=256
    )
    runtime = GatewayRuntime(
        dispatcher=build_dispatcher(),
        scope=scope,
        tokens=tokens,
        login_throttle=LoginThrottle(clock.monotonic_ms, limit=3, window_ms=60_000),
        clock=clock,
        health_checks=(
            HealthCheck("rpcTransport", probe("rpcTransport"), timeout_seconds=0.2),
            HealthCheck("readModel", probe("readModel"), timeout_seconds=0.2),
        ),
        openapi_document=(REPO_ROOT / "specs/shared/openapi.yaml").read_text(encoding="utf-8"),
        stream_hub=hub,
        stream_ping_interval_seconds=30.0,  # long: a test that wants pings asks for them
        telemetry=build_telemetry("gateway", ""),  # no exporter: nothing leaves the process
    )
    app = create_app()
    app.state.runtime = runtime
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        yield Harness(
            app,
            client,
            rpc,
            read_model,
            clock,
            tokens,
            window,
            runtime,
            health_probes=probes,
            hub=hub,
        )


def new_uuid() -> UUID:
    return uuid4()
