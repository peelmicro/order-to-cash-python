"""I2 (PR5, PR38): the options the runtime passes to the consumer, on the dict
`consumer_options()` returns AND on the kwargs a recording `consumer_factory` received when `run`
built the consumer: `earliest` (aiokafka's default is `latest`), `enable_auto_commit` False (its
default is True), the group equal to the ledger's consumer name, the client id, the three topics.
"""

import asyncio
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest

from otc_projector.application.ports.fact_stream import FactMessage
from otc_projector.infrastructure.messaging.consumer_name import ConsumerName
from otc_projector.infrastructure.messaging.fact_retry import FactRetryStopped
from otc_projector.infrastructure.messaging.fact_topics import PROJECTOR_FACT_TOPICS
from otc_projector.infrastructure.messaging.kafka_fact_subscriber import KafkaFactSubscriber
from otc_projector.infrastructure.settings import KafkaSettings


class RecordingConsumer:
    created: ClassVar[list[tuple[tuple[Any, ...], dict[str, Any]]]] = []

    def __init__(self, *topics: str, **kwargs: Any) -> None:
        RecordingConsumer.created.append((topics, kwargs))

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def assignment(self) -> list[tuple[str, int]]:
        return []

    async def position(self, partition: tuple[str, int]) -> int:
        return 0

    async def getmany(self, *, timeout_ms: int, max_records: int) -> dict[Any, Any]:
        return {}

    def seek(self, partition: tuple[str, int], offset: int) -> None:
        return None

    async def commit(self, offsets: dict[Any, int]) -> None:
        return None


@pytest.fixture
def default_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> KafkaSettings:
    monkeypatch.chdir(tmp_path)
    for name in ("KAFKA_BROKERS", "PROJECTOR_KAFKA_CLIENT_ID", "PROJECTOR_CONSUMER_GROUP"):
        monkeypatch.delenv(name, raising=False)
    return KafkaSettings()


EXPECTED = {
    "bootstrap_servers": "localhost:9092",
    "group_id": "projector",
    "client_id": "otc-projector",
    "enable_auto_commit": False,
    "max_poll_interval_ms": 300000,  # aiokafka default, now written down
    "auto_offset_reset": "earliest",
}


def test_pr38_the_options_the_runtime_passes_are_earliest_projector_group_client_id_and_no_auto_commit(  # noqa: E501
    default_settings: KafkaSettings,
) -> None:
    subscriber = KafkaFactSubscriber(default_settings)
    options = subscriber.consumer_options()
    assert options == EXPECTED, options
    assert options["auto_offset_reset"] == "earliest", "a new group must start at the beginning"
    assert options["enable_auto_commit"] is False
    assert options["group_id"] == ConsumerName.PROJECTOR.value
    assert options["client_id"] == "otc-projector"


async def test_pr38_the_kwargs_the_consumer_factory_received_when_run_built_the_consumer(
    default_settings: KafkaSettings,
) -> None:
    RecordingConsumer.created.clear()
    stop = asyncio.Event()
    stop.set()  # one pass: build, start, resolve positions, stop
    subscriber = KafkaFactSubscriber(
        default_settings,
        consumer_factory=cast("Callable[..., Any]", RecordingConsumer),
        poll_ms=1,
    )

    async def handler(message: FactMessage) -> None:
        raise AssertionError("no record was delivered")

    await subscriber.run(handler, stop)
    assert len(RecordingConsumer.created) == 1, "run must build exactly one consumer"
    topics, kwargs = RecordingConsumer.created[0]
    assert topics == PROJECTOR_FACT_TOPICS
    assert kwargs == EXPECTED, kwargs
    assert kwargs["auto_offset_reset"] == "earliest"
    assert kwargs["enable_auto_commit"] is False


class OneRecordConsumer:
    """Hands out ONE record, then nothing; records every commit and seek."""

    def __init__(self) -> None:
        self.commits: list[dict[Any, int]] = []
        self.seeks: list[tuple[Any, int]] = []
        self._handed = False

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def assignment(self) -> list[tuple[str, int]]:
        return []

    async def position(self, partition: tuple[str, int]) -> int:
        return 0

    async def getmany(self, *, timeout_ms: int, max_records: int) -> dict[Any, Any]:
        if self._handed:
            await asyncio.sleep(0)
            return {}
        self._handed = True
        record = SimpleNamespace(
            topic="otc.orders.facts.v1", partition=2, offset=5, key=b"k", value=b"{}", headers=()
        )
        return {("otc.orders.facts.v1", 2): [record]}

    def seek(self, partition: Any, offset: int) -> None:
        self.seeks.append((partition, offset))

    async def commit(self, offsets: dict[Any, int]) -> None:
        self.commits.append(dict(offsets))


async def test_f1_a_retry_interrupted_by_shutdown_is_not_committed_not_sought_and_not_a_handler_failure(  # noqa: E501
    default_settings: KafkaSettings, caplog: pytest.LogCaptureFixture
) -> None:
    """The stop signal ended the retry back-off (`FactRetryStopped`): the record stays uncommitted
    (redelivered after the restart), nothing is sought, and the line is NOT the failure line."""
    consumer = OneRecordConsumer()
    stop = asyncio.Event()
    paced: list[float] = []

    async def sleep(seconds: float) -> None:
        paced.append(seconds)

    subscriber = KafkaFactSubscriber(
        default_settings,
        consumer_factory=cast("Callable[..., Any]", lambda *topics, **options: consumer),
        sleep=sleep,
        poll_ms=1,
    )

    async def handler(message: FactMessage) -> None:
        stop.set()
        raise FactRetryStopped

    with caplog.at_level(logging.INFO):
        await subscriber.run(handler, stop)

    assert consumer.commits == [], "the record is NOT committed"
    assert consumer.seeks == [], "no seek: this is not a failure of the record"
    assert paced == [], "no pacing"
    lines = [record.getMessage() for record in caplog.records]
    assert not any(line.startswith("fact handler failed") for line in lines), lines
    assert any(line.startswith("fact retry interrupted by shutdown") for line in lines), lines
