"""Feature 26, acceptance 2 (strong form): the connection OUTLIVES an idle timeout because of the
heartbeat, and would not without it.

"A `ping` frame arrives" is not the claim; deleting the ping must fail a test. So the real Gateway
(a real uvicorn, a real socket) sits behind an IDLE-TIMEOUT RELAY, the stand-in for the proxy or
load
balancer the heartbeat exists for (`openapi.yaml`: "so proxies do not close the connection"): it
forwards bytes both ways and CLOSES the connection when neither direction has carried a byte for
`IDLE_SECONDS`. The ping interval is a fraction of that, and the test holds the connection open for
many idle windows. #8's equivalent was a raw `TcpClient` with a read timeout
(`StreamHeartbeatHttpTests`);
#7 had none (its review 1 named this relay as the alternative it should have weighed).

The control (`test_the_relay_closes_a_connection_that_goes_quiet`) is the case that must fail to
detect: the SAME relay in front of a Gateway whose ping interval exceeds the idle window closes it.
Without the control, a relay that never closes anything would pass the strong form for free.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

IDLE_SECONDS = 0.5
PING_SECONDS = 0.12
HOLD_SECONDS = 3.0  # six idle windows


class IdleTimeoutRelay:
    def __init__(self, upstream_host: str, upstream_port: int, idle_seconds: float) -> None:
        self._upstream = (upstream_host, upstream_port)
        self._idle = idle_seconds
        self._server: asyncio.Server | None = None
        self.host = "127.0.0.1"
        self.port = 0
        self.closed_for_idleness = asyncio.Event()
        self.connections = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        self.connections += 1
        up_r, up_w = await asyncio.open_connection(*self._upstream)
        loop = asyncio.get_running_loop()
        last = loop.time()

        async def pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            nonlocal last
            while chunk := await src.read(65536):
                last = loop.time()
                dst.write(chunk)
                await dst.drain()

        async def watchdog() -> None:
            while loop.time() - last < self._idle:  # noqa: ASYNC110 - polls a timestamp, not a flag
                await asyncio.sleep(0.02)
            self.closed_for_idleness.set()

        tasks = [
            asyncio.create_task(pump(client_r, up_w)),
            asyncio.create_task(pump(up_r, client_w)),
            asyncio.create_task(watchdog()),
        ]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.wait(tasks)
            for writer in (client_w, up_w):
                writer.close()


@pytest.fixture
async def relay_to(
    serve: Callable[..., Awaitable[Any]],
) -> Any:
    relays: list[IdleTimeoutRelay] = []

    async def make(app: Any) -> IdleTimeoutRelay:
        upstream = await serve(app)
        relay = IdleTimeoutRelay(upstream.host, upstream.port, IDLE_SECONDS)
        await relay.start()
        relays.append(relay)
        return relay

    yield make
    for relay in relays:
        await relay.stop()


async def test_r55_the_connection_outlives_an_idle_timeout_because_of_the_heartbeat(
    harness: Any, relay_to: Any, raw_sse: Any
) -> None:
    harness.with_stream(ping_interval_seconds=PING_SECONDS)
    relay = await relay_to(harness.app)
    client = await raw_sse(relay.host, relay.port, "/orders/stream", dict(harness.bearer()))
    await client.next_frame(5, "stream.ready")

    loop = asyncio.get_running_loop()
    began = loop.time()
    pings = 0
    while loop.time() - began < HOLD_SECONDS:
        # a read bound well above the idle window: what ends a ping-less stream here is the RELAY
        # closing it (the proxy's behaviour), not this client giving up first
        frame = await client.next_frame(
            4 * IDLE_SECONDS, f"a frame while the relay's {IDLE_SECONDS} s idle window runs"
        )
        assert frame.event == "ping"
        assert frame.id is None
        pings += 1

    assert not relay.closed_for_idleness.is_set(), "the relay closed the stream for idleness"
    assert HOLD_SECONDS / IDLE_SECONDS >= 6, "the hold is not many idle windows long"
    assert pings >= int(HOLD_SECONDS / PING_SECONDS * 0.6), (
        f"only {pings} pings in {HOLD_SECONDS} s"
    )


async def test_the_relay_closes_a_connection_that_goes_quiet(
    harness: Any, relay_to: Any, raw_sse: Any
) -> None:
    """The control: a ping interval beyond the idle window, and the relay does what a proxy does."""
    harness.with_stream(ping_interval_seconds=30.0)
    relay = await relay_to(harness.app)
    client = await raw_sse(relay.host, relay.port, "/orders/stream", dict(harness.bearer()))
    await client.next_frame(5, "stream.ready")

    async with asyncio.timeout(5):
        await relay.closed_for_idleness.wait()

    with pytest.raises(pytest.fail.Exception, match=r"closed the connection|ended the response"):
        await client.next_frame(2, "a frame after the relay gave up on the idle connection")
