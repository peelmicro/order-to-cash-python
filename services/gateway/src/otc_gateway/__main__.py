"""`python -m otc_gateway`: run the Gateway on the configured `GATEWAY_PORT` (#8 id 96).

`uvicorn otc_gateway.main:app` takes its port from its own `--port` (8000 by default) and cannot
know a setting of this service; this entry point reads `GATEWAY_HOST` / `GATEWAY_PORT` through the
composition root's settings and hands them to uvicorn, so the port the process listens on is the one
configured. One worker: the login limit and the issued-order window are per process.

`timeout_graceful_shutdown`: an open `GET /orders/stream` never ends by itself, and uvicorn waits
for
every open response before it runs the lifespan's shutdown; without a bound a stop signal would hang
behind the first browser tab. After the bound the stream is cancelled (its subscription released in
`EventStreamResponse`'s `finally`) and the shutdown proceeds.
"""

import uvicorn

from otc_gateway.composition import load_settings

GRACEFUL_SHUTDOWN_SECONDS = 5


def main() -> None:
    server = load_settings().server
    uvicorn.run(
        "otc_gateway.main:app",
        host=server.host,
        port=server.port,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )


if __name__ == "__main__":
    main()
