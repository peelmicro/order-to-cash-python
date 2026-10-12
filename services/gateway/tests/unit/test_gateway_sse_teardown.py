"""Feature 26, acceptance 3: a client disconnect releases the subscription.

#8 D1: the teardown is HAND-BUILT in #9 as it was in #8 (#7's was Express's engine-supplied
`res.on('close')`), and in #8 deleting its `Unsubscribe` left every test green: each disconnected
`EventSource` would have leaked a queue the publisher feeds on every fact. Armed three ways in
`progress/impl_gateway_sse_push.md`: delete the unsubscribe; do not watch the request's disconnect
(the pump would then unwind only when a later ping hit a dead socket); subscribe on a different hub
than the one the publisher uses.

The ping interval is 30 s in every test here, so a ping can never be what notices the departure: the
release must come from the disconnect itself, within `RELEASE_SECONDS`.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

RELEASE_SECONDS = 2.0


async def released(hub: Any, claim: str) -> None:
    """Wait (bounded, paced 10 ms) for the hub's subscriber count to reach zero."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + RELEASE_SECONDS
    while hub.subscriber_count != 0:
        if loop.time() > deadline:
            pytest.fail(
                f"{claim}: {hub.subscriber_count} subscription(s) still on the publisher's hub "
                f"{RELEASE_SECONDS} s after the client left"
            )
        await asyncio.sleep(0.01)


async def test_r55_an_asgi_disconnect_releases_the_subscription_and_ends_the_response(
    harness: Any, asgi_stream: Any
) -> None:
    stream = asgi_stream(harness.app, "/orders/stream", dict(harness.bearer()))
    await stream.frames(1, "stream.ready")
    assert harness.hub.subscriber_count == 1, (
        "the open stream is not subscribed on the publisher's hub"
    )

    await stream.disconnect()

    await released(harness.hub, "an http.disconnect")
    await stream.ended("an http.disconnect")
    assert stream.error is None


async def test_r55_a_client_that_closes_its_tcp_connection_releases_the_subscription(
    harness: Any,
    serve: Callable[..., Awaitable[Any]],
    raw_sse: Callable[..., Awaitable[Any]],
) -> None:
    """Over a real socket and a real uvicorn: the disconnect arrives as a TCP close, with a 30 s
    ping interval, so only the disconnect watcher can release it."""
    server = await serve(harness.app)
    client = await raw_sse(server.host, server.port, "/orders/stream", dict(harness.bearer()))
    ready = await client.next_frame(5, "stream.ready")
    assert ready.event == "stream.ready"
    assert harness.hub.subscriber_count == 1, (
        "the open stream is not subscribed on the publisher's hub"
    )

    await client.close()

    await released(harness.hub, "a closed TCP connection")


async def test_r55_every_one_of_many_connections_is_released_when_its_client_leaves(
    harness: Any, asgi_stream: Any
) -> None:
    streams = [asgi_stream(harness.app, "/orders/stream", dict(harness.bearer())) for _ in range(5)]
    for stream in streams:
        await stream.frames(1, "stream.ready")
    assert harness.hub.subscriber_count == 5

    for stream in streams[:3]:
        await stream.disconnect()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + RELEASE_SECONDS
    while harness.hub.subscriber_count != 2:
        assert loop.time() < deadline, f"{harness.hub.subscriber_count} left of 5 after 3 left"
        await asyncio.sleep(0.01)

    # the two that stayed still receive
    sent = harness.hub.publish("order.updated", __import__("uuid").UUID(int=1), "{}")
    for stream in streams[3:]:
        (frame,) = await stream.frames(1, "a frame for a connection that stayed")
        assert frame.id == sent.cursor
