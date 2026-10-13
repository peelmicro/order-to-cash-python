"""Integration fixtures of the projector: a real `mongo:8.3.8` (the root `conftest.py`'s
Docker-held `mongo_server`, never the developer stack), and the writer wired exactly as
`composition.py` wires it.

Loop scopes: every async fixture here is `loop_scope="function"`, written next to it. The
`AsyncMongoClient` is created inside the test's own loop and closed in the same fixture, before the
root conftest's `fresh_mongo_database` drops the database (teardown runs in reverse order of
setup). A test that needs several clients (the concurrency cases) builds and closes its own.
"""

import dataclasses
import itertools
import json
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import pytest
import pytest_asyncio
from pymongo import AsyncMongoClient, monitoring
from pymongo.asynchronous.collection import AsyncCollection

from otc_contracts import FactEvent, format_instant, parse_fact
from otc_projector.application.outcome import ProjectionOutcome
from otc_projector.application.ports.read_model import AppliedDocument
from otc_projector.application.projection import project
from otc_projector.infrastructure.messaging.idempotent_consumer import IdempotentConsumer
from otc_projector.infrastructure.persistence.mongo_read_model_writer import MongoReadModelWriter
from otc_projector.infrastructure.persistence.read_model_document import COLLECTION
from otc_projector.infrastructure.persistence.read_model_indexes import ensure_indexes
from otc_seed.domain.data.sagas import OrderSagaFixture


class FreshDatabase(Protocol):
    """The root conftest's `FreshDatabase`: a database name and the server's URI."""

    @property
    def name(self) -> str: ...
    @property
    def uri(self) -> str: ...


class CommandLog(monitoring.CommandListener):
    """Records the name of every command the driver STARTED, with its first value (the collection
    for `update`, `findAndModify`, `find`, `createIndexes`...). The only way to prove the absence of
    a read is to look at what the driver sent (PR6)."""

    def __init__(self) -> None:
        self.started_commands: list[tuple[str, object]] = []
        self.full_commands: list[tuple[str, dict[str, Any]]] = []

    def started(self, event: monitoring.CommandStartedEvent) -> None:
        self.started_commands.append((event.command_name, next(iter(event.command.values()), None)))
        self.full_commands.append((event.command_name, dict(event.command)))

    def succeeded(self, event: monitoring.CommandSucceededEvent) -> None:
        pass

    def failed(self, event: monitoring.CommandFailedEvent) -> None:
        pass

    def against(self, collection: str) -> list[str]:
        return [name for name, first in self.started_commands if first == collection]

    def clear(self) -> None:
        self.started_commands.clear()
        self.full_commands.clear()


@dataclass
class Applied:
    outcome: ProjectionOutcome
    documents: list[AppliedDocument] = field(default_factory=list)


@dataclass
class ReadModel:
    client: AsyncMongoClient[dict[str, Any]]
    collection: AsyncCollection[dict[str, Any]]
    writer: MongoReadModelWriter
    log: CommandLog
    database: str
    uri: str

    async def apply(self, event: FactEvent) -> Applied:
        applied = Applied(ProjectionOutcome.DUPLICATE)

        async def collect(document: AppliedDocument) -> None:
            applied.documents.append(document)

        applied.outcome = await self.writer.apply(project(event), after_applied=collect)
        return applied

    async def document(self, order_id: object) -> dict[str, Any]:
        found = await self.collection.find_one({"_id": str(order_id)})
        assert found is not None, f"no document for {order_id}"
        return found

    async def raw(self, order_id: object) -> bytes:
        """The document's stored BSON bytes (element order and types included)."""
        from bson.raw_bson import RawBSONDocument

        raw_collection = self.client.get_database(self.database).get_collection(
            COLLECTION, codec_options=_raw_options()
        )
        found = await raw_collection.find_one({"_id": str(order_id)})
        assert isinstance(found, RawBSONDocument), f"no document for {order_id}"
        return bytes(found.raw)


def _raw_options() -> Any:
    from bson.codec_options import CodecOptions
    from bson.raw_bson import RawBSONDocument

    return CodecOptions(document_class=RawBSONDocument)


def new_read_model(uri: str, database: str, *, listener: bool = True) -> ReadModel:
    log = CommandLog()
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
        uri, event_listeners=[log] if listener else []
    )
    collection = client.get_database(database).get_collection(COLLECTION)
    writer = MongoReadModelWriter(collection, IdempotentConsumer(collection))
    return ReadModel(client, collection, writer, log, database, uri)


@pytest_asyncio.fixture(loop_scope="function")
async def read_model(fresh_mongo_database: FreshDatabase) -> AsyncIterator[ReadModel]:
    """A read model with both indexes created, on a database nobody else has used."""
    model = new_read_model(fresh_mongo_database.uri, fresh_mongo_database.name)
    await ensure_indexes(model.collection)
    model.log.clear()
    try:
        yield model
    finally:
        await model.client.close()


def facts_of(saga: OrderSagaFixture) -> list[FactEvent]:
    """The facts a saga's own outbox fixtures describe, as the producers publish them."""
    facts: list[FactEvent] = []
    for row in (*saga.orders_outbox, *saga.fulfillment_outbox, *saga.billing_outbox):
        document = {
            "eventId": row.event_id,
            "eventType": row.event_type,
            "aggregateId": row.aggregate_id,
            "correlationId": row.correlation_id,
            "causationId": row.causation_id,
            "occurredAt": format_instant(row.occurred_at),
            "payload": dict(row.payload),
        }
        facts.append(parse_fact(json.dumps(document)))
    return facts


@pytest.fixture
def new_model_factory(fresh_mongo_database: FreshDatabase) -> Callable[[], ReadModel]:
    """A factory for additional, separate clients on the same database (the concurrency cases)."""

    def make() -> ReadModel:
        return new_read_model(fresh_mongo_database.uri, fresh_mongo_database.name)

    return make


@pytest.fixture
def saga_facts() -> Callable[[OrderSagaFixture], list[FactEvent]]:
    """`facts_of` as a fixture: test modules cannot import this conftest (importlib mode)."""
    return facts_of


# ------------------------------------------------------------------------------------------- NATS


@pytest_asyncio.fixture(loop_scope="function")
async def nats_connection(nats_server: Any) -> AsyncIterator[Any]:
    """A core NATS client on the root conftest's Docker-held server, created and closed in the
    test's own (function) loop. Never the developer stack's NATS."""
    import nats

    connection = await nats.connect(nats_server.url)
    try:
        yield connection
    finally:
        await connection.close()


BARRIER = b"__barrier__"


class Frames:
    """A subscription that records what it receives, with a BARRIER for 'nothing more is coming'.

    Subscribing happens FIRST (a core subscription sees nothing published before it exists). To
    prove the absence of a frame, a barrier is published on the same subjects after the action
    under test: a subscription delivers in publish order, so once its barrier has arrived,
    everything published before it has been delivered, and a count is exact (never a sleep).
    """

    def __init__(self, connection: Any, subject: str) -> None:
        self.connection = connection
        self.subject = subject
        self.received: list[bytes] = []
        self.barriers = 0
        self._subscription: Any = None

    async def start(self) -> Frames:
        async def collect(message: Any) -> None:
            if message.data == BARRIER:
                self.barriers += 1
            else:
                self.received.append(message.subject.encode() + b"\n" + message.data)

        self._subscription = await self.connection.subscribe(self.subject, cb=collect)
        await self.connection.flush()  # the server has the subscription before anything publishes
        return self

    def frames(self) -> list[tuple[str, dict[str, Any]]]:
        out = []
        for raw in self.received:
            subject, _, body = raw.partition(b"\n")
            out.append((subject.decode(), json.loads(body)))
        return out


@pytest.fixture
def trace_support() -> Any:
    """`tests/observability/trace_support.py` (typed span readers), loaded by path."""
    import importlib.util
    import sys
    from pathlib import Path

    name = "trace_support"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parents[4] / "tests/observability/trace_support.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def dl_support() -> Any:
    """`tests/observability/dead_letter_support.py` (broker readers, a producer), loaded by path."""
    import importlib.util
    import sys
    from pathlib import Path

    name = "dead_letter_support"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parents[4] / "tests/observability/dead_letter_support.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def frames_factory(nats_connection: Any) -> Callable[[str], Any]:
    async def make(subject: str) -> Frames:
        return await Frames(nats_connection, subject).start()

    return make


# ------------------------------------------------------------------------- the real runtime


@dataclass(frozen=True)
class Topics:
    """THREE PRIVATE TOPICS per test, one per producing service, in place of the three real ones.

    The root conftest's Kafka is ONE broker for the whole pytest session and every service's tests
    publish to the real fact topics (Orders' saga and relay tests, Billing's, Fulfillment's...).
    The projector's groups start at `earliest`, so a runtime pointed at the real topics replays
    whatever ANY earlier test of ANY service produced into this test's database: two
    `order.placed.v1` with one `orderReference` collide on `uq_order_reference` (the poison record
    feature 27 owns) and the test fails for another test's fact (measured: the first full
    `./quality.sh` failed three cases this way). Isolation, not luck: the runtime is pointed at
    private topics through the `Externals` subscriber factory; the real topic names are asserted by
    `unit/test_fact_topics.py`, by `unit/test_kafka_fact_subscriber_options.py` and by the live
    walkthrough.
    """

    orders: str
    fulfillment: str
    billing: str

    @property
    def all(self) -> tuple[str, str, str]:
        return (self.orders, self.fulfillment, self.billing)

    @property
    def dead_letters(self) -> tuple[str, str, str]:
        """The private `<topic>.dlq` companions (feature 27, item 10): the dead-letter publisher
        derives the name from the record's own topic, so a poison fact on a private topic is
        dead-lettered to a private companion, never to a real one."""
        return (f"{self.orders}.dlq", f"{self.fulfillment}.dlq", f"{self.billing}.dlq")

    def dead_letter_of(self, topic: str) -> str:
        assert topic in self.all, f"{topic} is not one of this test's private topics"
        return f"{topic}.dlq"

    def for_event(self, event_type: str) -> str:
        """The topic a fact is published on: one per producing service (`asyncapi.yaml`)."""
        if event_type.startswith("stock."):
            return self.fulfillment
        if event_type.startswith(("credit.", "invoice.", "payment.")):
            return self.billing
        return self.orders


async def wait_until(claim: str, condition: Callable[[], Any], seconds: float = 60.0) -> None:
    """Poll monotonic evidence under a bound; the failure names the claim (no timeout plugin)."""
    import asyncio

    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while True:
        result = condition()
        if hasattr(result, "__await__"):
            result = await result
        if result:
            return
        if loop.time() > deadline:
            pytest.fail(f"{claim}: not observed within {seconds} s")
        await asyncio.sleep(0.05)


@dataclass
class RuntimeEnv:
    """Where the real runtime connects: the root conftest's Docker-held servers."""

    mongo_uri: str
    database: str
    kafka: str
    nats: str
    topics: Topics
    started: list[Any] = field(default_factory=list)

    def settings(self, group: str, *, nats: str | None = None, backoff_ms: int = 10) -> Any:
        from otc_projector.composition import ProjectorSettings
        from otc_projector.infrastructure.settings import (
            FactRetrySettings,
            KafkaSettings,
            MongoSettings,
            NatsSettings,
            TelemetrySettings,
        )

        return ProjectorSettings(
            mongo=MongoSettings.model_validate(
                {"MONGO_URI": self.mongo_uri, "MONGO_DB_READMODEL": self.database}
            ),
            kafka=KafkaSettings.model_validate(
                {
                    "KAFKA_BROKERS": self.kafka,
                    "PROJECTOR_KAFKA_CLIENT_ID": f"otc-projector-test-{group}",
                    "PROJECTOR_CONSUMER_GROUP": group,
                }
            ),
            nats=NatsSettings.model_validate({"NATS_URL": nats or self.nats}),
            telemetry=TelemetrySettings(),
            # a short back-off keeps a poison fact's three attempts inside a test's budget
            fact_retry=FactRetrySettings.model_validate({"FACT_RETRY_BACKOFF_MS": backoff_ms}),
        )

    def read_model(self) -> ReadModel:
        """A second, independent view of the runtime's database (own client, own loop)."""
        return new_read_model(self.mongo_uri, self.database)

    def externals(self, base: Any = None) -> Any:
        """`base` (or the real collaborators) with the subscriber pointed at THIS test's topics."""
        from otc_projector.composition import Externals
        from otc_projector.infrastructure.messaging.kafka_fact_subscriber import KafkaFactSubscriber

        topics = self.topics.all

        def subscriber(settings: Any, tracer: Any) -> Any:
            return KafkaFactSubscriber(settings, topics=topics, tracer=tracer)

        return dataclasses.replace(base if base is not None else Externals(), subscriber=subscriber)

    async def start(
        self, group: str, *, externals: Any = None, backoff_ms: int = 10, **kwargs: Any
    ) -> Any:
        from otc_projector.composition import start_runtime

        runtime = await start_runtime(
            self.settings(group, backoff_ms=backoff_ms),
            externals=self.externals(externals),
            **kwargs,
        )
        self.started.append(runtime)
        return runtime

    async def start_with(self, group: str, *, nats: str, **kwargs: Any) -> Any:
        """Like `start`, against a NATS URL of the caller's choosing."""
        from otc_projector.composition import start_runtime

        runtime = await start_runtime(
            self.settings(group, nats=nats), externals=self.externals(), **kwargs
        )
        self.started.append(runtime)
        return runtime


@pytest.fixture
def endpoints(mongo_server: Any, kafka_server: Any, nats_server: Any) -> Iterator[RuntimeEnv]:
    """Sync (no loop): descriptions of the three Docker-held servers and a database nobody else
    has used. A test that starts runtimes in loops of its own (`asyncio.run`) uses this directly."""
    import asyncio
    import uuid

    from aiokafka.admin import AIOKafkaAdminClient, NewTopic

    suffix = uuid.uuid4().hex[:10]
    topics = Topics(
        orders=f"otc-test-{suffix}-orders-facts",
        fulfillment=f"otc-test-{suffix}-fulfillment-facts",
        billing=f"otc-test-{suffix}-billing-facts",
    )

    async def create_topics() -> None:
        admin = AIOKafkaAdminClient(bootstrap_servers=kafka_server.bootstrap_servers)
        await admin.start()
        try:
            await admin.create_topics(
                [
                    NewTopic(name=n, num_partitions=3, replication_factor=1)
                    for n in (*topics.all, *topics.dead_letters)
                ]
            )
        finally:
            await admin.close()

    asyncio.run(create_topics())
    database = f"otc_test_{uuid.uuid4().hex}"
    env = RuntimeEnv(
        mongo_uri=mongo_server.uri(),
        database=database,
        kafka=kafka_server.bootstrap_servers,
        nats=nats_server.url,
        topics=topics,
    )
    yield env

    async def drop() -> None:
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(env.mongo_uri)
        try:
            await client.drop_database(database)
        finally:
            await client.close()

    asyncio.run(drop())


@pytest_asyncio.fixture(loop_scope="function")
async def runtime_env(endpoints: RuntimeEnv) -> AsyncIterator[RuntimeEnv]:
    """`endpoints` for an async test: every runtime it starts through `endpoints.start` is stopped
    at teardown, in this same (function) loop, if the test did not stop it."""
    try:
        yield endpoints
    finally:
        for runtime in endpoints.started:
            if not runtime._stopping:
                await runtime.stop()


@pytest_asyncio.fixture(loop_scope="function")
async def produce(endpoints: RuntimeEnv) -> AsyncIterator[Callable[..., Any]]:
    """`await produce(events_or_bytes)`: publish facts to THIS test's private topics, keyed by
    correlationId."""
    from aiokafka import AIOKafkaProducer

    producer = AIOKafkaProducer(bootstrap_servers=endpoints.kafka)
    await producer.start()

    async def send(events: list[Any]) -> None:
        for event in events:
            if isinstance(event, bytes):
                await producer.send_and_wait(endpoints.topics.orders, event)
                continue
            value = to_wire_bytes(event)
            key = str(event.correlation_id).encode()
            await producer.send_and_wait(
                endpoints.topics.for_event(event.event_type), value, key=key
            )

    try:
        yield send
    finally:
        await producer.stop()


def to_wire_bytes(event: Any) -> bytes:
    from otc_contracts import to_wire_json

    return to_wire_json(event).encode("utf-8")


_REFERENCES = itertools.count(800001)


@pytest.fixture
def new_reference() -> Callable[[], str]:
    """A process-unique `ORD-######` for a test that produces an `order.placed.v1` to Kafka.

    Belt and braces: each such test now has PRIVATE topics (`Topics`), which is what isolates it
    from other tests' facts; a unique reference additionally keeps two orders of ONE test apart."""

    def make() -> str:
        return f"ORD-{next(_REFERENCES):06d}"

    return make
