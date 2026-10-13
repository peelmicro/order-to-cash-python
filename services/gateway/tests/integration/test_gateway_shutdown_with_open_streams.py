"""`OR13` (item 13, S7.5): an exit signal ends every open `GET /orders/stream` and logs no error.

Before `GatewayServer`, SIGTERM left uvicorn waiting `GRACEFUL_SHUTDOWN_SECONDS` for the open
responses, then logging `Cancel N running task(s), timeout graceful shutdown exceeded` at ERROR and
one `Exception in ASGI application ... CancelledError` per stream
(`progress/review_gateway_sse_push.md` line 66). #8 ends a stream at host shutdown through the
framework and logs nothing; the Gateway now ends its streams itself on the exit signal
(`design.md` 8.3).

A REAL `python -m otc_gateway` child over the suite's Docker-held NATS and MongoDB (the port is a
literal in the 38400s, free-checked first, like `test_gateway_log_contract.py`; the settings refuse
port 0). Two streams are opened over RAW sockets (`stream.ready` read from each, so both are
subscribed), SIGTERM is sent, and the test then judges, all at once: both streams reached EOF within
2 s of the signal, the process exited before the graceful bound, with code 0 (or the re-raised
SIGTERM), and no stderr line is an ERROR or names `Exception in ASGI application`. Every line must
be JSON (R58). Loop scope: function.
"""

import asyncio
import importlib.util
import signal
import socket
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from otc_gateway.__main__ import GRACEFUL_SHUTDOWN_SECONDS

pytestmark = pytest.mark.integration

SUPPORT_PATH = Path(__file__).resolve().parents[4] / "tests/observability/log_contract_support.py"
OPERATOR_PASSWORD = "shutdown-operator-password"
JWT_SECRET = "shutdown-jwt-secret-0123456789abcdef-0123456789"
PORT = 38422
STREAM_ENDS_WITHIN_SECONDS = 2.0


def load_support() -> Any:
    spec = importlib.util.spec_from_file_location("log_contract_support", SUPPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def something_listens(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


async def open_stream(token: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection("127.0.0.1", PORT)
    writer.write(
        (
            "GET /orders/stream HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            f"Authorization: Bearer {token}\r\nAccept: text/event-stream\r\n\r\n"
        ).encode()
    )
    await writer.drain()
    received = b""
    async with asyncio.timeout(15):
        while b"stream.ready" not in received:
            chunk = await reader.read(65536)
            assert chunk, f"the stream closed before stream.ready: {received!r}"
            received += chunk
    return reader, writer


async def seconds_until_eof(
    reader: asyncio.StreamReader, since: float, bound: float
) -> float | None:
    """Seconds from `since` to the stream's EOF; None if it did not end within `bound`."""
    try:
        async with asyncio.timeout(bound):
            while await reader.read(65536):
                pass
    except TimeoutError:
        return None
    return time.monotonic() - since


async def test_or13_an_exit_signal_ends_every_open_stream_before_the_bound_and_logs_no_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, nats_server: Any, fresh_mongo_database: Any
) -> None:
    support = load_support()
    assert not something_listens(PORT), f"port {PORT} is already in use: free it and re-run"
    monkeypatch.chdir(tmp_path)  # no developer `.env`
    for name, value in {
        "NATS_URL": nats_server.url,
        "MONGO_URI": fresh_mongo_database.uri,
        "MONGO_DB_READMODEL": fresh_mongo_database.name,
        "JWT_SECRET": JWT_SECRET,
        "GATEWAY_OPERATOR_PASSWORD": OPERATOR_PASSWORD,
        "GATEWAY_HOST": "127.0.0.1",
        "GATEWAY_PORT": str(PORT),
    }.items():
        monkeypatch.setenv(name, value)
    process = support.spawn(
        support.python_module("otc_gateway"), cwd=tmp_path, tmp_path=tmp_path, name="gateway"
    )
    writers: list[asyncio.StreamWriter] = []
    try:
        await support.wait_for_event(
            process, "the Gateway's application startup complete", support.booted
        )
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORT}", timeout=10.0) as client:
            login = await client.post(
                "/auth/login", json={"username": "operator", "password": OPERATOR_PASSWORD}
            )
        assert login.status_code == 200, login.text
        token = login.json()["accessToken"]
        readers = []
        for _ in range(2):
            reader, writer = await open_stream(token)
            readers.append(reader)
            writers.append(writer)

        signalled = time.monotonic()
        process.popen.send_signal(signal.SIGTERM)
        ended = await asyncio.gather(
            *(
                seconds_until_eof(reader, signalled, GRACEFUL_SHUTDOWN_SECONDS + 15)
                for reader in readers
            )
        )
        code = await asyncio.wait_for(asyncio.to_thread(process.popen.wait), timeout=30)
        exited_after = time.monotonic() - signalled
    finally:
        for writer in writers:
            writer.close()
        support.kill(process)

    lines = support.parse([line for line in process.stderr_text().split("\n") if line.strip()])
    errors = [line for line in lines if line.get("level") in {"error", "critical"}]
    traces = [line for line in lines if "Exception in ASGI application" in str(line.get("event"))]
    problems = []
    if any(seconds is None or seconds > STREAM_ENDS_WITHIN_SECONDS for seconds in ended):
        problems.append(
            f"OR13: the streams ended after {ended} s; each must end within "
            f"{STREAM_ENDS_WITHIN_SECONDS} s of the exit signal"
        )
    if exited_after >= GRACEFUL_SHUTDOWN_SECONDS:
        problems.append(
            f"OR13: the process exited {exited_after:.1f} s after the signal; the graceful bound "
            f"of {GRACEFUL_SHUTDOWN_SECONDS} s was used up waiting for open streams"
        )
    if code not in {0, -signal.SIGTERM}:
        problems.append(f"the process exited with {code}")
    if errors or traces:
        problems.append(f"OR13: shutdown logged errors: {errors + traces}")
    assert not problems, "\n".join(problems) + f"\n--- stderr ---\n{process.stderr_text()}"
