"""Acceptance item 3, second half: `GATEWAY_PORT` is honoured (#8 id 96: a Gateway that ignored it
and listened wherever the framework's default put it, so the web app and the manual-test recipe
reached nothing).

A REAL process: `python -m otc_gateway` with the environment a deployment would carry, over a real
MongoDB and a real NATS. The claim is about an actual bind, so what is checked is the socket: the
configured port answers `GET /health/live` from outside the process, and the process's own log names
it. A sibling-port substitution is the arm: the same process started with the OTHER port answers
there and NOT on the first (nothing else listens on either, asserted before each start).

The two ports are literals in the 38400s, not picked free and released: if something else holds one
the test fails at the pre-check with that port named, never silently on a stale answer. A process
stopped with SIGTERM exits through uvicorn's orderly shutdown (no traceback, "Application shutdown
complete"), and the lifespan closes its connections (the NATS client's drain is the log line).
Loop scope: function.
"""

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration

PORTS = (38417, 38418)
OPERATOR_PASSWORD = "port-test-operator-password"


def text_of(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def something_listens(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


async def wait_for_live(port: int, process: subprocess.Popen[bytes], log: Path) -> None:
    """Bounded by a deadline and PACED: one attempt per 0.3 s, whatever the attempt answered (a
    refused connection, a 503 or a timeout), proved by counting (CLAUDE.md "Retry loops")."""
    started = time.monotonic()
    deadline = started + 60
    attempts = 0
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.monotonic() < deadline:
            assert process.poll() is None, f"the Gateway exited early:\n{text_of(log)}"
            attempts += 1
            try:
                response = await client.get(f"http://127.0.0.1:{port}/health/live")
                if response.status_code == 200:
                    elapsed = time.monotonic() - started
                    assert attempts <= elapsed / 0.3 + 2, (
                        f"{attempts} attempts in {elapsed:.2f} s is not paced at 0.3 s"
                    )
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.3)
    raise AssertionError(f"nothing answered on port {port} within 60 s:\n{text_of(log)}")


@pytest.mark.parametrize(("configured", "other"), [(PORTS[0], PORTS[1]), (PORTS[1], PORTS[0])])
async def test_the_process_listens_on_gateway_port_and_nowhere_else(
    configured: int,
    other: int,
    nats_server: Any,
    fresh_mongo_database: Any,
    tmp_path: Path,
) -> None:
    for port in PORTS:
        assert not something_listens(port), f"port {port} is already in use: free it and re-run"
    log_file = tmp_path / "gateway.log"
    environment = {
        **os.environ,
        "GATEWAY_PORT": str(configured),
        "GATEWAY_HOST": "127.0.0.1",
        "NATS_URL": nats_server.url,
        "MONGO_URI": fresh_mongo_database.uri,
        "MONGO_DB_READMODEL": fresh_mongo_database.name,
        "JWT_SECRET": "port-test-jwt-secret-0123456789abcdef-0123456789",
        "GATEWAY_OPERATOR_PASSWORD": OPERATOR_PASSWORD,
        "GATEWAY_LOGIN_RATE_LIMIT": "2",
    }
    with log_file.open("w") as log:
        process = subprocess.Popen(  # noqa: ASYNC220 - a blocking spawn that returns at once
            [sys.executable, "-m", "otc_gateway"],
            cwd=tmp_path,  # an empty directory: no `.env` can supply a value
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            await wait_for_live(configured, process, log_file)

            assert something_listens(configured)
            assert not something_listens(other), f"the process also listens on {other}"
            assert not something_listens(8000), "the process listens on uvicorn's default port"
            async with httpx.AsyncClient(timeout=5.0) as client:
                base = f"http://127.0.0.1:{configured}"
                ready = await client.get(f"{base}/health/ready")
                assert ready.status_code == 200, ready.text
                login = await client.post(
                    f"{base}/auth/login",
                    json={"username": "operator", "password": OPERATOR_PASSWORD},
                )
                assert login.status_code == 200
                # R63 over the real socket: the second attempt is a 401, the third is a 429
                wrong = await client.post(
                    f"{base}/auth/login", json={"username": "operator", "password": "wrong"}
                )
                refused = await client.post(
                    f"{base}/auth/login",
                    json={"username": "operator", "password": OPERATOR_PASSWORD},
                )
                assert wrong.status_code == 401
                assert refused.status_code == 429
                assert refused.headers["content-type"] == "application/problem+json"
                assert refused.headers["retry-after"].isdigit()
                assert "accessToken" not in refused.text
                token = login.json()["accessToken"]
                me = await client.get(
                    f"{base}/auth/me", headers={"Authorization": f"Bearer {token}"}
                )
                assert me.status_code == 200  # the limit is the login route's alone
            process.send_signal(signal.SIGTERM)
            assert await asyncio.to_thread(process.wait, 30) in {0, -signal.SIGTERM}
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    output = text_of(log_file)
    assert f"Uvicorn running on http://127.0.0.1:{configured}" in output, output
    assert f"{other}" not in output.replace(str(configured), ""), output
    assert "Application shutdown complete" in output, output
    assert "Traceback" not in output, output
    assert not something_listens(configured)


def test_without_gateway_port_the_process_listens_on_3001_the_documented_default() -> None:
    """Not a bind (3001 is often taken on this machine): the default is the settings' value, which
    `test_gateway_settings_env.py` pins, and the entry point passes exactly that to
    `uvicorn.Config`."""
    import ast

    from otc_gateway import __main__ as entry

    tree = ast.parse(text_of(Path(entry.__file__)))
    run = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Config"
    )
    keywords = {k.arg: ast.unparse(k.value) for k in run.keywords}

    # `timeout_graceful_shutdown` is feature 26's: an open event stream never ends by itself
    assert keywords == {
        "host": "server.host",
        "port": "server.port",
        "timeout_graceful_shutdown": "GRACEFUL_SHUTDOWN_SECONDS",
        "log_config": "None",  # OR13: uvicorn's LOGGING_CONFIG must not replace the JSON handler
    }
