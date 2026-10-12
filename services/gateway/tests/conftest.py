"""Server-sent-event test support shared by the Gateway's unit and integration suites (feature 26).

Three instruments, each independent of the code under test (a frame is parsed here, never by
`otc_gateway.presentation.event_stream`):

* `parse_frames`: raw SSE bytes -> `SseFrame`s, by the SSE line grammar (`id:`, `event:`, `data:`,
  a blank line ends a frame);
* `AsgiStream`: runs the ASGI app directly, so the test controls `receive` (the disconnect) and
  sees every `send` as it happens (`httpx.ASGITransport` buffers a whole response, which a
  never-ending stream never completes);
* `serve`: the SAME app on a real TCP socket under a real `uvicorn.Server`, for what only a socket
  can show (a heartbeat that keeps a connection alive, a disconnect that arrives as a TCP close).

Loop scope: nothing here owns a loop; every instrument is created and closed by the test (or the
function-scoped fixture) that asks for it, in that test's loop. Every wait is bounded
(`asyncio.timeout`) with a message naming the claim.
"""

import asyncio
import json
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Literal

import pytest
import uvicorn

WAIT_SECONDS = 10.0


@dataclass(frozen=True)
class SseFrame:
    id: str | None
    event: str
    data: str

    def json(self) -> dict[str, Any]:
        parsed: dict[str, Any] = json.loads(self.data)
        return parsed


def parse_frames(raw: bytes) -> list[SseFrame]:
    frames: list[SseFrame] = []
    for block in raw.decode("utf-8").split("\n\n"):
        if not block:
            continue
        frame_id: str | None = None
        event: str | None = None
        data: list[str] = []
        for line in block.split("\n"):
            name, _, value = line.partition(": ")
            if name == "id":
                frame_id = value
            elif name == "event":
                event = value
            elif name == "data":
                data.append(value)
            else:
                raise AssertionError(f"not an SSE line: {line!r}")
        assert event is not None, f"a frame with no event: {block!r}"
        frames.append(SseFrame(frame_id, event, "\n".join(data)))
    return frames


class AsgiStream:
    """One request to the app, run as a task; the body arrives frame by frame."""

    def __init__(
        self,
        app: Any,
        path: str,
        headers: dict[str, str],
        on_send: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """`on_send`, when given, is called with every ASGI message the app sends, BEFORE it is
        recorded: a test publishes from inside a chosen write (the window between the replay
        snapshot and the first live read)."""
        path_only, _, query = path.partition("?")
        self._on_send = on_send
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self._buffer = b""
        self._chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.finished = asyncio.Event()
        self.started = asyncio.Event()
        self.error: BaseException | None = None
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path_only,
            "raw_path": path_only.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("127.0.0.1", 50000),
            "server": ("gateway.test", 80),
            "app": app,
        }
        self._task = asyncio.create_task(self._run(app, scope))

    async def _receive(self) -> dict[str, Any]:
        return await self._incoming.get()

    async def _send(self, message: dict[str, Any]) -> None:
        if self._on_send is not None:
            self._on_send(message)
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
            self.started.set()
        elif message["type"] == "http.response.body":
            if message.get("body"):
                await self._chunks.put(message["body"])
            if not message.get("more_body", False):
                await self._chunks.put(None)

    async def _run(self, app: Any, scope: dict[str, Any]) -> None:
        try:
            await app(scope, self._receive, self._send)
        except Exception as error:
            self.error = error
        finally:
            self.finished.set()
            await self._chunks.put(None)

    async def frames(self, count: int, claim: str, within: float = WAIT_SECONDS) -> list[SseFrame]:
        """The next `count` frames, bounded by `within`; fewer arriving fails naming `claim`."""
        found: list[SseFrame] = []
        try:
            async with asyncio.timeout(within):
                while len(found) < count:
                    while b"\n\n" not in self._buffer:
                        chunk = await self._chunks.get()
                        if chunk is None:
                            pytest.fail(f"{claim}: the stream ended after {len(found)} frames")
                        self._buffer += chunk
                    block, _, self._buffer = self._buffer.partition(b"\n\n")
                    found += parse_frames(block + b"\n\n")
        except TimeoutError:
            pytest.fail(f"{claim}: {len(found)} of {count} frames within {within} s")
        return found

    async def leftovers(self, claim: str) -> list[SseFrame]:
        """Every complete frame the client has not yet read, once the response has ended: what a
        client that kept reading would still have received before the stream closed."""
        await self.ended(claim)
        raw = self._buffer
        self._buffer = b""
        while not self._chunks.empty():
            chunk = self._chunks.get_nowait()
            if chunk is not None:
                raw += chunk
        return parse_frames(raw) if raw else []

    async def response_started(self, claim: str) -> int:
        """The status line of the response, bounded."""
        try:
            async with asyncio.timeout(WAIT_SECONDS):
                await self.started.wait()
        except TimeoutError:
            pytest.fail(f"{claim}: no response within {WAIT_SECONDS} s")
        assert self.status is not None
        return self.status

    async def disconnect(self) -> None:
        await self._incoming.put({"type": "http.disconnect"})

    async def ended(self, claim: str) -> None:
        try:
            async with asyncio.timeout(WAIT_SECONDS):
                await self.finished.wait()
        except TimeoutError:
            pytest.fail(f"{claim}: the response did not end within {WAIT_SECONDS} s")

    async def close(self) -> None:
        await self.disconnect()
        self._task.cancel()
        await asyncio.wait({self._task})


@pytest.fixture
async def asgi_stream() -> AsyncIterator[Callable[..., AsgiStream]]:
    """`asgi_stream(app, path, headers, on_send=None)`: every stream it opened is disconnected and
    awaited at teardown, in this test's loop."""
    opened: list[AsgiStream] = []

    def open_stream(
        app: Any,
        path: str,
        headers: dict[str, str],
        on_send: Callable[[dict[str, Any]], None] | None = None,
    ) -> AsgiStream:
        stream = AsgiStream(app, path, headers, on_send)
        opened.append(stream)
        return stream

    yield open_stream
    for stream in opened:
        await stream.close()


# --------------------------------------------------------------------------------- a real socket


@dataclass
class LiveServer:
    host: str
    port: int
    server: uvicorn.Server
    _task: asyncio.Task[None] = field(repr=False)
    _socket: socket.socket = field(repr=False)

    async def stop(self) -> None:
        self.server.should_exit = True
        try:
            async with asyncio.timeout(WAIT_SECONDS):
                await asyncio.wait({self._task})
        except TimeoutError:
            pytest.fail(f"uvicorn did not stop within {WAIT_SECONDS} s")
        finally:
            self._socket.close()


async def _serve(app: Any, lifespan: Literal["auto", "on", "off"]) -> LiveServer:
    """`app` under a real uvicorn on a socket THIS function binds and holds (port 0: the kernel
    assigns it, and it is never released and re-picked)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="warning", lifespan=lifespan, timeout_graceful_shutdown=2)
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    live = LiveServer(host, port, server, task, sock)
    async with asyncio.timeout(WAIT_SECONDS):
        while not server.started:
            if task.done():
                task.result()
            await asyncio.sleep(0.01)
    return live


@pytest.fixture
async def serve() -> AsyncIterator[Callable[..., Awaitable[LiveServer]]]:
    """`await serve(app)`: every server started is stopped (and its socket closed) at teardown."""
    started: list[LiveServer] = []

    async def start(app: Any, lifespan: Literal["auto", "on", "off"] = "off") -> LiveServer:
        live = await _serve(app, lifespan)
        started.append(live)
        return live

    yield start
    for live in reversed(started):
        await live.stop()


@pytest.fixture
async def raw_sse() -> AsyncIterator[Callable[..., Awaitable[RawSseClient]]]:
    """`await raw_sse(host, port, path, headers)`: a bare TCP client, closed at teardown."""
    opened: list[RawSseClient] = []

    async def connect(host: str, port: int, path: str, headers: dict[str, str]) -> RawSseClient:
        client = await RawSseClient.connect(host, port, path, headers)
        opened.append(client)
        return client

    yield connect
    for client in opened:
        await client.close()


class RawSseClient:
    """A bare TCP client: one HTTP/1.1 GET, then frames read off the socket."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._buffer = b""
        self.head = b""

    @classmethod
    async def connect(
        cls, host: str, port: int, path: str, headers: dict[str, str]
    ) -> RawSseClient:
        reader, writer = await asyncio.open_connection(host, port)
        client = cls(reader, writer)
        lines = [f"GET {path} HTTP/1.1", f"Host: {host}:{port}", "Accept: text/event-stream"]
        lines += [f"{k}: {v}" for k, v in headers.items()]
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
        await writer.drain()
        async with asyncio.timeout(WAIT_SECONDS):
            client.head = await reader.readuntil(b"\r\n\r\n")
        return client

    async def next_frame(self, within: float, claim: str) -> SseFrame:
        """The next frame, or fail naming `claim` when nothing complete arrives within `within`."""
        try:
            async with asyncio.timeout(within):
                while b"\n\n" not in self._buffer:
                    # HTTP/1.1 chunked transfer coding, as uvicorn writes a body of unknown length
                    size_line = await self._reader.readuntil(b"\r\n")
                    size = int(size_line.strip().split(b";")[0] or b"0", 16)
                    if size == 0:
                        pytest.fail(f"{claim}: the server ended the response")
                    self._buffer += (await self._reader.readexactly(size + 2))[:-2]
        except TimeoutError:
            pytest.fail(f"{claim}: no frame within {within} s")
        except asyncio.IncompleteReadError, ConnectionError:
            pytest.fail(f"{claim}: the server closed the connection")
        block, _, self._buffer = self._buffer.partition(b"\n\n")
        return parse_frames(block + b"\n\n")[0]

    async def close(self) -> None:
        self._writer.close()
        with suppress(OSError):
            await self._writer.wait_closed()
