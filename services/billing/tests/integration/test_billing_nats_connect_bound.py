"""Backlog 214: the boot's NATS connection is bounded (the projector's PR45, for billing).

`nats.connect` with the client's defaults was still connecting after 60 s against an unreachable
broker. A Docker-held port with nothing behind it (the nats image, its entrypoint replaced) accepts
the TCP connection and drops it, as an unreachable broker does; the port is held by Docker, never
picked free and released. The wait is itself bounded, and its failure names the claim.
"""

import asyncio
import time
from typing import Any

import pytest
from testcontainers.core.container import DockerContainer

from otc_billing.composition import load_settings, start_runtime

pytestmark = pytest.mark.integration

NATS_IMAGE = "nats:2.14.5-alpine"  # the compose pin


def leftover_tasks() -> set[asyncio.Task[Any]]:
    return {t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()}


async def test_an_unreachable_nats_fails_the_billing_boot_within_the_bound_naming_nats_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = (
        DockerContainer(NATS_IMAGE)
        .with_exposed_ports(4222)
        .with_kwargs(entrypoint=["sleep", "120"])
    )
    with container:
        url = f"nats://{container.get_container_host_ip()}:{container.get_exposed_port(4222)}"
        monkeypatch.setenv("NATS_URL", url)
        before = leftover_tasks()
        started = time.monotonic()

        async def boot() -> None:
            try:
                async with asyncio.timeout(20):
                    await start_runtime(load_settings(), nats_connect_seconds=2.0)
            except TimeoutError:
                pytest.fail("214: the billing boot did not fail within 20 s against a 2 s bound")

        with pytest.raises(RuntimeError) as refused:
            await boot()
        elapsed = time.monotonic() - started
    assert elapsed < 5.0, f"the billing boot took {elapsed:.1f} s against a 2 s bound"
    assert "NATS_URL" in str(refused.value)
    assert url in str(refused.value)
    assert "2.0 s" in str(refused.value)
    assert leftover_tasks() == before, "a task was left behind by the failed boot"
