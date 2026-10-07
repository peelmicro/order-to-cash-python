"""A real `uvicorn otc_orders.main:app` process, a real SIGTERM, a request in flight (feature 15,
#8 id 50 and #7's `kill -TERM` evidence).

The lifespan's shutdown drains the responder: the request that is mid-flight when SIGTERM arrives is
still answered (the stand-in Fulfillment holds its reply until after the signal), and the process
then exits 0 having logged its own orderly shutdown. Everything is real: the server process, the
signal handling, NATS, PostgreSQL and Kafka.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import nats
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg

REQUEST = {
    "retailerCode": "RET-01",
    "companyCode": "CMP-01",
    "currency": "EUR",
    "lines": [{"productCode": "SKU-A", "quantity": 3, "unitPrice": 1999, "lineDiscount": 250}],
}


async def test_sigterm_drains_the_request_in_flight_then_the_server_exits_cleanly(
    host_environment: Callable[..., None],
    nats_client: NatsClient,
    nats_server: Any,
    reference_data: Any,
    stock_reply: Callable[..., bytes],
    tmp_path: Path,
) -> None:
    host_environment()
    log_file = tmp_path / "uvicorn.log"
    with log_file.open("w") as log:
        server = subprocess.Popen(  # noqa: ASYNC220 - a blocking spawn that returns at once
            [sys.executable, "-m", "uvicorn", "otc_orders.main:app", "--port", "0"],
            cwd=tmp_path,
            env=os.environ.copy(),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        stand_in_client = await nats.connect(nats_server.url)
        try:
            # booted when the responder answers at all (nobody answers the stock check yet)
            deadline = time.monotonic() + 60
            booted = False
            while time.monotonic() < deadline and not booted:
                assert server.poll() is None, log_file.read_text()
                try:
                    await nats_client.request(
                        "orders.create", json.dumps(REQUEST).encode(), timeout=1
                    )
                    booted = True
                except nats.errors.Error:
                    await asyncio.sleep(0.3)
            assert booted, "the server never answered orders.create:\n" + log_file.read_text()

            entered, release = asyncio.Event(), asyncio.Event()

            async def held_stock_check(message: Msg) -> None:
                entered.set()
                await release.wait()
                await message.respond(stock_reply([("SKU-A", 3, 50)]))

            await stand_in_client.subscribe("fulfillment.stock.check", cb=held_stock_check)
            await stand_in_client.flush()
            in_flight = asyncio.create_task(
                nats_client.request("orders.create", json.dumps(REQUEST).encode(), timeout=30)
            )
            await asyncio.wait_for(entered.wait(), timeout=10)

            server.send_signal(signal.SIGTERM)
            await asyncio.sleep(1.0)
            assert server.poll() is None, "the server must wait for the request in flight"
            assert not in_flight.done()

            release.set()
            reply = json.loads((await asyncio.wait_for(in_flight, timeout=15)).data)
            assert reply["status"] == "placed", reply
            # uvicorn finishes its shutdown, then re-raises the signal to itself so the exit status
            # says SIGTERM (-15); a crash would be another non-zero status or a traceback below.
            assert await asyncio.to_thread(server.wait, 30) in {0, -signal.SIGTERM}
        finally:
            if server.poll() is None:
                server.kill()
                server.wait()
            await stand_in_client.close()

    output = log_file.read_text()
    assert "Application shutdown complete" in output, output
    assert "Traceback" not in output, output
