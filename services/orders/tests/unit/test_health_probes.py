"""R60 / OR6, S6.2: every readiness probe is BOUNDED; one that never answers is `down` within its
bound plus 100 ms.

Each kind is driven by a dependency that accepts the call and never answers, which is what a
docker-paused container does (the TCP connection stays open, nothing is read). PostgreSQL: a real
listening socket that accepts and stays silent (asyncpg's startup message is never answered). Kafka
and NATS: a client whose call never returns (the paused-broker integration cases of S6.7 are the
real thing). The probes are called DIRECTLY, not through `HealthCheck`, so that the bound under test
is the probe's own: a `HealthCheck` bound around an unbounded probe would hide its removal. Each
test carries an outer `asyncio.timeout` that is much longer than the bound, so a probe that lost its
bound fails on the elapsed-time assertion naming the claim instead of hanging the suite.

The Mongo probe (the Projector's canonical) is bounded the same way in the Projector's tests; the
copies are parity-guarded (`tests/architecture/test_observability_copy_parity.py`).
"""

import asyncio
import contextlib
import math
import time
from typing import Any

import pytest

from otc_orders.infrastructure.health.checks import (
    SHUTTING_DOWN,
    CheckResult,
    HealthCheck,
    dead_tasks,
    run_checks,
)
from otc_orders.infrastructure.health.kafka_probe import KafkaAdminProbe
from otc_orders.infrastructure.health.nats_probe import (
    NatsNotConnectedError,
    NatsProbe,
)
from otc_orders.infrastructure.health.postgres_probe import PostgresProbe

BOUND = 0.4
SLACK = 0.1  # the claim: down within the bound plus 100 ms
RUNAWAY = 4.0  # the outer guard: far above the bound, so a lost bound is seen as elapsed time


async def silent_server() -> tuple[asyncio.Server, int, list[asyncio.StreamWriter]]:
    """A TCP server that accepts every connection and never reads or writes."""
    held: list[asyncio.StreamWriter] = []

    async def hold(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        held.append(writer)
        await asyncio.sleep(RUNAWAY * 4)

    server = await asyncio.start_server(hold, "127.0.0.1", 0)
    port: int = server.sockets[0].getsockname()[1]
    return server, port, held


async def elapsed_until_down(call: Any) -> float:
    started = time.monotonic()
    with pytest.raises((TimeoutError, OSError)):
        async with asyncio.timeout(RUNAWAY):
            await call()
    return time.monotonic() - started


def assert_within_bound(elapsed: float, kind: str) -> None:
    assert elapsed <= BOUND + SLACK, (
        f"R60: the {kind} probe took {elapsed:.3f} s against a bound of {BOUND} s: "
        "a probe that never answers must be down within its bound plus 100 ms"
    )


async def test_or6_the_postgres_probe_is_down_within_its_bound_when_the_server_is_silent() -> None:
    server, port, held = await silent_server()
    probe = PostgresProbe(
        f"postgresql+asyncpg://postgres:secret@127.0.0.1:{port}/otc", bound_seconds=BOUND
    )
    try:
        assert_within_bound(await elapsed_until_down(probe), "PostgreSQL")
    finally:
        await probe.aclose()
        for writer in held:
            writer.close()
        server.close()
        await server.wait_closed()


class HangingAdmin:
    """An admin client whose `start` and/or `describe_cluster` never return."""

    def __init__(self, *, hang_start: bool, hang_describe: bool) -> None:
        self.hang_start = hang_start
        self.hang_describe = hang_describe
        self.started = False
        self.closed = False

    async def start(self) -> None:
        if self.hang_start:
            await asyncio.sleep(RUNAWAY * 4)
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def describe_cluster(self) -> dict[str, Any]:
        if self.hang_describe:
            await asyncio.sleep(RUNAWAY * 4)
        return {"brokers": []}


async def test_or6_the_kafka_probe_is_down_within_its_bound_when_the_bootstrap_is_silent() -> None:
    client = HangingAdmin(hang_start=True, hang_describe=False)
    probe = KafkaAdminProbe(
        "broker:9092",
        client_id="otc-test-health",
        bound_seconds=BOUND,
        client_factory=lambda *_: client,
    )
    assert_within_bound(await elapsed_until_down(probe), "Kafka (bootstrap)")
    assert client.closed, "a client whose start the bound cancelled is closed, never kept"


async def test_or6_the_kafka_probe_is_down_within_its_bound_when_a_started_client_goes_silent() -> (
    None
):
    client = HangingAdmin(hang_start=False, hang_describe=True)
    probe = KafkaAdminProbe(
        "broker:9092",
        client_id="otc-test-health",
        bound_seconds=BOUND,
        client_factory=lambda *_: client,
    )
    assert_within_bound(await elapsed_until_down(probe), "Kafka (describe_cluster)")
    assert not client.closed, "a call the bound cancelled leaves the long-lived client in place"


async def test_or6_the_kafka_probe_keeps_one_lazily_built_client_across_a_cancelled_call() -> None:
    built: list[HangingAdmin] = []

    def factory(brokers: str, client_id: str) -> HangingAdmin:
        client = HangingAdmin(hang_start=False, hang_describe=False)
        built.append(client)
        assert (brokers, client_id) == ("broker:9092", "otc-test-health")
        return client

    probe = KafkaAdminProbe(
        "broker:9092", client_id="otc-test-health", bound_seconds=BOUND, client_factory=factory
    )
    assert built == [], "nothing is built at construction: the client starts on the first call"
    await probe()
    built[0].hang_describe = True
    await elapsed_until_down(probe)
    built[0].hang_describe = False
    await probe()
    assert len(built) == 1, "the same client answers after the cancelled call"
    await probe.aclose()
    assert built[0].closed


class SilentNats:
    def __init__(self, *, connected: bool = True) -> None:
        self.is_connected = connected
        self.flush_timeouts: list[int] = []

    async def flush(self, timeout: int = 10) -> None:  # noqa: ASYNC109 - the nats client's name
        self.flush_timeouts.append(timeout)
        await asyncio.sleep(RUNAWAY * 4)


async def test_or6_the_nats_probe_is_down_within_its_bound_when_the_pong_never_comes() -> None:
    connection = SilentNats()
    probe = NatsProbe(connection, bound_seconds=BOUND)
    assert_within_bound(await elapsed_until_down(probe), "NATS")
    assert connection.flush_timeouts == [math.ceil(BOUND)], "flush gets its own whole-second bound"


async def test_or6_a_client_that_is_not_connected_is_down_at_once_without_a_flush() -> None:
    connection = SilentNats(connected=False)
    started = time.monotonic()
    try:
        async with asyncio.timeout(1.0):
            await NatsProbe(connection, bound_seconds=BOUND)()
    except NatsNotConnectedError:
        pass
    except TimeoutError:
        pytest.fail("R60: a client that is not connected was flushed, not reported down at once")
    else:
        pytest.fail("R60: a client that is not connected was reported up")
    assert time.monotonic() - started < SLACK
    assert connection.flush_timeouts == [], "no PING is sent on a client that cannot carry it"


# ------------------------------------------------------------------ HealthCheck / run_checks


async def never() -> object:
    await asyncio.sleep(RUNAWAY * 4)
    return None


async def test_or6_a_health_check_whose_probe_never_answers_is_down_within_its_own_bound() -> None:
    started = time.monotonic()
    result = await HealthCheck("writeModel", never, timeout_seconds=BOUND).run()
    assert time.monotonic() - started <= BOUND + SLACK
    assert result == CheckResult("writeModel", False, f"no answer within {BOUND} s")


async def test_or6_two_hung_checks_cost_one_bound_not_two() -> None:
    started = time.monotonic()
    results = await run_checks(
        [
            HealthCheck("writeModel", never, timeout_seconds=BOUND),
            HealthCheck("rpcTransport", never, timeout_seconds=BOUND),
        ]
    )
    assert time.monotonic() - started <= BOUND + SLACK, "the checks run together"
    assert [r.up for r in results] == [False, False]


async def test_r60_a_shutting_down_runtime_reports_every_check_down_and_probes_nothing() -> None:
    calls: list[str] = []

    async def probe() -> object:
        calls.append("probe")
        return None

    results = await run_checks(
        [HealthCheck("writeModel", probe), HealthCheck("rpcTransport", probe)], shutting_down=True
    )
    assert results == [
        CheckResult("writeModel", False, SHUTTING_DOWN),
        CheckResult("rpcTransport", False, SHUTTING_DOWN),
    ]
    assert calls == []


async def test_r60_a_dead_task_makes_its_check_down_with_the_task_named_and_no_probe_runs() -> None:
    calls: list[str] = []

    async def probe() -> object:
        calls.append("probe")
        return None

    async def finished() -> None:
        return None

    async def waiting() -> None:
        await asyncio.sleep(RUNAWAY)

    done = asyncio.create_task(finished())
    alive = asyncio.create_task(waiting())
    await done
    try:
        tasks = {"nats-responder": done, "saga-consumer": alive}
        dead = HealthCheck(
            "rpcTransport", probe, task_reasons=dead_tasks(tasks, ("nats-responder",))
        )
        fine = HealthCheck("factStream", probe, task_reasons=dead_tasks(tasks, ("saga-consumer",)))
        assert await dead.run() == CheckResult(
            "rpcTransport", False, "transport task nats-responder is not running"
        )
        assert await fine.run() == CheckResult("factStream", True, None)
        assert calls == ["probe"], "only the healthy check probed"
    finally:
        alive.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await alive
