"""`python -m otc_gateway`: run the Gateway on the configured `GATEWAY_PORT` (#8 id 96).

`uvicorn otc_gateway.main:app` takes its port from its own `--port` (8000 by default) and cannot
know a setting of this service; this entry point reads `GATEWAY_HOST` / `GATEWAY_PORT` through the
composition root's settings and hands them to uvicorn, so the port the process listens on is the one
configured. One worker: the login limit and the issued-order window are per process.

Open streams at shutdown (`OR13`): an open `GET /orders/stream` never ends by itself, and uvicorn
waits for every open response before it runs the lifespan's shutdown. So this entry point runs a
`GatewayServer`, whose `handle_exit` (the SIGINT / SIGTERM handler) ends every open subscription of
the stream hub on the event loop; each stream finishes its body and returns, uvicorn finds nothing
left to wait for, and the process exits without the "Cancel N running task(s)" ERROR line or one
traceback per stream. `timeout_graceful_shutdown` stays as the bound for anything else that is
slow to finish. The app OBJECT (not an import string) is handed to `uvicorn.Config` so the subclass
can reach the runtime's hub. `log_config=None`: `uvicorn.Config.__init__` would otherwise re-apply
its own `LOGGING_CONFIG` over the JSON handler `main.py` installed at import (R58).

The by-hand path, `uvicorn otc_gateway.main:app`, has no such hook: an exit signal waits the
`--timeout-graceful-shutdown` bound (none by default, so it hangs behind the first open stream
unless one is given) and then cancels the streams, logging them at ERROR. Use
`python -m otc_gateway`.
"""

import asyncio
import socket
from collections.abc import Callable
from types import FrameType

import uvicorn

from otc_gateway.application.stream.hub import StreamHub
from otc_gateway.composition import load_settings

GRACEFUL_SHUTDOWN_SECONDS = 5


class GatewayServer(uvicorn.Server):
    """`uvicorn.Server` that ends every open event stream when the exit signal arrives."""

    def __init__(self, config: uvicorn.Config, hub: Callable[[], StreamHub | None]) -> None:
        super().__init__(config)
        self._hub = hub
        self._loop: asyncio.AbstractEventLoop | None = None

    async def serve(self, sockets: list[socket.socket] | None = None) -> None:
        self._loop = asyncio.get_running_loop()
        await super().serve(sockets)

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        super().handle_exit(sig, frame)
        hub = self._hub()
        if hub is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(hub.end_all)


def main() -> None:
    from otc_gateway.main import app  # imported here: it installs the JSON log handler

    def hub() -> StreamHub | None:
        runtime = getattr(app.state, "runtime", None)
        return None if runtime is None else runtime.stream_hub

    server = load_settings().server
    config = uvicorn.Config(
        app,
        host=server.host,
        port=server.port,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
        log_config=None,
    )
    GatewayServer(config, hub).run()


if __name__ == "__main__":
    main()
