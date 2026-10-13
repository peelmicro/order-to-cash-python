# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""Consumption against a real broker: first boot, the offset contract, group identity (SO1, SO9, L23).

SO9 is the one behaviour whose failure mode is silent loss, so it is proven the way #8 id 94 says it
must be: the committed offset is read FROM THE BROKER (an admin call, never inferred from our own
tables), and a failed record is redelivered by a genuinely NEW consumer (the lifespan is stopped and
started again), not by an in-process retry. Failures are injected by replacing `SagaFactHandler.handle`
for ONE event id, so the failure happens inside the real processing path.

Since feature 27 (`R16`) the consumer retries a failing record itself and then DEAD-LETTERS it, so a
processing failure no longer leaves the offset uncommitted: it commits past the record once the dead
letter is durable. The redelivery that survives (and that `OR8` creates) is a dead letter that is NOT
durable, so SO9 is proven with BOTH the handler and the dead-letter publication failing. The two
cases below run on the test's PRIVATE topics (item 10) with a dead-letter producer the test replaces
through the composition root's seam. The old "a poisoned payload is not committed and is retried"
case was retired by `R16` (its claim is now false by requirement); its mutation (validating the
payload in presentation) moved to the Orders dead-letter case.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.fact import SagaFact
from otc_orders.application.saga.fact_handler import SagaFactHandler, SagaFactResult
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]
TOPICS = ("otc.orders.facts.v1", "otc.fulfillment.facts.v1", "otc.billing.facts.v1")


def failing_once_for(
    monkeypatch: pytest.MonkeyPatch,
    event_id: uuid.UUID,
    *,
    until: asyncio.Event | None = None,
    hold: asyncio.Event | None = None,
) -> tuple[asyncio.Event, list[int]]:
    """Make `SagaFactHandler.handle` raise for `event_id`: once (`until=None`), or for as long as
    `until` is unset. With `hold`, the FIRST attempt blocks inside the handler until `hold` is set
    and only then raises (the record is "in flight" meanwhile). Returns (an event set at the first
    failure, the list of attempts)."""
    original = SagaFactHandler.handle
    failed = asyncio.Event()
    attempts: list[int] = []

    async def handle(self: SagaFactHandler, fact: SagaFact) -> SagaFactResult:
        if fact.event_id.value == event_id:
            attempts.append(1)
            if hold is not None and len(attempts) == 1:
                await hold.wait()
            if (until is None and len(attempts) == 1) or (until is not None and not until.is_set()):
                failed.set()
                raise RuntimeError("the injected processing failure")
        return await original(self, fact)

    monkeypatch.setattr(SagaFactHandler, "handle", handle)
    return failed, attempts


class UnreachableDeadLetterProducer:
    """A dead-letter producer whose broker never acknowledges: `send_and_wait` raises, and every
    refused publication is recorded in `refused` (the SUBSCRIBER-level redeliveries the record
    needed, since each refusal ends one round of attempts)."""

    def __init__(self, refused: list[str], **options: Any) -> None:
        self._refused = refused
        self.options = options

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_and_wait(self, topic: str, **record: Any) -> None:
        self._refused.append(topic)
        raise ConnectionError("the dead-letter broker did not acknowledge")


def unreachable(refused: list[str]) -> Callable[..., UnreachableDeadLetterProducer]:
    def factory(**options: Any) -> UnreachableDeadLetterProducer:
        return UnreachableDeadLetterProducer(refused, **options)

    return factory


# a short back-off keeps a record's three attempts inside a test's budget (the default is 500 ms)
FAST_RETRY = {"FACT_RETRY_BACKOFF_MS": "20"}


@pytest.mark.parametrize("topic", TOPICS)
async def test_the_three_fact_topics_exist_with_six_partitions(topic: str, broker: Any) -> None:
    assert len(await broker.partitions_of(topic)) == 6


async def test_so1_first_boot_consumes_a_fact_published_before_the_consumer_group_ever_subscribed(
    saga_harness: Any,
    saga_publisher: Callable[..., Awaitable[uuid.UUID]],
    broker: Any,
    order_at: OrderAt,
    waits: Waits,
) -> None:
    order = await order_at(OrderStatus.PLACED)
    await broker.delete_group()
    assert await broker.committed() == {}, "the group does not exist: no committed offset anywhere"
    await saga_publisher("stock.reserved.v1", correlation_id=order.id.value, reference="ORD-000101")

    async with saga_harness(history="keep") as saga:

        async def hold_exists() -> bool:
            return await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD) is not None

        await waits(
            hold_exists, "the credit.hold row exists: the fact published first was consumed"
        )
        assert await saga.db.status_of(order.id) == "stock_reserved"


async def test_so9_a_fact_whose_dead_letter_is_not_durable_leaves_the_committed_offset_unchanged_and_a_restarted_consumer_redelivers_it(
    saga_harness: Any,
    private_topics: Any,
    broker: Any,
    order_at: OrderAt,
    waits: Waits,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = await order_at(OrderStatus.PLACED)
    baseline_id, fact_id = uuid.uuid4(), uuid.uuid4()
    hold, recovered = asyncio.Event(), asyncio.Event()
    failed, attempts = failing_once_for(monkeypatch, fact_id, until=recovered, hold=hold)
    refused: list[str] = []

    async with saga_harness(
        cleanup=False,
        topics=private_topics,
        dead_letter_producer_factory=unreachable(refused),
        **FAST_RETRY,
    ) as first:
        # A fact of the SAME order and key (so the same partition) is processed and committed first:
        # the committed offset is then a real position, not "nothing", and the failing record is the
        # very next offset of that partition.
        await first.publish_fact(
            "stock.released.v1",
            correlation_id=order.id.value,
            reference="ORD-000101",
            event_id=baseline_id,
        )
        topic, partition, baseline_offset = first.positions[baseline_id]

        async def baseline_committed() -> bool:
            return bool((await broker.committed()).get((topic, partition)) == baseline_offset + 1)

        await waits(baseline_committed, "the baseline fact is processed and its offset committed")
        before = await broker.committed()

        await first.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference="ORD-000101",
            event_id=fact_id,
        )
        assert first.positions[fact_id][:2] == (topic, partition), "the same partition"
        offset = first.positions[fact_id][2]
        assert offset == baseline_offset + 1
        # The record is IN FLIGHT: its handler is running and has not returned. The committed
        # offset must not move while it runs, for longer than aiokafka's auto-commit interval
        # (5 s): a commit before the handler, or an auto-commit of the fetch position, shows here.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 6.5
        try:
            while loop.time() < deadline:
                assert await broker.committed() == before, "the offset moved while the handler ran"
                await asyncio.sleep(0.5)
        finally:
            hold.set()  # now the handler raises (and a failed assertion cannot hang the shutdown)
        await asyncio.wait_for(failed.wait(), timeout=20)

        async def dead_letter_refused() -> bool:
            return len(refused) >= 1

        await waits(
            dead_letter_refused, "the consumer exhausted its attempts and tried to dead-letter"
        )
        await asyncio.sleep(0.5)  # a (wrong) commit would have landed by now
        assert set(refused) == {f"{topic}.dlq"}, (
            "the dead letter goes to the record's own companion"
        )
        assert await broker.committed() == before, "an undelivered dead letter must not commit"
        assert not await first.db.processed(fact_id)
        assert len(attempts) >= 3, "the record was attempted to the maximum before the dead letter"
    # the first lifespan is stopped: its consumer is gone. Nothing may have been committed on exit.
    assert await broker.committed() == before
    attempts_before_the_restart = len(attempts)

    recovered.set()  # the failure clears; the dead-letter broker is back (the real producer)
    async with saga_harness(history="keep", topics=private_topics, **FAST_RETRY) as second:

        async def processed() -> bool:
            return bool(await second.db.processed(fact_id))

        await waits(processed, "a NEW consumer redelivers and processes the fact", seconds=30)

        async def committed_exactly() -> bool:
            return bool((await broker.committed()).get((topic, partition)) == offset + 1)

        await waits(committed_exactly, "the committed offset is exactly the fact's offset + 1")

        assert len(attempts) == attempts_before_the_restart + 1, (
            "the redelivery is ONE more attempt, and it succeeds"
        )
        assert (
            await second.db.fetchval(
                "SELECT count(*) FROM processed_events WHERE event_id = $1", fact_id
            )
            == 1
        )
        assert await second.db.status_of(order.id) == "stock_reserved"
        assert len(second.stand_in(SagaCommandKind.CREDIT_HOLD).requests_for(order.id.value)) == 1


async def test_so9_a_failed_record_is_never_committed_past_while_its_dead_letter_is_not_durable(
    saga_harness: Any,
    private_topics: Any,
    broker: Any,
    order_at: OrderAt,
    waits: Waits,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = await order_at(OrderStatus.PLACED)
    first_id = uuid.uuid4()
    recovered = asyncio.Event()
    _, attempts = failing_once_for(monkeypatch, first_id, until=recovered)
    refused: list[str] = []

    async with saga_harness(
        topics=private_topics, dead_letter_producer_factory=unreachable(refused), **FAST_RETRY
    ) as saga:
        # two facts of ONE order, so one key and one partition, in this order: reserved, then
        # rejected. In order, the rejection finds `stock_reserved` and is ignored; if the failed first
        # fact were skipped the rejection would meet `placed` and CANCEL the order.
        await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference="ORD-000101",
            event_id=first_id,
        )
        second_id = await saga.publish_fact(
            "stock.rejected.v1", correlation_id=order.id.value, reference="ORD-000101"
        )
        topic, partition, first_offset = saga.positions[first_id]
        assert saga.positions[second_id][:2] == (topic, partition), "the same partition"
        assert saga.positions[second_id][2] == first_offset + 1

        samples: list[int] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 60
        while len(refused) < 3:  # the subscriber delivered the record and redelivered it twice more
            assert loop.time() < deadline, (
                f"only {len(refused)} refused dead letters in 60 s ({len(attempts)} attempts)"
            )
            samples.append((await broker.committed()).get((topic, partition), -1))
            await asyncio.sleep(0.3)
        samples.append((await broker.committed()).get((topic, partition), -1))
        assert len(attempts) >= 9, "three rounds of three attempts each"
        assert max(samples) <= first_offset, (
            f"the committed offset {max(samples)} passed the failed record at {first_offset}: "
            f"samples={samples}"
        )
        assert not await saga.db.processed(second_id), "the later record waits for the failed one"
        assert await saga.db.status_of(order.id) == "placed"

        recovered.set()

        async def both_processed() -> bool:
            return bool(await saga.db.processed(first_id) and await saga.db.processed(second_id))

        await waits(
            both_processed, "after the failure clears both records are processed", seconds=30
        )

        assert await saga.db.status_of(order.id) == "stock_reserved", "processed in partition order"
        assert [r["event_id"] for r in await saga.db.ignored(order.id, "stock.rejected.v1")] == [
            second_id
        ]

        async def committed_past_both() -> bool:
            return bool((await broker.committed()).get((topic, partition)) == first_offset + 2)

        await waits(committed_past_both, "the committed offset covers both records")


async def test_the_consumer_group_on_the_broker_is_named_orders_saga(
    saga_harness: Any, broker: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        fact_id = await saga.publish_fact(
            "stock.reserved.v1", correlation_id=order.id.value, reference="ORD-000101"
        )
        topic, partition, offset = saga.positions[fact_id]

        async def processed() -> bool:
            return bool(await saga.db.processed(fact_id))

        await waits(processed, "the fact is processed (by whichever group consumed it)", seconds=60)

        groups = await broker.group_ids()
        assert "orders.saga" in groups, f"groups on the broker: {sorted(groups)}"
        assert {g for g in groups if g.startswith("orders")} == {"orders.saga"}, (
            f"the group on the broker must be named exactly orders.saga: {sorted(groups)} (#7 D5)"
        )

        async def committed() -> bool:
            return bool((await broker.committed()).get((topic, partition)) == offset + 1)

        await waits(committed, "the group's committed offset is the fact's offset + 1")


async def test_a_fact_stamped_with_a_non_utc_offset_advances_the_order_and_stamps_the_utc_millisecond(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference="ORD-000101",
            raw={"occurredAt": "2026-10-02T12:15:04.120456+02:00"},
        )

        async def advanced() -> bool:
            return await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD) is not None

        await waits(advanced, "the fact advances the order (the credit.hold row exists)")

        assert await saga.db.status_of(order.id) == "stock_reserved"
        assert await saga.db.fetchval(
            "SELECT updated_at FROM orders WHERE id = $1", order.id.value
        ) == datetime(2026, 10, 2, 10, 15, 4, 120000, tzinfo=UTC)


async def test_the_correlation_id_is_compared_as_a_uuid_value(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference="ORD-000101",
            raw={"correlationId": str(order.id.value).upper()},
        )

        async def advanced() -> bool:
            return await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD) is not None

        await waits(advanced, "the upper-case correlationId still routes to the order")

        assert await saga.db.status_of(order.id) == "stock_reserved"
        assert await saga.db.ignored(order.id) == []
