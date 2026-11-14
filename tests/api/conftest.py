"""Feature 31 fixtures: the black-box API suite.

The fleet is `tests/saga_e2e/conftest.py`'s `fleet` fixture, loaded BY PATH (importlib mode: test
directories are not packages) and re-exported here, not copied: ONE composed fleet per test, every
service through its own `create_app()` and real lifespan over the root session's testcontainers.

What this suite adds is the way in. `fleet.http` reaches the Gateway in-process over
`httpx.ASGITransport`; the `api` fixture serves the SAME Gateway app (the fleet's lifespan already
ran: `lifespan="off"`) on a real uvicorn socket and drives it with `httpx` over TCP. That adds what
an in-process call cannot show: the bytes on the wire (h11 framing, header casing, the
`Content-Type` of a problem), and the app's middleware stack behind a real server.

Loop scope: `api` is `loop_scope="function"`, written next to it; the server task, the socket and
the client are created in the test's loop and closed in it, BEFORE the fleet's own teardown (the
fixture depends on `fleet`, so pytest tears it down first). Each test boots its OWN fleet and the
previous one is fully torn down first: #8's shared-fleet regression (two fleets alive at once, five
timeouts) cannot happen by construction.
"""

import asyncio
import importlib.util
import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest_asyncio
import uvicorn

HERE = Path(__file__).resolve().parent
SERVE_SECONDS = 20.0


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_fleet_module = _load("saga_e2e_fleet", HERE.parent / "saga_e2e" / "conftest.py")
api_support = _load("api_support", HERE / "api_support.py")
fleet = _fleet_module.fleet  # the same fixture function: ONE definition of the fleet
OPERATOR_PASSWORD: str = _fleet_module.OPERATOR_PASSWORD


@pytest_asyncio.fixture(loop_scope="function")  # server task, socket and client: this test's loop
async def api(fleet: Any) -> AsyncIterator[Any]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))  # held by this fixture until teardown: never picked and released
    host, port = sock.getsockname()
    server = uvicorn.Server(
        uvicorn.Config(
            fleet.gateway, log_level="warning", lifespan="off", timeout_graceful_shutdown=2
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(SERVE_SECONDS):
            while not server.started:
                if task.done():
                    task.result()
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}", timeout=30.0) as client:
            login = await client.post(
                "/auth/login", json={"username": "operator", "password": OPERATOR_PASSWORD}
            )
            assert login.status_code == 200, login.text
            client.headers["Authorization"] = f"Bearer {login.json()['accessToken']}"
            yield api_support.BlackBox(client, fleet, OPERATOR_PASSWORD)
    finally:
        server.should_exit = True
        try:
            async with asyncio.timeout(SERVE_SECONDS):
                await asyncio.wait({task})
        finally:
            sock.close()
