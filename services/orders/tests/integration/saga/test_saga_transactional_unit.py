# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""One transaction for a step, and the fast path signalled only after its commit (SO3; 7.6, 7.7).

PostgreSQL only. The REAL `SagaFactHandler` and `SagaFactCommandHandler` run over the real unit of
work and the real canonical idempotent consumer; the faults and the probes are injected around them.
"""

import asyncio
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast

import asyncpg
import pytest

from otc_contracts import Envelope, from_wire_json
from otc_contracts.generated.asyncapi import CreditApprovedPayload
from otc_orders.application.ports.saga_signal import SagaCommandRef
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.fact import SagaFact
from otc_orders.application.saga.fact_command_handlers import SagaFactCommandHandler
from otc_orders.application.saga.fact_commands import HandleCreditApprovedFactCommand
from otc_orders.application.saga.fact_handler import SagaFactHandler
from otc_orders.application.scope import OrdersScope
from otc_orders.composition import build_dispatcher
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.clock import SystemClock
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_orders.infrastructure.saga.command_queue import SqlAlchemySagaCommandQueue
from otc_orders.infrastructure.saga.fact_consumption import SqlAlchemyFactConsumption
from otc_shared_kernel import UniqueId

NOW = datetime(2026, 10, 7, 12, 0, 0, 123000, tzinfo=UTC)


def credit_approved(order: Order) -> SagaFact:
    return SagaFact(
        event_id=UniqueId(uuid.uuid4()),
        event_type="credit.approved.v1",
        correlation_id=order.id,
        occurred_at=NOW,
        payload=CreditApprovedPayload(
            order_reference=order.order_reference.value,
            retailer_code="RET-01",
            company_code="CMP-01",
            credit_code="CR-000001",
            currency="EUR",
            held_amount=8115,
            available_credit_after=91885,
        ),
        topic="otc.billing.facts.v1",
    )


async def test_so3_the_owed_command_row_commits_and_rolls_back_with_the_status_change(
    uow: SqlAlchemyUnitOfWork,
    clock: SystemClock,
    order_at: Callable[..., Any],
    db: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    fact = credit_approved(order)
    original = SqlAlchemySagaCommandQueue.enqueue

    async def enqueue_then_fail(self: SqlAlchemySagaCommandQueue, command: Any) -> Any:
        await original(self, command)  # the row IS written inside the transaction...
        raise RuntimeError("a failure injected after the enqueue, inside work")

    monkeypatch.setattr(SqlAlchemySagaCommandQueue, "enqueue", enqueue_then_fail)

    with pytest.raises(RuntimeError, match="after the enqueue"):
        await SagaFactHandler(SqlAlchemyFactConsumption(uow, clock)).handle(fact)

    # ...and every effect of the step is gone with it
    assert await db.command_rows(order.id) == [], "no saga_commands row"
    assert await db.status_of(order.id) == "stock_reserved", "no status change"
    assert await db.outbox_types(order.id) == [], "no outbox row (confirm had raised one)"
    assert not await db.processed(fact.event_id.value), "no processed_events row: it is redelivered"


async def test_so3_a_step_that_succeeds_commits_all_four_effects_together(
    uow: SqlAlchemyUnitOfWork, clock: SystemClock, order_at: Callable[..., Any], db: Any
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    fact = credit_approved(order)

    result = await SagaFactHandler(SqlAlchemyFactConsumption(uow, clock)).handle(fact)

    assert result.enqueued is SagaCommandKind.DESPATCH_CREATE
    assert [r["command"] for r in await db.command_rows(order.id)] == ["despatch.create"]
    assert await db.status_of(order.id) == "confirmed"
    assert await db.outbox_types(order.id) == ["order.confirmed.v1"]
    assert await db.processed(fact.event_id.value)


class SeparateSession:
    """A second event loop on a second thread with its OWN database connection, so a check can run
    while the first loop is blocked inside `signal`: what a session that is not part of the fact's
    transaction can see at that instant."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._connection: asyncpg.Connection[asyncpg.Record] | None = None

    def start(self) -> None:
        self._thread.start()
        self._connection = asyncio.run_coroutine_threadsafe(
            asyncpg.connect(self._dsn), self._loop
        ).result(timeout=10)

    def stop(self) -> None:
        assert self._connection is not None
        asyncio.run_coroutine_threadsafe(self._connection.close(), self._loop).result(timeout=10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)
        self._loop.close()

    def command_row_visible(self, order_id: uuid.UUID, kind: SagaCommandKind) -> bool:
        assert self._connection is not None
        count = asyncio.run_coroutine_threadsafe(
            self._connection.fetchval(
                "SELECT count(*) FROM saga_commands WHERE order_id = $1 AND command = $2",
                order_id,
                kind.value,
            ),
            self._loop,
        ).result(timeout=10)
        return bool(count == 1)


class RecordingUnitOfWork:
    """The real unit of work, recording when each transaction begins and when its commit returned."""

    def __init__(self, inner: SqlAlchemyUnitOfWork, events: list[str]) -> None:
        self._inner = inner
        self._events = events

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[Any]:
        self._events.append("begin")
        async with self._inner.begin() as transaction:
            yield transaction
        self._events.append("committed")  # the commit has returned


async def test_so3_the_fast_path_is_signalled_only_after_the_owed_command_row_is_committed(
    uow: SqlAlchemyUnitOfWork,
    clock: SystemClock,
    order_at: Callable[..., Any],
    migrated_db: Any,
    make_fact_bytes: Callable[..., bytes],
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    events: list[str] = []
    visible_at_signal: list[bool] = []
    probe = SeparateSession(migrated_db.dsn)
    probe.start()

    class ProbingSignal:
        def signal(self, ref: SagaCommandRef) -> None:
            events.append("signal")
            visible_at_signal.append(probe.command_row_visible(ref.order_id.value, ref.kind))

    recording = RecordingUnitOfWork(uow, events)
    scope = OrdersScope(
        unit_of_work=cast("Any", recording),
        catalog=cast("Any", object()),
        stock=cast("Any", object()),
        clock=clock,
        dispatcher=build_dispatcher(),
        fact_consumption=SqlAlchemyFactConsumption(cast("Any", recording), clock),
        saga_signal=ProbingSignal(),
    )
    raw = make_fact_bytes(
        "credit.approved.v1",
        correlation_id=order.id.value,
        reference=order.order_reference.value,
        event_id=uuid.uuid4(),
    )
    command = HandleCreditApprovedFactCommand(
        envelope=from_wire_json(Envelope[dict[str, Any]], raw), topic="otc.billing.facts.v1"
    )

    try:
        result = await SagaFactCommandHandler(scope).handle(command)
    finally:
        probe.stop()

    assert result.enqueued is SagaCommandKind.DESPATCH_CREATE
    assert events == ["begin", "committed", "signal"], "the signal comes after the commit returned"
    assert visible_at_signal == [True], (
        "at the moment the signal was called a SEPARATE session already saw the committed row"
    )
