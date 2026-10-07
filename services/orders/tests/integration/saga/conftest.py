"""The saga integration harness (`design.md` 14.3; tasks 10.1): real lifespan, real stand-ins.

* ONE way to start the consumer: `saga_harness(**knobs)` drives the REAL `otc_orders.main` lifespan
  (feature 15's `orders_host_factory`: nothing is supplied, the host reads its own environment) with
  `SAGA_CONSUMER_ENABLED=true`, and deletes the `orders.saga` consumer group when the test is over,
  so the next test starts from a clean group (#8 id 74). A census test forbids any other module of
  this directory from touching the consumer task or the subscriber.
* The topics are shared by the session and every test has its OWN database, so a fresh group would
  replay every earlier test's facts as `unknown_order`. The harness therefore commits the group's
  offsets at the END of every partition before the lifespan starts (`history="skip"`, the default);
  the SO1 test asks for `history="replay"` and publishes its fact before the group exists.
* Six stand-in responders (real nats-py subscriptions, each with a real subscribe-and-flush probe
  before the test continues) record every request (subject, headers, raw bytes) and answer from a
  programmable behaviour. With `emit=True` a stand-in also publishes the fact its real responder
  would (features 17-22 are not built), keyed by `correlationId`, `causationId` = the request's
  `x-request-id`. No stand-in lives under `src/`.
* Facts are selected by CONTENT (the test's own correlation and event ids), never by position.
* `wait_then_assert(predicate)`: the wait and the assertion evaluate the SAME predicate object
  (#8 D4: a weaker wait, satisfied by an earlier iteration's row, then a stronger assert).
* Synchronise on durable terminal evidence (a `saga_commands` row reaching `sent`/`parked`, a
  `processed_events` row, a `saga_ignored_facts` row, an `outbox` row), never on a transient status.

Loop scope: every fixture here is function-scoped (the default): the producer, the admin client, the
stand-in connection, the database connection and the lifespan are created and closed in the loop of
the test that uses them.
"""

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import asyncpg
import nats
import pytest
import pytest_asyncio
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.errors import GroupCoordinatorNotAvailableError
from aiokafka.protocol.admin import DeleteGroupsRequest
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg as NatsMsg

from otc_contracts import Envelope, to_wire_json
from otc_contracts.generated.asyncapi import CancellationReason as WireCancellationReason
from otc_contracts.generated.asyncapi import (
    CreditApprovedPayload,
    CreditRejectedPayload,
    CreditReleasedPayload,
    DespatchLine,
    InvoiceIssuedPayload,
    InvoiceLine,
    OrderCancelledPayload,
    OrderCompletedPayload,
    OrderConfirmedPayload,
    OrderDespatchedPayload,
    OrderPlacedPayload,
    OrderSagaFailedPayload,
    PaymentReceivedPayload,
    PaymentSource,
    Reason,
    Reason1,
    Reason2,
    Reason3,
    ReservationRef,
    Shortage,
    StockRejectedPayload,
    StockReleasedPayload,
    StockReservedPayload,
)
from otc_contracts.generated.asyncapi import OrderLine as WireOrderLine
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.snapshot import OrderLineSnapshot, OrderSnapshot
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_shared_kernel import GLN, Money, OrderNumber, Quantity, UniqueId

GROUP = "orders.saga"
ORDERS_TOPIC = "otc.orders.facts.v1"
FULFILLMENT_TOPIC = "otc.fulfillment.facts.v1"
BILLING_TOPIC = "otc.billing.facts.v1"
ALL_TOPICS = (ORDERS_TOPIC, FULFILLMENT_TOPIC, BILLING_TOPIC)
NOW = datetime(2026, 10, 5, 12, 0, 0, 123000, tzinfo=UTC)

SUBJECT_OF = {
    SagaCommandKind.STOCK_RESERVE: "fulfillment.stock.reserve",
    SagaCommandKind.STOCK_RELEASE: "fulfillment.stock.release",
    SagaCommandKind.DESPATCH_CREATE: "fulfillment.despatch.create",
    SagaCommandKind.CREDIT_HOLD: "billing.credit.hold",
    SagaCommandKind.INVOICE_ISSUE: "billing.invoice.issue",
    SagaCommandKind.CREDIT_RELEASE: "billing.credit.release",
}


def topic_of(event_type: str) -> str:
    if event_type.startswith("order."):
        return ORDERS_TOPIC
    if event_type.startswith("stock."):
        return FULFILLMENT_TOPIC
    return BILLING_TOPIC


class KafkaServerShape(Protocol):
    @property
    def bootstrap_servers(self) -> str: ...


# ------------------------------------------------------------------------------------- the facts


def fact_payload(event_type: str, reference: str, *, release_reason: Reason1) -> Any:
    reservation = ReservationRef(
        reservation_id=uuid.UUID("00000000-0000-4000-8000-0000000000f1"),
        product_code="SKU-A",
        units=3,
    )
    match event_type:
        case "order.placed.v1":
            return OrderPlacedPayload(
                order_reference=reference,
                retailer_code="RET-01",
                company_code="CMP-01",
                buyer_gln="4012345000009",
                supplier_gln="5412345000006",
                currency="EUR",
                order_date=NOW,
                lines=[
                    WireOrderLine(
                        product_code="SKU-A", quantity=3, unit_price=1999, line_discount=250
                    )
                ],
                initial_amount=8465,
                initial_discount=350,
                total_amount=8115,
            )
        case "stock.reserved.v1":
            return StockReservedPayload(
                order_reference=reference, company_code="CMP-01", reservations=[reservation]
            )
        case "stock.rejected.v1":
            return StockRejectedPayload(
                order_reference=reference,
                company_code="CMP-01",
                shortages=[Shortage(product_code="SKU-A", requested=3, available=1)],
                reason=Reason.insufficient_stock,
            )
        case "stock.released.v1":
            return StockReleasedPayload(
                order_reference=reference,
                company_code="CMP-01",
                released=[reservation],
                reason=release_reason,
            )
        case "credit.approved.v1":
            return CreditApprovedPayload(
                order_reference=reference,
                retailer_code="RET-01",
                company_code="CMP-01",
                credit_code="CR-000001",
                currency="EUR",
                held_amount=8115,
                available_credit_after=91885,
            )
        case "credit.rejected.v1":
            return CreditRejectedPayload(
                order_reference=reference,
                retailer_code="RET-01",
                company_code="CMP-01",
                currency="EUR",
                requested_amount=8115,
                available_credit=100,
                reason=Reason2.over_limit,
            )
        case "credit.released.v1":
            return CreditReleasedPayload(
                order_reference=reference,
                retailer_code="RET-01",
                company_code="CMP-01",
                currency="EUR",
                released_amount=8115,
                available_credit_after=100000,
                reason=Reason3.invoice_paid,
            )
        case "order.despatched.v1":
            return OrderDespatchedPayload(
                order_reference=reference,
                despatch_reference="DES-000001",
                despatch_date=NOW,
                company_code="CMP-01",
                retailer_code="RET-01",
                lines=[DespatchLine(product_code="SKU-A", units=3)],
            )
        case "invoice.issued.v1":
            return InvoiceIssuedPayload(
                order_reference=reference,
                invoice_reference="INV-000001",
                invoice_date=NOW,
                retailer_code="RET-01",
                company_code="CMP-01",
                currency="EUR",
                lines=[InvoiceLine(product_code="SKU-A", units=3, unit_price=1999)],
                amount=8465,
                discount=350,
                total_amount=8115,
            )
        case "payment.received.v1":
            return PaymentReceivedPayload(
                order_reference=reference,
                invoice_reference="INV-000001",
                payment_reference="PAY-1",
                currency="EUR",
                amount=8115,
                value_date=NOW,
                source=PaymentSource.test,
            )
        case "order.confirmed.v1":
            return OrderConfirmedPayload(
                order_reference=reference,
                retailer_code="RET-01",
                company_code="CMP-01",
                currency="EUR",
                total_amount=8115,
                confirmed_at=NOW,
            )
        case "order.completed.v1":
            return OrderCompletedPayload(
                order_reference=reference,
                retailer_code="RET-01",
                company_code="CMP-01",
                currency="EUR",
                total_amount=8115,
                completed_at=NOW,
            )
        case "order.cancelled.v1":
            return OrderCancelledPayload(
                order_reference=reference,
                retailer_code="RET-01",
                company_code="CMP-01",
                cancellation_reason=WireCancellationReason.stock_rejected,
                cancelled_at=NOW,
                compensation_steps=[],
            )
        case "order.saga_failed.v1":
            return OrderSagaFailedPayload(
                order_reference=reference,
                command="stock.reserve",
                attempts=3,
                last_error="no responders",
                failed_at=NOW,
            )
    raise AssertionError(f"no payload builder for {event_type}")


def fact_bytes(
    event_type: str,
    *,
    correlation_id: uuid.UUID,
    reference: str,
    event_id: uuid.UUID,
    causation_id: uuid.UUID | None = None,
    release_reason: Reason1 = Reason1.credit_rejected,
    occurred_at: datetime | None = None,
    payload: Mapping[str, Any] | None = None,
    raw: Mapping[str, Any] | None = None,
) -> bytes:
    document_payload = json.loads(
        to_wire_json(fact_payload(event_type, reference, release_reason=release_reason))
    )
    if payload is not None:
        document_payload = dict(payload)
    envelope = Envelope[dict[str, Any]](
        event_id=event_id,
        event_type=event_type,
        aggregate_id=correlation_id,
        correlation_id=correlation_id,
        causation_id=causation_id if causation_id is not None else uuid.uuid4(),
        occurred_at=occurred_at if occurred_at is not None else datetime.now(UTC),
        payload=document_payload,
    )
    document = json.loads(to_wire_json(envelope))
    document.update(raw or {})
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


# ---- stand-in responders


@dataclass(frozen=True)
class Recorded:
    subject: str
    headers: dict[str, str]
    body: bytes

    @property
    def request(self) -> dict[str, Any]:
        document: dict[str, Any] = json.loads(self.body)
        return document


Behaviour = Callable[[Recorded], bytes | None]


def accept(kind: SagaCommandKind) -> Behaviour:
    """The success reply of `kind` (a business `accepted` / `approved` / `released` outcome)."""

    def reply(recorded: Recorded) -> bytes:
        reference = recorded.request["orderReference"]
        bodies: dict[SagaCommandKind, dict[str, Any]] = {
            SagaCommandKind.STOCK_RESERVE: {"outcome": "accepted", "orderReference": reference},
            SagaCommandKind.STOCK_RELEASE: {"outcome": "released", "orderReference": reference},
            SagaCommandKind.DESPATCH_CREATE: {
                "orderReference": reference,
                "despatchReference": "DES-000001",
                "despatchDate": "2026-10-05T12:00:00.123Z",
                "created": True,
            },
            SagaCommandKind.CREDIT_HOLD: {
                "outcome": "approved",
                "orderReference": reference,
                "creditCode": "CR-000001",
                "currency": "EUR",
                "heldAmount": 8115,
                "availableCredit": 91885,
            },
            SagaCommandKind.INVOICE_ISSUE: {
                "orderReference": reference,
                "invoiceReference": "INV-000001",
                "invoiceDate": "2026-10-05T12:00:00.123Z",
                "currency": "EUR",
                "totalAmount": 8115,
                "status": "issued",
                "created": True,
            },
            SagaCommandKind.CREDIT_RELEASE: {
                "released": True,
                "orderReference": reference,
                "currency": "EUR",
                "availableCreditAfter": 100000,
            },
        }
        return json.dumps(bodies[kind]).encode()

    return reply


def reject_credit(recorded: Recorded) -> bytes:
    return json.dumps(
        {
            "outcome": "rejected",
            "orderReference": recorded.request["orderReference"],
            "currency": "EUR",
            "availableCredit": 100,
            "reason": "over_limit",
        }
    ).encode()


def silent(_recorded: Recorded) -> None:
    return None


def not_json(_recorded: Recorded) -> bytes:
    return b"this is not json"


# the fact a real responder would publish after answering, per kind and outcome
EMITS: dict[SagaCommandKind, str] = {
    SagaCommandKind.STOCK_RESERVE: "stock.reserved.v1",
    SagaCommandKind.STOCK_RELEASE: "stock.released.v1",
    SagaCommandKind.DESPATCH_CREATE: "order.despatched.v1",
    SagaCommandKind.CREDIT_HOLD: "credit.approved.v1",
    SagaCommandKind.INVOICE_ISSUE: "invoice.issued.v1",
}


class StandIn:
    def __init__(
        self,
        kind: SagaCommandKind,
        client: NatsClient,
        publish: Callable[..., Awaitable[uuid.UUID]],
    ) -> None:
        self.kind = kind
        self.subject = SUBJECT_OF[kind]
        self.behaviour: Behaviour = accept(kind)
        self.emit = False
        self.emit_as: str | None = None  # override the fact type (e.g. credit.rejected.v1)
        self.requests: list[Recorded] = []
        self._client = client
        self.publish = publish

    async def start(self) -> None:
        await self._client.subscribe(self.subject, cb=self._on_request)

    async def _on_request(self, message: NatsMsg) -> None:
        recorded = Recorded(
            subject=message.subject,
            headers={str(k): str(v) for k, v in (message.headers or {}).items()},
            body=message.data,
        )
        self.requests.append(recorded)
        reply = self.behaviour(recorded)
        if reply is not None:
            await message.respond(reply)
            if self.emit:
                await self.publish(
                    self.emit_as or EMITS[self.kind],
                    correlation_id=uuid.UUID(recorded.headers["x-correlation-id"]),
                    reference=recorded.request["orderReference"],
                    causation_id=uuid.UUID(recorded.headers["x-request-id"]),
                )

    def requests_for(self, order_id: uuid.UUID) -> list[Recorded]:
        return [r for r in self.requests if r.headers.get("x-correlation-id") == str(order_id)]


# ---------------------------------------------------------------------------------- the database


class Db:
    """A plain asyncpg connection to the test's database (never the host's engine)."""

    def __init__(self, connection: asyncpg.Connection[asyncpg.Record]) -> None:
        self._connection = connection

    async def fetch(self, sql: str, *args: Any) -> list[asyncpg.Record]:
        return list(await self._connection.fetch(sql, *args))

    async def fetchval(self, sql: str, *args: Any) -> Any:
        return await self._connection.fetchval(sql, *args)

    async def status_of(self, order_id: UniqueId | uuid.UUID) -> str | None:
        key = order_id.value if isinstance(order_id, UniqueId) else order_id
        value: str | None = await self._connection.fetchval(
            "SELECT status FROM orders WHERE id = $1", key
        )
        return value

    async def command_rows(self, order_id: UniqueId | uuid.UUID) -> list[asyncpg.Record]:
        key = order_id.value if isinstance(order_id, UniqueId) else order_id
        return await self.fetch(
            "SELECT id, command, status, attempts, last_error, payload::text AS payload, "
            "next_attempt_at, sent_at FROM saga_commands WHERE order_id = $1 ORDER BY created_at",
            key,
        )

    async def command_row(
        self, order_id: UniqueId | uuid.UUID, kind: SagaCommandKind
    ) -> asyncpg.Record | None:
        for row in await self.command_rows(order_id):
            if row["command"] == kind.value:
                return row
        return None

    async def outbox_types(self, order_id: UniqueId | uuid.UUID) -> list[str]:
        key = order_id.value if isinstance(order_id, UniqueId) else order_id
        rows = await self.fetch(
            "SELECT event_type FROM outbox WHERE aggregate_id = $1 ORDER BY seq", key
        )
        return [row["event_type"] for row in rows]

    async def ignored(
        self, order_id: UniqueId | uuid.UUID, event_type: str | None = None
    ) -> list[asyncpg.Record]:
        key = order_id.value if isinstance(order_id, UniqueId) else order_id
        rows = await self.fetch(
            "SELECT event_id, event_type, order_id, correlation_id, observed_status, "
            "expected_status, marker FROM saga_ignored_facts WHERE correlation_id = $1 "
            "ORDER BY recorded_at",
            key,
        )
        return [r for r in rows if event_type is None or r["event_type"] == event_type]

    async def processed(self, event_id: uuid.UUID) -> bool:
        return bool(
            await self._connection.fetchval(
                "SELECT count(*) FROM processed_events "
                "WHERE event_id = $1 AND consumer = 'orders.saga'",
                event_id,
            )
        )


@pytest_asyncio.fixture(loop_scope="function")
async def db(migrated_db: Any) -> AsyncIterator[Db]:
    connection = await asyncpg.connect(migrated_db.dsn)
    try:
        yield Db(connection)
    finally:
        await connection.close()


async def wait_then_assert(
    predicate: Callable[[], Awaitable[bool]],
    message: str,
    *,
    seconds: float = 20,
) -> None:
    """Wait until `predicate()` is true, then ASSERT THE SAME PREDICATE once more.

    The wait and the assertion are one object on purpose (#8 D4): a wait on a weaker condition (an
    earlier iteration's row, a status the saga merely passes through) followed by a stronger
    assertion is a race the test loses when the machine is slow. Failure names what was waited for.
    """

    async def poll() -> None:
        while not await predicate():  # noqa: ASYNC110 - polling a database: there is no event
            await asyncio.sleep(0.05)

    with contextlib.suppress(TimeoutError):  # the assertion below reports what was waited for
        await asyncio.wait_for(poll(), timeout=seconds)
    assert await predicate(), f"timed out after {seconds}s waiting for: {message}"


@pytest.fixture
def waits() -> Callable[..., Awaitable[None]]:
    return wait_then_assert


# --------------------------------------------------------------------------------- planting orders


OrderAt = Callable[..., Awaitable[Order]]


@pytest.fixture
def order_at(uow: SqlAlchemyUnitOfWork, reference_data: Any) -> OrderAt:
    """`await order_at(status, reason=None, reference=None)`: an order inserted through the real
    repository AT `status`, with NO domain events (so no outbox row, and nothing for the relay to
    publish: the saga sees only what the test publishes)."""
    counter = iter(range(101, 10_000))

    async def plant(
        status: OrderStatus,
        *,
        reason: CancellationReason | None = None,
        reference: str | None = None,
    ) -> Order:
        if status is OrderStatus.CANCELLED and reason is None:
            reason = CancellationReason.STOCK_REJECTED
        order = Order.rehydrate(
            OrderSnapshot(
                id=UniqueId.new(),
                order_reference=OrderNumber(reference or f"ORD-{next(counter):06d}"),
                order_date=NOW,
                retailer_code="RET-01",
                buyer_gln=GLN("4012345000009"),
                company_code="CMP-01",
                supplier_gln=GLN("5412345000006"),
                currency="EUR",
                status=status,
                cancellation_reason=reason,
                notes=None,
                lines=(
                    OrderLineSnapshot(
                        id=UniqueId.new(),
                        product_code="SKU-A",
                        description="Alpha pallet",
                        quantity=Quantity(3),
                        unit_price=Money(1999, "EUR"),
                        line_discount=Money(250, "EUR"),
                    ),
                    OrderLineSnapshot(
                        id=UniqueId.new(),
                        product_code="SKU-B",
                        description=None,
                        quantity=Quantity(2),
                        unit_price=Money(1234, "EUR"),
                        line_discount=Money(100, "EUR"),
                    ),
                ),
                created_at=NOW,
                updated_at=NOW + timedelta(minutes=5),
            )
        )
        async with uow.begin() as transaction:
            await transaction.orders.save(order)
        return order

    return plant


# ------------------------------------------------------------------------------------- the broker


async def delete_group(bootstrap_servers: str, group: str = GROUP) -> None:
    """Delete the consumer group (aiokafka 0.14's admin has no such call: the protocol request is
    sent to the group's coordinator). A group that does not exist is already deleted.

    On a broker that has never seen a group, the first `FindCoordinator` makes the broker create
    `__consumer_offsets` and answers `GroupCoordinatorNotAvailable` until it exists: retried.
    """
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        last = "no attempt"
        for _ in range(60):
            try:
                coordinator = await admin.find_coordinator(group)
            except GroupCoordinatorNotAvailableError:
                last = "coordinator not available"
                await asyncio.sleep(0.5)
                continue
            response = await admin._send_request_to_node(coordinator, DeleteGroupsRequest([group]))
            (_, error_code) = response.results[0]
            if error_code in (0, 69):  # none / GROUP_ID_NOT_FOUND
                return
            last = f"error {error_code}"
            await asyncio.sleep(0.25)  # 68 NON_EMPTY_GROUP: the member is still leaving
        raise AssertionError(f"the group {group} could not be deleted ({last})")
    finally:
        await admin.close()


async def committed_offsets(
    bootstrap_servers: str, group: str = GROUP
) -> dict[tuple[str, int], int]:
    """The group's committed offsets as THE BROKER reports them (never inferred)."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        offsets: dict[Any, Any] = await admin.list_consumer_group_offsets(group)
        return {(tp.topic, tp.partition): int(meta.offset) for tp, meta in offsets.items()}
    finally:
        await admin.close()


async def commit_group_at_end(bootstrap_servers: str, group: str = GROUP) -> None:
    """Commit the END offset of every partition of the three topics under `group`, so a later
    member reads only facts published after this call.

    Partitions are assigned MANUALLY (no group join): a join to an empty group waits out the
    broker's `group.initial.rebalance.delay.ms` (3 s measured), and the saga's own consumer pays
    that once per test already.
    """
    consumer = AIOKafkaConsumer(
        bootstrap_servers=bootstrap_servers,
        group_id=group,
        client_id="otc-orders-tests-baseline",
        enable_auto_commit=False,
    )
    await consumer.start()
    try:
        partitions = [
            TopicPartition(topic, partition)
            for topic in ALL_TOPICS
            for partition in await partitions_of(bootstrap_servers, topic)
        ]
        consumer.assign(partitions)
        ends: dict[Any, int] = await consumer.end_offsets(partitions)
        await consumer.commit({tp: ends[tp] for tp in partitions})
    finally:
        # aiokafka 0.14.0 (measured, see `read_topic`): stop() can raise CancelledError from a
        # coordinator task that has not taken its first step; one loop tick lets it start.
        await asyncio.sleep(0.05)
        await consumer.stop()


async def partitions_of(bootstrap_servers: str, topic: str) -> list[int]:
    """The partition ids the BROKER reports for `topic` (its metadata, not a constant)."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        described: list[dict[str, Any]] = await admin.describe_topics([topic])
    finally:
        await admin.close()
    return sorted(int(partition["partition"]) for partition in described[0]["partitions"])


# -------------------------------------------------------------------------------------- the harness


@dataclass
class SagaHarness:
    """What a test sees while the lifespan runs."""

    runtime: Any
    app: Any
    stand_ins: dict[SagaCommandKind, StandIn]
    publish_fact: Callable[..., Awaitable[uuid.UUID]]
    db: Db
    bootstrap_servers: str
    positions: dict[uuid.UUID, tuple[str, int, int]] = field(default_factory=dict)
    """event id -> (topic, partition, offset) of every fact published through `publish_fact`."""
    behaviours: dict[str, Behaviour] = field(default_factory=lambda: dict(BEHAVIOURS))
    """The named stand-in behaviours a test can install: `reject_credit`, `silent`, `not_json` and
    `accept_<kind>` (a stand-in's default)."""

    def stand_in(self, kind: SagaCommandKind) -> StandIn:
        return self.stand_ins[kind]


FAST_KNOBS = {
    "SAGA_COMMAND_TIMEOUT_MS": "400",
    "SAGA_COMMAND_BACKOFF_MS": "20",
    "SAGA_COMMAND_LEASE_MS": "5000",
    "SAGA_PARK_RETRY_CAP_MS": "1000",
    "SAGA_SWEEPER_INTERVAL_MS": "100",
    "SAGA_PENDING_GRACE_MS": "300",
    "SAGA_SWEEPER_ENABLED": "true",
    "OUTBOX_POLL_INTERVAL_MS": "50",
}

BEHAVIOURS: dict[str, Behaviour] = {
    "reject_credit": reject_credit,
    "silent": silent,
    "not_json": not_json,
    **{f"accept_{kind.name.lower()}": accept(kind) for kind in SagaCommandKind},
}

HarnessFactory = Callable[..., AbstractAsyncContextManager[SagaHarness]]


@pytest_asyncio.fixture(loop_scope="function")
async def saga_stand_ins(nats_server: Any) -> AsyncIterator[dict[SagaCommandKind, StandIn]]:
    """The six stand-ins, subscribed and flushed on their own connection (closed with the test)."""

    async def not_yet(event_type: str, **_kwargs: Any) -> uuid.UUID:
        raise AssertionError(f"{event_type}: a stand-in emitted before the harness started")

    client = await nats.connect(nats_server.url)
    stand_ins = {kind: StandIn(kind, client, not_yet) for kind in SagaCommandKind}
    try:
        for stand_in in stand_ins.values():
            await stand_in.start()
        await client.flush()  # a real subscribe-and-flush probe, never a fixed delay
        yield stand_ins
    finally:
        await client.close()


@pytest_asyncio.fixture(loop_scope="function")
async def saga_harness(
    orders_host_factory: Callable[..., AbstractAsyncContextManager[Any]],
    kafka_server: KafkaServerShape,
    saga_stand_ins: dict[SagaCommandKind, StandIn],
    db: Db,
    reference_data: Any,
) -> AsyncIterator[HarnessFactory]:
    """`async with saga_harness(sweeper=..., history="skip") as saga:` starts the REAL lifespan."""
    bootstrap = kafka_server.bootstrap_servers
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap, client_id="otc-orders-tests-facts")
    await producer.start()

    positions: dict[uuid.UUID, tuple[str, int, int]] = {}

    async def publish_fact(
        event_type: str,
        *,
        correlation_id: uuid.UUID,
        reference: str = "ORD-000001",
        event_id: uuid.UUID | None = None,
        topic: str | None = None,
        **kwargs: Any,
    ) -> uuid.UUID:
        identifier = event_id if event_id is not None else uuid.uuid4()
        sent = await producer.send_and_wait(
            topic or topic_of(event_type),
            key=str(correlation_id).encode("utf-8"),
            value=fact_bytes(
                event_type,
                correlation_id=correlation_id,
                reference=reference,
                event_id=identifier,
                **kwargs,
            ),
            headers=[("x-event-type", event_type.encode("utf-8"))],
        )
        positions.setdefault(identifier, (sent.topic, int(sent.partition), int(sent.offset)))
        return identifier

    @asynccontextmanager
    async def start(
        *, history: str = "skip", cleanup: bool = True, **knobs: str
    ) -> AsyncIterator[SagaHarness]:
        """`history`: "skip" (default) starts from the END of every partition; "replay" deletes the
        group, so a first boot reads from the beginning (SO1); "keep" resumes whatever the group
        committed (a restart). `cleanup=False` leaves the group for a later `history="keep"`."""
        if history == "skip":
            await delete_group(bootstrap)
            await commit_group_at_end(bootstrap)
        elif history == "replay":
            await delete_group(bootstrap)
        for stand_in in saga_stand_ins.values():
            stand_in.publish = publish_fact
        try:
            async with orders_host_factory(
                **({"SAGA_CONSUMER_ENABLED": "true"} | FAST_KNOBS | knobs)
            ) as host:
                yield SagaHarness(
                    runtime=host.runtime,
                    app=host.app,
                    stand_ins=saga_stand_ins,
                    publish_fact=publish_fact,
                    db=db,
                    bootstrap_servers=bootstrap,
                    positions=positions,
                )
        finally:
            if cleanup:
                await delete_group(bootstrap)

    try:
        yield start
    finally:
        await producer.stop()


@pytest.fixture
def make_fact_bytes() -> Callable[..., bytes]:
    """`make_fact_bytes(event_type, correlation_id=..., reference=..., event_id=..., ...)`: the wire
    bytes of one fact envelope (`fact_bytes`), for tests that build a command without a broker."""
    return fact_bytes


@dataclass(frozen=True)
class Broker:
    """What the tests ask of the broker itself (never inferred from our own tables)."""

    bootstrap_servers: str

    async def committed(self) -> dict[tuple[str, int], int]:
        return await committed_offsets(self.bootstrap_servers)

    async def delete_group(self) -> None:
        await delete_group(self.bootstrap_servers)

    async def commit_end(self) -> None:
        await commit_group_at_end(self.bootstrap_servers)

    async def group_ids(self) -> set[str]:
        admin = AIOKafkaAdminClient(bootstrap_servers=self.bootstrap_servers)
        await admin.start()
        try:
            groups: list[tuple[str, str]] = await admin.list_consumer_groups()
            return {group_id for group_id, _protocol in groups}
        finally:
            await admin.close()

    async def partitions_of(self, topic: str) -> list[int]:
        return await partitions_of(self.bootstrap_servers, topic)


@pytest.fixture
def broker(kafka_server: KafkaServerShape) -> Broker:
    return Broker(kafka_server.bootstrap_servers)


@pytest_asyncio.fixture(loop_scope="function")
async def saga_publisher(
    kafka_server: KafkaServerShape,
) -> AsyncIterator[Callable[..., Awaitable[uuid.UUID]]]:
    """A bare fact publisher for tests that publish BEFORE any lifespan exists (SO1)."""
    producer = AIOKafkaProducer(
        bootstrap_servers=kafka_server.bootstrap_servers, client_id="otc-orders-tests-early"
    )
    await producer.start()

    async def publish(
        event_type: str, *, correlation_id: uuid.UUID, reference: str = "ORD-000001", **kwargs: Any
    ) -> uuid.UUID:
        identifier = uuid.uuid4()
        await producer.send_and_wait(
            topic_of(event_type),
            key=str(correlation_id).encode("utf-8"),
            value=fact_bytes(
                event_type,
                correlation_id=correlation_id,
                reference=reference,
                event_id=identifier,
                **kwargs,
            ),
        )
        return identifier

    try:
        yield publish
    finally:
        await producer.stop()
