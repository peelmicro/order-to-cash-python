"""Entry 218: `booted` means the socket accepts, not that uvicorn's lifespan finished.

A real uvicorn child: the lifespan line precedes the listening line, `booted` matches only the
listening line, and a connect succeeds once `booted` has matched. (The gap between the two lines
is microseconds, so the race itself cannot be observed deterministically; the predicate is.)
"""

import asyncio
import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import ModuleType

SUPPORT_PATH = Path(__file__).resolve().parent / "log_contract_support.py"


def _support() -> ModuleType:
    spec = importlib.util.spec_from_file_location("log_contract_support", SUPPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


support = _support()

APP = """
import asyncio
import json
import logging

class JsonFmt(logging.Formatter):
    def format(self, record):
        return json.dumps({"logger": record.name, "event": record.getMessage()})

async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            m = await receive()
            if m["type"] == "lifespan.startup":
                await asyncio.sleep(1.5)
                await send({"type": "lifespan.startup.complete"})
            else:
                await send({"type": "lifespan.shutdown.complete"})
                return
"""


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def test_n218_booted_matches_only_once_the_socket_accepts_and_startup_complete_comes_first(
    tmp_path: Path,
) -> None:
    (tmp_path / "slowapp.py").write_text(APP)
    (tmp_path / "log.json").write_text(
        json.dumps(
            {
                "version": 1,
                "formatters": {"j": {"()": "slowapp.JsonFmt"}},
                "handlers": {"h": {"class": "logging.StreamHandler", "formatter": "j"}},
                "loggers": {"uvicorn.error": {"handlers": ["h"], "level": "INFO"}},
            }
        )
    )
    port = _free_port()
    process = support.spawn(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "slowapp:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-config",
            "log.json",
        ],
        cwd=tmp_path,
        tmp_path=tmp_path,
        name="slow",
    )
    try:
        lifespan = await support.wait_for_event(
            process, "the lifespan line", support.startup_complete
        )
        listening = await support.wait_for_event(process, "the listening line", support.booted)
        # `booted` is the line logged after the bind, and is not the lifespan line
        assert not support.booted(lifespan), "booted matches the lifespan line: it races the bind"
        assert support.startup_complete(lifespan)
        assert not support.startup_complete(listening)
        lines = [ln for ln in process.stderr_text().split("\n") if ln.strip()]
        assert lines.index(json.dumps(lifespan)) < lines.index(json.dumps(listening))
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
    finally:
        support.kill(process)
