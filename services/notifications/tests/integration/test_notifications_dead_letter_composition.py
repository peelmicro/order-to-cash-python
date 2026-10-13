"""`R16` (S4.5): the dead-letter producer of the REAL Notifications composition.

The real `start_runtime` over the Docker-held Kafka, Mailpit and PostgreSQL. The consumer reads the
test's PRIVATE topics (item 10) through the composition root's test seam.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from aiokafka import AIOKafkaProducer

from otc_notifications.composition import DEAD_LETTER_CLIENT_ID, load_settings, start_runtime
from otc_notifications.infrastructure.messaging import dead_letter_publisher

pytestmark = pytest.mark.integration

SUPPORT = Path(__file__).resolve().parents[4] / "tests/observability/dead_letter_support.py"


def load_support() -> ModuleType:
    """`tests/observability/dead_letter_support.py`, loaded by path (importlib mode)."""
    name = "dead_letter_support"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SUPPORT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


async def test_or8_the_dead_letter_producer_uses_the_configured_brokers_and_its_own_client_id(
    notifications_host_factory: Any,
    private_topics: Any,
    kafka_server: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The producer has no bootstrap setting of its own that could default to `localhost:9092`
    (#8 id 104). The recording subclass fails inside the constructor, so a wrong address names the
    claim instead of failing as a connection error."""
    captured: list[dict[str, Any]] = []

    class Recording(AIOKafkaProducer):  # type: ignore[misc]
        def __init__(self, **kwargs: Any) -> None:
            captured.append(kwargs)
            assert kwargs["bootstrap_servers"] == kafka_server.bootstrap_servers, (
                "the dead-letter producer must connect to the configured KAFKA_BROKERS, "
                f"not {kwargs['bootstrap_servers']!r}"
            )
            super().__init__(**kwargs)

    monkeypatch.setattr(dead_letter_publisher, "AIOKafkaProducer", Recording)

    async with notifications_host_factory(
        NOTIFICATIONS_SENDER="console", topics=private_topics
    ) as host:
        assert [r for r in await host.runtime.readiness() if not r.up] == []

    [options] = captured
    assert options["client_id"] == DEAD_LETTER_CLIENT_ID == "otc-notifications-dlq"
    assert (options["acks"], options["enable_idempotence"]) == ("all", True)


def test_or8_the_runtime_starts_and_stops_in_two_successive_event_loops(
    host_environment: Any, kafka_server: Any
) -> None:
    """Ledger L13: the dead-letter producer, like the consumer, is created in the loop that runs the
    lifespan and closed in it; a second `asyncio.run` builds both anew."""
    support = load_support()
    topics = asyncio.run(support.create_private_topics(kafka_server.bootstrap_servers, "loops"))
    host_environment(NOTIFICATIONS_SENDER="console")

    async def once() -> tuple[list[str], list[str]]:
        async with asyncio.timeout(60):
            runtime = await start_runtime(load_settings(), fact_topics=topics.all)
            try:
                reasons = [r.name for r in await runtime.readiness() if not r.up]
                names = sorted(runtime.tasks)
            finally:
                await runtime.stop()
        return reasons, names

    assert asyncio.run(once()) == ([], ["fact-consumer"])
    assert asyncio.run(once()) == ([], ["fact-consumer"])
