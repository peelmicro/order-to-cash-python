"""`KafkaDeadLetterPublisher`: the dead-letter record, written to `<source topic>.dlq` (`R16`).

Canonical in Orders; copied to the Projector and Notifications (`OR2`,
`tests/architecture/test_observability_copy_parity.py` fails on any difference after this
docstring, so edit here and copy). Design: `specs/observability_reliability/design.md` 5.4.

* ONE `AIOKafkaProducer` per service, built and started inside the lifespan's loop (`start()`) and
  stopped by it (`stop()`); an aiokafka client binds to the loop that creates it, so nothing is
  built in `__init__`. It connects to the service's OWN `KafkaSettings.brokers`: there is no second
  bootstrap setting that could default to `localhost` (#8 id 104). `acks="all"` and
  `enable_idempotence=True`: `send_and_wait` returns only after the broker's acknowledgement, which
  is the durability `OR8` waits for.
* The topic is `f"{source_topic}.dlq"`, the key is the ORIGINAL record key (the correlation id;
  `asyncapi.yaml` `DeadLetterRecord` keys by `UniqueId`; #8 keyed by event type) and the value is
  the ORIGINAL bytes, never a re-serialised envelope, so a redrive is a byte-for-byte republish.
* Headers, all UTF-8 bytes: `x-failed-consumer`, `x-attempts` (decimal), `x-error` (cut to 1 000
  characters, no traceback), `x-original-topic`, `x-first-failed-at` and `x-failed-at` (both
  `YYYY-MM-DDTHH:MM:SS.mmmZ` through `format_instant`, never `isoformat()`), `x-event-type`,
  `content-type` and, when a valid span is current, `traceparent`. The original record's own headers
  are NOT copied (its `traceparent` would collide with the dead letter's).
* A missing `.dlq` topic (the broker does not create topics; `kafka-init` creates the companions)
  fails `send_and_wait` with `UnknownTopicOrPartitionError` after `request_timeout_ms` (measured:
  40 s with aiokafka's default, so 10 s here): the failure is `OR8`'s path (no commit, redelivery).
"""

import contextlib
from collections.abc import Callable
from typing import Protocol

from aiokafka import AIOKafkaProducer

from otc_contracts import format_instant
from otc_orders.infrastructure.messaging.fact_retry import DeadLetter
from otc_orders.infrastructure.observability.trace_context import current_traceparent
from otc_orders.infrastructure.settings import KafkaSettings

DEAD_LETTER_SUFFIX = ".dlq"
ERROR_LIMIT = 1000
REQUEST_TIMEOUT_MS = 10_000


class _Producer(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_and_wait(
        self, topic: str, *, value: bytes, key: bytes | None, headers: list[tuple[str, bytes]]
    ) -> object: ...


type ProducerFactory = Callable[..., _Producer]


def dead_letter_headers(letter: DeadLetter) -> list[tuple[str, bytes]]:
    headers = [
        ("x-failed-consumer", letter.consumer.encode("utf-8")),
        ("x-attempts", str(letter.attempts).encode("utf-8")),
        ("x-error", letter.error[:ERROR_LIMIT].encode("utf-8")),
        ("x-original-topic", letter.source_topic.encode("utf-8")),
        ("x-first-failed-at", format_instant(letter.first_failed_at).encode("utf-8")),
        ("x-failed-at", format_instant(letter.failed_at).encode("utf-8")),
        ("x-event-type", letter.event_type.encode("utf-8")),
        ("content-type", b"application/json"),
    ]
    traceparent = current_traceparent()
    if traceparent is not None:
        headers.append(("traceparent", traceparent.encode("utf-8")))
    return headers


class KafkaDeadLetterPublisher:
    def __init__(
        self,
        settings: KafkaSettings,
        *,
        client_id: str,
        producer_factory: ProducerFactory | None = None,
        request_timeout_ms: int = REQUEST_TIMEOUT_MS,
    ) -> None:
        self._settings = settings
        self._client_id = client_id
        self._producer_factory: ProducerFactory = (
            AIOKafkaProducer if producer_factory is None else producer_factory
        )
        self._request_timeout_ms = request_timeout_ms
        self._producer: _Producer | None = None

    def producer_options(self) -> dict[str, object]:
        return {
            "bootstrap_servers": self._settings.brokers,
            "client_id": self._client_id,
            "acks": "all",
            "enable_idempotence": True,
            "request_timeout_ms": self._request_timeout_ms,
        }

    async def start(self) -> None:
        producer = self._producer_factory(**self.producer_options())
        try:
            await producer.start()
        except BaseException:
            # A producer whose start() raised still holds its client; close it, then re-raise.
            with contextlib.suppress(Exception):
                await producer.stop()
            raise
        self._producer = producer

    async def stop(self) -> None:
        producer, self._producer = self._producer, None
        if producer is not None:
            await producer.stop()

    async def publish(self, letter: DeadLetter) -> None:
        producer = self._producer
        if producer is None:
            raise RuntimeError("the dead-letter producer is not started")
        await producer.send_and_wait(
            f"{letter.source_topic}{DEAD_LETTER_SUFFIX}",
            key=letter.key,
            value=letter.value,
            headers=dead_letter_headers(letter),
        )
