"""H3, H4, H5 (PR27, PR43, PR45 and the wiring of every setting): the composition root, driven with
RECORDING FAKES for the five externals (the Mongo client, the index ensure/verify, the migration,
the NATS connection and the subscriber), so the ORDER of the boot and the destination of every
setting are asserted on calls that happened, not on the source text.

Loop scope: the function loop; every fake is created in the test and the runtime is stopped in it.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest

import otc_projector.composition as composition
from otc_cqrs import DispatcherValidationError, HandlerRegistry
from otc_projector.composition import Externals, ProjectorSettings, start_runtime
from otc_projector.infrastructure.messaging.kafka_fact_subscriber import KafkaFactSubscriber
from otc_projector.infrastructure.settings import KafkaSettings, MongoSettings, NatsSettings

EXPECTED_ORDER = [
    "dispatcher",
    "mongo.ping",
    "indexes.ensure",
    "indexes.verify",
    "migration",
    "nats.connect",
    "consumer.start",
]


class World:
    """The five recording fakes, sharing one call log."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.mongo_uri: str | None = None
        self.database_name: str | None = None
        self.collection_name: str | None = None
        self.nats_url: str | None = None
        self.kafka_settings: KafkaSettings | None = None
        self.consumer_kwargs: dict[str, Any] = {}
        self.fail_at: str | None = None
        self.subscriber_error: Exception | None = None

    def hit(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError(f"{name} failed")

    # -- Mongo
    def mongo_client(self, uri: str) -> Any:
        self.mongo_uri = uri
        world = self

        class Collection:
            pass

        class Database:
            async def command(self, command: str) -> None:
                assert command == "ping"
                world.hit("mongo.ping")

            def get_collection(self, name: str) -> Any:
                world.collection_name = name
                return Collection()

        class Client:
            def get_database(self, name: str) -> Any:
                world.database_name = name
                return Database()

            async def close(self) -> None:
                world.calls.append("mongo.close")

        return Client()

    async def ensure(self, collection: Any) -> None:
        self.hit("indexes.ensure")

    async def verify(self, collection: Any) -> None:
        self.hit("indexes.verify")

    async def migrate(self, collection: Any) -> object:
        self.hit("migration")
        return None

    # -- NATS
    async def nats_connect(self, url: str) -> Any:
        self.nats_url = url
        self.hit("nats.connect")
        world = self

        class Connection:
            is_closed = False
            is_reconnecting = False

            async def publish(self, *args: Any, **kwargs: Any) -> None:
                return None

            async def drain(self) -> None:
                world.calls.append("nats.drain")

        return Connection()

    # -- Kafka
    def subscriber(self, settings: KafkaSettings) -> Any:
        self.kafka_settings = settings
        world = self

        class Consumer:
            def __init__(self, *topics: str, **kwargs: Any) -> None:
                world.consumer_kwargs = {"topics": topics, **kwargs}

            async def start(self) -> None:
                world.hit("consumer.start")
                if world.subscriber_error is not None:
                    raise world.subscriber_error

            async def stop(self) -> None:
                world.calls.append("consumer.stop")

            def assignment(self) -> list[tuple[str, int]]:
                return []

            async def position(self, partition: tuple[str, int]) -> int:
                return 0

            async def getmany(self, *, timeout_ms: int, max_records: int) -> dict[Any, Any]:
                await asyncio.sleep(0.001)
                return {}

            def seek(self, partition: tuple[str, int], offset: int) -> None:
                return None

            async def commit(self, offsets: dict[Any, int]) -> None:
                return None

        return KafkaFactSubscriber(
            settings, consumer_factory=cast("Callable[..., Any]", Consumer), poll_ms=1
        )

    def externals(self) -> Externals:
        def wire() -> composition.Wiring:
            self.calls.append("dispatcher")
            return composition._wire()

        return Externals(
            wire=wire,
            mongo_client=self.mongo_client,
            ensure_indexes=cast("Callable[[Any], Awaitable[None]]", self.ensure),
            verify_indexes=cast("Callable[[Any], Awaitable[None]]", self.verify),
            migrate=cast("Callable[[Any], Awaitable[object]]", self.migrate),
            nats_connect=cast("Callable[[str], Awaitable[Any]]", self.nats_connect),
            subscriber=self.subscriber,
        )


def settings_from(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, **env: str) -> ProjectorSettings:
    monkeypatch.chdir(tmp_path)  # no developer `.env`
    for name in (
        "MONGO_URI",
        "MONGO_INITDB_ROOT_PASSWORD",
        "MONGO_DB_READMODEL",
        "KAFKA_BROKERS",
        "PROJECTOR_KAFKA_CLIENT_ID",
        "PROJECTOR_CONSUMER_GROUP",
        "NATS_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return composition.load_settings()


def default_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> ProjectorSettings:
    return settings_from(monkeypatch, tmp_path, MONGO_INITDB_ROOT_PASSWORD="pw")


def leftover_tasks() -> set[asyncio.Task[Any]]:
    return {t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()}


async def test_each_setting_reaches_the_adapter_it_configures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    settings = settings_from(
        monkeypatch,
        tmp_path,
        MONGO_URI="mongodb://sentinel-user:sentinel-pw@mongo.sentinel:27999/?authSource=sentinel",
        MONGO_DB_READMODEL="readmodel_sentinel",
        KAFKA_BROKERS="kafka.sentinel:19092",
        PROJECTOR_KAFKA_CLIENT_ID="client-sentinel",
        PROJECTOR_CONSUMER_GROUP="group-sentinel",
        NATS_URL="nats://nats.sentinel:4333",
    )
    world = World()
    runtime = await start_runtime(settings, externals=world.externals())
    try:
        assert world.mongo_uri == (
            "mongodb://sentinel-user:sentinel-pw@mongo.sentinel:27999/?authSource=sentinel"
        )
        assert world.database_name == "readmodel_sentinel"
        assert world.collection_name == "order_timeline"
        assert world.nats_url == "nats://nats.sentinel:4333"
        assert world.consumer_kwargs["bootstrap_servers"] == "kafka.sentinel:19092"
        assert world.consumer_kwargs["client_id"] == "client-sentinel"
        assert world.consumer_kwargs["group_id"] == "group-sentinel"
    finally:
        await runtime.stop()


async def test_pr43_start_runtime_runs_its_steps_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    world = World()
    runtime = await start_runtime(
        default_settings(monkeypatch, tmp_path), externals=world.externals()
    )
    try:
        assert world.calls == EXPECTED_ORDER, f"the boot ran {world.calls}"
        assert runtime.unready_reasons() == []
    finally:
        await runtime.stop()
    # closed in reverse order of opening: the consumer first, then NATS, then MongoDB
    assert world.calls[len(EXPECTED_ORDER) :] == ["consumer.stop", "nats.drain", "mongo.close"]


@pytest.mark.parametrize(
    "failing", ["indexes.ensure", "indexes.verify", "migration", "nats.connect"]
)
async def test_pr43_a_raising_step_leaves_no_task_and_closes_what_was_opened_in_reverse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, failing: str
) -> None:
    world = World()
    world.fail_at = failing
    before = leftover_tasks()
    with pytest.raises(RuntimeError, match=f"{failing} failed"):
        await start_runtime(default_settings(monkeypatch, tmp_path), externals=world.externals())
    assert leftover_tasks() == before, "a task was left running by a failed boot"
    steps = EXPECTED_ORDER[: EXPECTED_ORDER.index(failing) + 1]
    assert world.calls[: len(steps)] == steps
    closes = [c for c in world.calls if c in ("mongo.close", "nats.drain")]
    assert closes == ["mongo.close"], f"closed {closes}, expected only what was opened"
    assert "consumer.start" not in world.calls, "the consumer started after a failed step"


async def test_pr43_a_consumer_that_cannot_start_closes_everything_in_reverse_and_leaves_no_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    world = World()
    world.subscriber_error = RuntimeError("broker down")
    before = leftover_tasks()
    with pytest.raises(RuntimeError, match="broker down"):
        await start_runtime(default_settings(monkeypatch, tmp_path), externals=world.externals())
    assert leftover_tasks() == before
    closes = [c for c in world.calls if c in ("mongo.close", "nats.drain")]
    assert closes == ["nats.drain", "mongo.close"], f"closed {closes}"


async def test_pr45_a_nats_connection_that_never_answers_fails_the_boot_naming_nats_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    world = World()
    externals = world.externals()

    async def never(url: str) -> Any:
        world.calls.append("nats.connect")
        await asyncio.Event().wait()

    stuck = Externals(
        wire=externals.wire,
        mongo_client=externals.mongo_client,
        ensure_indexes=externals.ensure_indexes,
        verify_indexes=externals.verify_indexes,
        migrate=externals.migrate,
        nats_connect=never,
        subscriber=externals.subscriber,
    )
    before = leftover_tasks()
    with pytest.raises(RuntimeError, match="NATS_URL nats://localhost:4222"):
        await start_runtime(
            default_settings(monkeypatch, tmp_path), externals=stuck, nats_connect_seconds=0.05
        )
    assert leftover_tasks() == before
    assert "consumer.start" not in world.calls


# ------------------------------------------------------------------------------------ H5 / PR27


class DroppingRegistry[S](HandlerRegistry[S]):
    """The real registry, whose `register_command` registers NOTHING (zero handlers)."""

    def register_command(self, command_type: Any, factory: Any) -> None:
        return None


class DoublingRegistry[S](HandlerRegistry[S]):
    """The real registry, whose `register_command` registers TWICE (two handlers)."""

    def register_command(self, command_type: Any, factory: Any) -> None:
        super().register_command(command_type, factory)
        super().register_command(command_type, factory)


def test_pr27_the_real_registration_builds_a_dispatcher_with_exactly_one_handler() -> None:
    dispatcher, factories = composition._wire()
    assert dispatcher is not None
    assert len(factories) == 1


async def test_pr27_zero_handlers_fail_the_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(composition, "HandlerRegistry", DroppingRegistry)
    world = World()
    with pytest.raises(DispatcherValidationError) as raised:
        await start_runtime(
            default_settings(monkeypatch, tmp_path),
            externals=Externals(
                mongo_client=world.mongo_client,
                ensure_indexes=cast("Callable[[Any], Awaitable[None]]", world.ensure),
                verify_indexes=cast("Callable[[Any], Awaitable[None]]", world.verify),
                migrate=cast("Callable[[Any], Awaitable[object]]", world.migrate),
                nats_connect=cast("Callable[[str], Awaitable[Any]]", world.nats_connect),
                subscriber=world.subscriber,
            ),
        )
    assert "ProjectFactCommand" in str(raised.value)
    assert world.calls == [], f"a connection was opened before the dispatcher failed: {world.calls}"
    assert world.mongo_uri is None
    assert world.nats_url is None
    assert world.kafka_settings is None


async def test_pr27_two_handlers_fail_the_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(composition, "HandlerRegistry", DoublingRegistry)
    world = World()
    with pytest.raises(DispatcherValidationError) as raised:
        await start_runtime(
            default_settings(monkeypatch, tmp_path),
            externals=Externals(
                mongo_client=world.mongo_client,
                ensure_indexes=cast("Callable[[Any], Awaitable[None]]", world.ensure),
                verify_indexes=cast("Callable[[Any], Awaitable[None]]", world.verify),
                migrate=cast("Callable[[Any], Awaitable[object]]", world.migrate),
                nats_connect=cast("Callable[[str], Awaitable[Any]]", world.nats_connect),
                subscriber=world.subscriber,
            ),
        )
    assert "2 command handlers are registered for ProjectFactCommand" in str(raised.value)
    assert world.calls == []
    assert world.mongo_uri is None


def test_the_settings_bundle_is_the_three_classes_load_settings_builds() -> None:
    import dataclasses

    names = {f.name: f.type for f in dataclasses.fields(ProjectorSettings)}
    assert names == {"mongo": MongoSettings, "kafka": KafkaSettings, "nats": NatsSettings}
