"""Feature 26 against real infrastructure (R55, the subscriber leg): the Gateway's lifespan
subscribes to the real NATS, the frames reach a real TCP client, and (the end-to-end case) a Kafka
fact travels through the REAL Projector to an SSE frame.

What is real: NATS, MongoDB and Kafka (the root conftest's Docker-held servers, never the developer
stack), the Gateway host (`otc_gateway.main.create_app()` under a real uvicorn socket), and the
Projector's runtime (`otc_projector.composition.start_runtime`: the body of its lifespan, with its
real Kafka consumer, MongoDB writer and NATS publisher). The only thing pointed elsewhere is the
Projector's three fact topics (private, so no other test's facts are consumed).

Loop scope: every async fixture and test runs in the function loop; the Gateway's lifespan, the
uvicorn server, the Projector runtime and every client are created and closed in it, in reverse
order. Every wait is bounded and its failure names the claim.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import nats
import pytest
import pytest_asyncio
from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from opentelemetry.trace import Tracer

from otc_contracts import FactEvent, format_instant, parse_fact, to_wire_json
from otc_contracts.generated import openapi
from otc_seed.domain.data.sagas import SAGAS

pytestmark = pytest.mark.integration

OPERATOR_PASSWORD = "sse-operator-password"
JWT_SECRET = "sse-jwt-secret-0123456789abcdef-0123456789"
PING_MS = 200
ORDER = "0a0b0c0d-5555-4000-8000-0000000000e5"
BOUND_SECONDS = 90.0


@dataclass
class LiveGateway:
    host: str
    port: int
    app: Any
    token: str
    server: Any

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    @property
    def hub(self) -> Any:
        return self.app.state.runtime.stream_hub


@pytest_asyncio.fixture(loop_scope="function")
async def live_gateway(
    fresh_mongo_database: Any,
    nats_server: Any,
    serve: Callable[..., Awaitable[Any]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[LiveGateway]:
    from otc_gateway.main import create_app as create_gateway

    monkeypatch.chdir(tmp_path)  # no developer `.env`
    for name, value in {
        "NATS_URL": nats_server.url,
        "MONGO_URI": fresh_mongo_database.uri,
        "MONGO_DB_READMODEL": fresh_mongo_database.name,
        "JWT_SECRET": JWT_SECRET,
        "GATEWAY_OPERATOR_PASSWORD": OPERATOR_PASSWORD,
        "GATEWAY_SSE_PING_INTERVAL_MS": str(PING_MS),
    }.items():
        monkeypatch.setenv(name, value)
    app = create_gateway()
    async with app.router.lifespan_context(app):
        server = await serve(app)
        async with httpx.AsyncClient(base_url=f"http://{server.host}:{server.port}") as client:
            login = await client.post(
                "/auth/login", json={"username": "operator", "password": OPERATOR_PASSWORD}
            )
        assert login.status_code == 200, login.text
        yield LiveGateway(server.host, server.port, app, login.json()["accessToken"], server)


async def open_stream(
    gateway: LiveGateway, raw_sse: Any, path: str = "/orders/stream", **headers: str
) -> Any:
    return await raw_sse(gateway.host, gateway.port, path, {**gateway.auth, **headers})


async def frames_until_closed(client: Any) -> None:
    """Read (buffered pings first) until the server's close surfaces as a failure."""
    for _ in range(100):
        await client.next_frame(2, "a frame after the server stopped")


def update_wire(order: str, status: str, n: int) -> bytes:
    model = openapi.OrderStreamUpdate.model_validate_json(
        json.dumps(
            {
                "eventId": str(uuid.UUID(int=n)),
                "orderId": order,
                "status": status,
                "occurredAt": "2026-08-18T10:15:02.100Z",
            }
        )
    )
    return to_wire_json(model).encode("utf-8")


# ----------------------------------------------------------------- the subscriber on a real NATS


async def test_r55_a_signal_published_on_nats_reaches_a_connected_client_as_an_sse_frame(
    live_gateway: LiveGateway, nats_server: Any, raw_sse: Any
) -> None:
    other = str(uuid.UUID(int=0xB0B))
    client = await open_stream(live_gateway, raw_sse, f"/orders/stream?orderId={ORDER}")
    ready = await client.next_frame(10, "stream.ready")
    assert ready.json()["orderId"] == ORDER
    publisher = await nats.connect(nats_server.url)
    try:
        # a barrier-like noise first: not JSON, then another order's signal, then ours
        await publisher.publish(f"readmodel.order.updated.{ORDER}", b"__barrier__")
        await publisher.publish(
            f"readmodel.order.updated.{other}", update_wire(other, "confirmed", 1)
        )
        wanted = update_wire(ORDER, "stock_reserved", 2)
        await publisher.publish(f"readmodel.order.updated.{ORDER}", wanted)
        await publisher.flush()

        frame = await client.next_frame(10, "the order's own signal")
    finally:
        await publisher.close()

    assert frame.event == "order.updated"
    assert frame.id is not None
    assert frame.data.encode("utf-8") == wanted, "the data line is not the Projector's exact bytes"
    assert openapi.OrderStreamUpdate.model_validate_json(frame.data).order_id == uuid.UUID(ORDER)


async def test_r55_the_two_subjects_feed_their_own_event_types(
    live_gateway: LiveGateway, nats_server: Any, raw_sse: Any
) -> None:
    client = await open_stream(live_gateway, raw_sse)
    await client.next_frame(10, "stream.ready")
    entry = openapi.TimelineStreamEntry.model_validate_json(
        json.dumps(
            {
                "eventId": str(uuid.UUID(int=77)),
                "orderId": ORDER,
                "eventType": "credit.rejected.v1",
                "occurredAt": "2026-08-18T10:15:04.120Z",
                "summary": "Credit rejected",
            }
        )
    )
    publisher = await nats.connect(nats_server.url)
    try:
        await publisher.publish(
            f"readmodel.timeline.appended.{ORDER}", to_wire_json(entry).encode("utf-8")
        )
        await publisher.flush()
        frame = await client.next_frame(10, "the timeline signal")
    finally:
        await publisher.close()

    assert frame.event == "timeline.appended"
    assert openapi.TimelineStreamEntry.model_validate_json(frame.data).event_id == uuid.UUID(int=77)


async def test_r55_a_dead_subscriber_task_takes_readiness_down(live_gateway: LiveGateway) -> None:
    async with httpx.AsyncClient(
        base_url=f"http://{live_gateway.host}:{live_gateway.port}"
    ) as http:
        before = await http.get("/health/ready")
        assert before.status_code == 200, before.text
        assert before.json()["checks"]["streamSignals"] == {"status": "up"}

        (task,) = [t for t in asyncio.all_tasks() if t.get_name() == "gateway-stream-signal"]
        task.cancel()
        await asyncio.wait({task})
        after = await http.get("/health/ready")

    assert after.status_code == 503
    assert after.json()["checks"]["streamSignals"]["status"] == "down"
    assert after.json()["checks"]["rpcTransport"] == {"status": "up"}


async def test_r55_stopping_the_server_with_streams_open_ends_them_and_releases_every_subscription(
    live_gateway: LiveGateway, raw_sse: Any
) -> None:
    """uvicorn waits for open responses before it stops; a stream never ends by itself, so the bound
    (`timeout_graceful_shutdown`, the helper's 2 s as `__main__`'s 5 s) must end them, and each
    one's subscription must be released by that cancellation, not left on the hub."""
    hub = live_gateway.hub
    clients = [await open_stream(live_gateway, raw_sse) for _ in range(3)]
    for client in clients:
        await client.next_frame(10, "stream.ready")
    assert hub.subscriber_count == 3

    loop = asyncio.get_running_loop()
    began = loop.time()
    await live_gateway.server.stop()  # bounded by the helper (10 s); the graceful bound is 2 s

    assert loop.time() - began < 8, "the server took longer than its graceful bound to stop"
    deadline = loop.time() + 2  # the cancelled responses finish their `finally` on the next turns
    while hub.subscriber_count != 0:
        assert loop.time() < deadline, "a stream's subscription survived the server's stop"
        await asyncio.sleep(0.01)
    for client in clients:
        with pytest.raises(
            pytest.fail.Exception, match=r"closed the connection|ended the response"
        ):
            await frames_until_closed(client)


# ------------------------------------------------------------ through the REAL Projector (R55)


def saga_facts(saga: Any) -> list[FactEvent]:
    facts = []
    for row in (*saga.orders_outbox, *saga.fulfillment_outbox, *saga.billing_outbox):
        facts.append(
            parse_fact(
                json.dumps(
                    {
                        "eventId": row.event_id,
                        "eventType": row.event_type,
                        "aggregateId": row.aggregate_id,
                        "correlationId": row.correlation_id,
                        "causationId": row.causation_id,
                        "occurredAt": format_instant(row.occurred_at),
                        "payload": dict(row.payload),
                    }
                )
            )
        )
    return facts


def topic_for(event_type: str, topics: tuple[str, str, str]) -> str:
    orders, fulfillment, billing = topics
    if event_type.startswith("stock."):
        return fulfillment
    if event_type.startswith(("credit.", "invoice.", "payment.")):
        return billing
    return orders


async def create_topics(bootstrap: str, names: tuple[str, ...]) -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        await admin.create_topics(
            [NewTopic(name=n, num_partitions=3, replication_factor=1) for n in names]
        )
    finally:
        await admin.close()


async def test_r55_a_projected_fact_reaches_an_sse_client_as_frames_through_the_real_projector(
    live_gateway: LiveGateway,
    kafka_server: Any,
    nats_server: Any,
    fresh_mongo_database: Any,
    raw_sse: Any,
) -> None:
    """The subscriber leg of R55, end to end: facts produced to Kafka -> the real Projector (its
    consumer, MongoDB writer and NATS publisher) -> NATS -> the real Gateway -> a TCP client reading
    SSE. For the completed seeded saga: one `timeline.appended` and one `order.updated` per fact,
    each carrying the fact's own `eventId`, the cursors increasing, the last status `completed`,
    and a reconnect from the middle replaying exactly the frames after it."""
    from otc_projector.composition import Externals, ProjectorSettings, start_runtime
    from otc_projector.infrastructure.messaging.kafka_fact_subscriber import KafkaFactSubscriber
    from otc_projector.infrastructure.settings import (
        FactRetrySettings,
        KafkaSettings,
        MongoSettings,
        NatsSettings,
        TelemetrySettings,
    )

    saga = next(s for s in SAGAS if s.status == "completed")
    facts = saga_facts(saga)
    order_id = saga.order_id
    suffix = uuid.uuid4().hex[:10]
    topics = (
        f"otc-sse-{suffix}-orders",
        f"otc-sse-{suffix}-fulfillment",
        f"otc-sse-{suffix}-billing",
    )
    await create_topics(kafka_server.bootstrap_servers, topics)
    settings = ProjectorSettings(
        mongo=MongoSettings.model_validate(
            {"MONGO_URI": fresh_mongo_database.uri, "MONGO_DB_READMODEL": fresh_mongo_database.name}
        ),
        kafka=KafkaSettings.model_validate(
            {
                "KAFKA_BROKERS": kafka_server.bootstrap_servers,
                "PROJECTOR_KAFKA_CLIENT_ID": f"otc-projector-sse-{suffix}",
                "PROJECTOR_CONSUMER_GROUP": f"projector-sse-{suffix}",
            }
        ),
        nats=NatsSettings.model_validate({"NATS_URL": nats_server.url}),
        telemetry=TelemetrySettings(),
        fact_retry=FactRetrySettings(),
    )

    def subscriber(kafka: KafkaSettings, tracer: Tracer) -> KafkaFactSubscriber:
        return KafkaFactSubscriber(kafka, topics=topics, tracer=tracer)

    client = await open_stream(live_gateway, raw_sse, f"/orders/stream?orderId={order_id}")
    await client.next_frame(10, "stream.ready")
    # a second, independent NATS subscriber: the bytes the Projector really published (N2)
    published: list[tuple[str, bytes]] = []

    async def record(message: Any) -> None:
        published.append((message.subject, bytes(message.data)))

    spy = await nats.connect(nats_server.url)
    await spy.subscribe("readmodel.>", cb=record)
    await spy.flush()
    producer = AIOKafkaProducer(bootstrap_servers=kafka_server.bootstrap_servers)
    await producer.start()
    projector = await start_runtime(settings, externals=Externals(subscriber=subscriber))
    try:
        for fact in facts:
            await producer.send_and_wait(
                topic_for(fact.event_type, topics),
                to_wire_json(fact).encode("utf-8"),
                key=str(fact.correlation_id).encode(),
            )
        frames: list[Any] = []
        try:
            async with asyncio.timeout(BOUND_SECONDS):
                while sum(f.event == "timeline.appended" for f in frames) < len(facts) or sum(
                    f.event == "order.updated" for f in frames
                ) < len(facts):
                    frame = await client.next_frame(BOUND_SECONDS, "the next frame of the saga")
                    if frame.event != "ping":
                        frames.append(frame)
        except TimeoutError:
            pytest.fail(
                f"R55: {len(frames)} frames within {BOUND_SECONDS} s for {len(facts)} facts "
                f"({[f.event for f in frames]})"
            )
    finally:
        await producer.stop()
        await projector.stop()
        await spy.drain()

    fact_ids = {str(f.event_id) for f in facts}
    timeline = [f for f in frames if f.event == "timeline.appended"]
    updates = [f for f in frames if f.event == "order.updated"]
    assert {f.json()["eventId"] for f in timeline} == fact_ids, "timeline frames != the facts"
    assert {f.json()["eventId"] for f in updates} == fact_ids, "order.updated frames != the facts"
    assert len(timeline) == len(updates) == len(facts)
    # N2: each frame's `data` is, byte for byte, a message the Projector published on its subject
    for event, subject_prefix, got in (
        ("order.updated", "readmodel.order.updated.", updates),
        ("timeline.appended", "readmodel.timeline.appended.", timeline),
    ):
        projected = sorted(
            data for subject, data in published if subject.startswith(subject_prefix)
        )
        assert len(projected) == len(facts), f"the Projector published {len(projected)} {event}"
        assert sorted(f.data.encode("utf-8") for f in got) == projected, (
            f"{event}: the frames' data lines are not the Projector's published bytes"
        )
    assert all(f.json()["orderId"] == order_id for f in frames)
    for frame in timeline:
        openapi.TimelineStreamEntry.model_validate_json(frame.data)
    for frame in updates:
        openapi.OrderStreamUpdate.model_validate_json(frame.data)
    sequences = [int((f.id or "").rsplit("-", 1)[1]) for f in frames]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    assert updates[-1].json()["status"] == "completed", "the last signal is the final document"

    middle = frames[len(frames) // 2]
    again = await open_stream(
        live_gateway,
        raw_sse,
        f"/orders/stream?orderId={order_id}",
        **{"Last-Event-ID": middle.id or ""},
    )
    ready = await again.next_frame(10, "stream.ready of the reconnect")
    after = frames[len(frames) // 2 + 1 :]
    replayed = [await again.next_frame(10, "a replayed frame") for _ in after]
    assert ready.json()["resumed"] is True
    assert [(f.id, f.event, f.data) for f in replayed] == [(f.id, f.event, f.data) for f in after]
