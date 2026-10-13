"""Private containers, pausing and paced polling for the readiness tests of feature 27 (S6).

Not a test module. Loaded BY PATH (the suite runs in importlib mode, so a sibling module is not
importable by name), the way `trace_support.py` is. It imports nothing from a service.

`R60` is proven against a dependency that is PAUSED, not stopped: a docker-paused container keeps
its TCP connection open and answers nothing, which is the failure a probe without a bound hangs on
(#7 shipped an unbounded NATS probe). Pausing a container the whole session shares would stall
every later test if the test that paused it died, so each readiness test starts a PRIVATE container
of its own (`private_*`) and pauses it only through `paused(...)`:

* `paused(container)` pauses on entry and unpauses in a `finally`, so a body that raises (an
  assertion, a timeout, a cancellation) still unpauses before the container is stopped. The only
  `.pause()` call in the repository's tests is the one in this module
  (`tests/architecture/test_pause_confinement.py` counts them), and
  `tests/observability/test_health_support.py` arms the guarantee.
* `poll(...)` is paced: the sleep sits between every two reads, so a read that fails in
  microseconds cannot turn the loop into a busy spin that burns its whole budget in a millisecond
  (#8 ids 63 and 69, unpaced readiness loops).
"""

import asyncio
import time
import warnings
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

import httpx
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from testcontainers.community.mongodb import MongoDbContainer
from testcontainers.community.nats import NatsContainer
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

POSTGRES_IMAGE = "postgres:18.6"
MONGO_IMAGE = "mongo:8.3.8"  # the compose pin (docker-compose.infra.yml)
NATS_IMAGE = "nats:2.14.5-alpine"  # the compose pin
KAFKA_IMAGE = "apache/kafka:4.3.1"  # the compose pin
POLL_INTERVAL_SECONDS = 0.25
_KAFKA_EXTERNAL_PORT = 9092
_KAFKA_INTERNAL_PORT = 29092
_KAFKA_CONTROLLER_PORT = 9093
_KAFKA_START_SCRIPT = "/testcontainers_health_kafka_start.sh"
_POSTGRES_PASSWORD = "otc_health_password"
_MONGO_USER = "otc_health"
_MONGO_PASSWORD = "otc_health_password"


@contextmanager
def paused(container: DockerContainer) -> Iterator[None]:
    """Pause `container` for the body and unpause it in a `finally`, whatever the body does."""
    wrapped = container.get_wrapped_container()
    wrapped.pause()
    try:
        yield
    finally:
        wrapped.reload()
        if wrapped.status == "paused":
            wrapped.unpause()


def status_of(container: DockerContainer) -> str:
    wrapped = container.get_wrapped_container()
    wrapped.reload()
    status: str = wrapped.status
    return status


@contextmanager
def private_postgres() -> Iterator[tuple[PostgresContainer, str]]:
    """A Postgres of this test's own; yields the container and the SQLAlchemy asyncpg URL."""
    container = PostgresContainer(
        POSTGRES_IMAGE,
        username="postgres",
        password=_POSTGRES_PASSWORD,
        dbname="postgres",
        driver=None,
    )
    with container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        yield (
            container,
            f"postgresql+asyncpg://postgres:{_POSTGRES_PASSWORD}@{host}:{port}/postgres",
        )


@contextmanager
def private_nats() -> Iterator[tuple[NatsContainer, str]]:
    container = NatsContainer(NATS_IMAGE)
    with warnings.catch_warnings():
        # testcontainers 4.15.0's own `NatsContainer.start()` calls its deprecated
        # `wait_for_logs(<str>)` (the same filter the root conftest's `nats_server` carries).
        warnings.filterwarnings(
            "ignore",
            message="The wait_for_logs function with string or callable predicates is deprecated",
            category=DeprecationWarning,
        )
        container.start()
    try:
        yield container, container.nats_uri()
    finally:
        container.stop()


@contextmanager
def private_mongo() -> Iterator[tuple[MongoDbContainer, str]]:
    """A MongoDB of this test's own; yields the container and a URI with its root credentials."""
    container = MongoDbContainer(MONGO_IMAGE, username=_MONGO_USER, password=_MONGO_PASSWORD)
    with container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(27017))
        yield (
            container,
            f"mongodb://{_MONGO_USER}:{_MONGO_PASSWORD}@{host}:{port}/?authSource=admin",
        )


@contextmanager
def private_kafka() -> Iterator[tuple[DockerContainer, str]]:
    """A single-node KRaft broker of this test's own, the shape the root conftest's `kafka_server`
    builds (the generic `DockerContainer`; the advertised external address needs the host port
    Docker assigns, so the broker starts from a script written after the container is up). Auto
    topic creation is off, as in the deployed broker."""
    container = (
        DockerContainer(KAFKA_IMAGE)
        .with_exposed_ports(_KAFKA_EXTERNAL_PORT)
        .with_command(
            [
                "/bin/sh",
                "-c",
                f"while [ ! -f {_KAFKA_START_SCRIPT} ]; do sleep 0.1; done; "
                f"exec /bin/sh {_KAFKA_START_SCRIPT}",
            ]
        )
        .with_env("KAFKA_NODE_ID", "1")
        .with_env("KAFKA_PROCESS_ROLES", "broker,controller")
        .with_env(
            "KAFKA_LISTENERS",
            f"PLAINTEXT://:{_KAFKA_INTERNAL_PORT},CONTROLLER://:{_KAFKA_CONTROLLER_PORT},"
            f"EXTERNAL://:{_KAFKA_EXTERNAL_PORT}",
        )
        .with_env(
            "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP",
            "CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,EXTERNAL:PLAINTEXT",
        )
        .with_env("KAFKA_CONTROLLER_LISTENER_NAMES", "CONTROLLER")
        .with_env("KAFKA_INTER_BROKER_LISTENER_NAME", "PLAINTEXT")
        .with_env("KAFKA_CONTROLLER_QUORUM_VOTERS", f"1@localhost:{_KAFKA_CONTROLLER_PORT}")
        .with_env("KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR", "1")
        .with_env("KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR", "1")
        .with_env("KAFKA_TRANSACTION_STATE_LOG_MIN_ISR", "1")
        .with_env("KAFKA_AUTO_CREATE_TOPICS_ENABLE", "false")
        .with_env("KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS", "0")
        .with_env("CLUSTER_ID", "MkU3OEVBNTcwNTJENDM2Qk")
    )
    with container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(_KAFKA_EXTERNAL_PORT))
        advertised = f"PLAINTEXT://localhost:{_KAFKA_INTERNAL_PORT},EXTERNAL://{host}:{port}"
        script = (
            f"#!/bin/sh\nexport KAFKA_ADVERTISED_LISTENERS='{advertised}'\n"
            "exec /etc/kafka/docker/run\n"
        )
        container.copy_into_container(script.encode("utf-8"), _KAFKA_START_SCRIPT, mode=0o755)
        LogMessageWaitStrategy("Kafka Server started").with_startup_timeout(120).wait_until_ready(
            container
        )
        yield container, f"{host}:{port}"


async def poll[T](
    read: Callable[[], Awaitable[T]],
    accept: Callable[[T], bool],
    *,
    within: float,
    claim: str,
    interval: float = POLL_INTERVAL_SECONDS,
) -> list[T]:
    """Read, then sleep `interval`, until `accept(sample)`; returns every sample taken.

    The wait is `asyncio.timeout(within)` with a message naming `claim`; the pause between two reads
    is unconditional, so the number of reads in `within` seconds is at most `within / interval + 1`
    whatever `read` costs."""
    samples: list[T] = []
    try:
        async with asyncio.timeout(within):
            while True:
                sample = await read()
                samples.append(sample)
                if accept(sample):
                    return samples
                await asyncio.sleep(interval)
    except TimeoutError as error:
        raise AssertionError(
            f"not within {within} s: {claim} (after {len(samples)} reads, last {samples[-1:]!r})"
        ) from error


async def create_topics(bootstrap_servers: str, names: Sequence[str]) -> None:
    """Create `names` on a private broker (auto-creation is off, as in the deployed broker)."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        await admin.create_topics(
            [NewTopic(name=name, num_partitions=3, replication_factor=1) for name in names]
        )
    finally:
        await admin.close()


SCHEDULING_SLACK_SECONDS = 0.25
LIVE_ANSWER_SECONDS = 0.5


@dataclass(frozen=True)
class PauseObservation:
    seconds_to_down: float
    polls_while_paused: int
    live_seconds: list[float]
    seconds_to_recover: float
    down_checks: dict[str, str | None]


def down_checks_of(response: httpx.Response) -> dict[str, str | None]:
    checks: dict[str, dict[str, str]] = response.json()["checks"]
    return {
        name: check.get("detail") for name, check in checks.items() if check["status"] == "down"
    }


async def observe_pause(
    *,
    container: DockerContainer,
    ready: Callable[[], Awaitable[httpx.Response]],
    live: Callable[[], Awaitable[httpx.Response]],
    paused_check: str,
    check_names: Sequence[str],
    bound: float = 2.0,
    interval: float = POLL_INTERVAL_SECONDS,
    recovery_within: float = 30.0,
) -> PauseObservation:
    """Pause `container`; prove the claims of `R60` about the check it backs; unpause; prove the
    service recovers. Every wait is `poll` (paced, bounded, naming its claim); the container is
    unpaused by `paused` in a `finally` whatever fails."""
    baseline = await poll(
        ready,
        lambda response: response.status_code == 200,
        within=recovery_within,
        claim="readiness was not 200 before the pause: the test has no baseline",
    )
    assert down_checks_of(baseline[-1]) == {}, baseline[-1].text
    assert sorted(baseline[-1].json()["checks"]) == sorted(check_names), baseline[-1].text

    live_seconds: list[float] = []

    async def read_while_paused() -> httpx.Response:
        started = time.monotonic()
        liveness = await live()
        live_seconds.append(time.monotonic() - started)
        assert (liveness.status_code, liveness.json()) == (200, {"status": "up"}), liveness.text
        return await ready()

    with paused(container):
        paused_at = time.monotonic()
        samples = await poll(
            read_while_paused,
            lambda response: response.status_code == 503,
            within=bound + interval + SCHEDULING_SLACK_SECONDS + 5.0,
            claim=f"readiness never reported {paused_check} down while its container was paused",
        )
        seconds_to_down = time.monotonic() - paused_at
        down = samples[-1]
        # one more liveness read after the dependency is known down: it still answers at once
        await read_while_paused_live_only(live, live_seconds)

    assert seconds_to_down <= bound + interval + SCHEDULING_SLACK_SECONDS, (
        f"R60: {paused_check} was reported down after {seconds_to_down:.2f} s, not within its "
        f"{bound} s bound plus one {interval} s poll interval"
    )
    assert down.json()["status"] == "down", down.text
    assert down_checks_of(down).keys() == {paused_check}, (
        f"R60: readiness must name ONLY {paused_check}; it named {down_checks_of(down)}"
    )
    assert max(live_seconds) <= LIVE_ANSWER_SECONDS, (
        f"R60: liveness took {max(live_seconds):.2f} s with a dependency paused: it consulted it"
    )

    recovery_started = time.monotonic()
    recovered = await poll(
        ready,
        lambda response: response.status_code == 200,
        within=recovery_within,
        claim=f"readiness did not return to 200 after {paused_check}'s container was unpaused",
    )
    assert down_checks_of(recovered[-1]) == {}
    return PauseObservation(
        seconds_to_down=seconds_to_down,
        polls_while_paused=len(samples),
        live_seconds=live_seconds,
        seconds_to_recover=time.monotonic() - recovery_started,
        down_checks=down_checks_of(down),
    )


async def read_while_paused_live_only(
    live: Callable[[], Awaitable[httpx.Response]], live_seconds: list[float]
) -> None:
    started = time.monotonic()
    liveness = await live()
    live_seconds.append(time.monotonic() - started)
    assert (liveness.status_code, liveness.json()) == (200, {"status": "up"}), liveness.text
