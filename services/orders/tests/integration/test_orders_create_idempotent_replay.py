"""`orders.create` and `requestId` against real PostgreSQL, NATS and Kafka (R62, RI1 - RI5).

Measured at S2.3 on `postgres:18.6`: a duplicate on `uq_orders_request_id` arrives as
`sqlalchemy.exc.IntegrityError` whose `.orig.__cause__` is `asyncpg.exceptions.UniqueViolationError`
with `constraint_name == "uq_orders_request_id"` (`sqlstate 23505`); a duplicate on the order
reference names `uq_orders_order_reference`. The race test creates its own overlap: the stand-in
`fulfillment.stock.check` holds both replies until both requests have arrived.

Loop scope: function. Every host, connection and engine is created and closed in the test's loop.
"""

import asyncio
import json
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import nats
import pytest
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg as NatsMsg
from sqlalchemy.exc import IntegrityError

from otc_orders.application.ports.unit_of_work import RequestIdAlreadyPlacedError
from otc_orders.domain.order import Order
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration

REQUEST: dict[str, Any] = {
    "retailerCode": "RET-01",
    "companyCode": "CMP-01",
    "currency": "EUR",
    "lines": [
        {"productCode": "SKU-A", "quantity": 3, "unitPrice": 1999, "lineDiscount": 250},
        {"productCode": "SKU-B", "quantity": 2, "unitPrice": 1234, "lineDiscount": 100},
    ],
    "notes": "dock 4, before noon",
}
ENOUGH = [("SKU-A", 3, 50), ("SKU-B", 2, 50)]
ROUNDS = 5


async def call(client: NatsClient, payload: dict[str, Any]) -> dict[str, Any]:
    reply = await client.request("orders.create", json.dumps(payload).encode(), timeout=15)
    body: dict[str, Any] = json.loads(reply.data)
    return body


async def rows(dsn: str, sql: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def test_ri4_two_orders_with_no_request_id_both_commit(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
) -> None:
    # the property the whole feature rests on: PostgreSQL's default NULLS DISTINCT (S2.1 MEASURE)
    [index] = await rows(
        migrated_db.dsn,
        "SELECT i.indnullsnotdistinct FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE c.relname = 'uq_orders_request_id'",
    )
    assert index["indnullsnotdistinct"] is False
    await stand_in_stock_check(lambda request: stock_reply(ENOUGH))

    first = await call(orders_host.client, REQUEST)
    second = await call(orders_host.client, REQUEST)

    assert first.get("status") == second.get("status") == "placed", (first, second)
    assert first["orderId"] != second["orderId"]
    stored = await rows(migrated_db.dsn, "SELECT request_id FROM orders WHERE request_id IS NULL")
    assert len(stored) == 2, "both orders committed with no requestId"


async def test_ri1_the_request_id_is_stored_under_the_unique_index(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
) -> None:
    await stand_in_stock_check(lambda request: stock_reply(ENOUGH))
    request_id = uuid.uuid4()

    reply = await call(orders_host.client, REQUEST | {"requestId": str(request_id)})

    assert reply["status"] == "placed", reply
    [order] = await rows(
        migrated_db.dsn, "SELECT request_id FROM orders WHERE id = $1", uuid.UUID(reply["orderId"])
    )
    assert order["request_id"] == request_id


async def test_ri2_a_repeated_request_id_replays_the_original_reply_and_writes_nothing_more(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
) -> None:
    stand_in = await stand_in_stock_check(lambda request: stock_reply(ENOUGH))
    request_id = str(uuid.uuid4())

    first = await call(orders_host.client, REQUEST | {"requestId": request_id})
    second = await call(orders_host.client, REQUEST | {"requestId": request_id})

    assert second == first
    assert (first["initialAmount"], first["initialDiscount"], first["totalAmount"]) == (
        8465,
        350,
        8115,
    )
    assert len(stand_in.requests) == 1, "the replay made no stock check"
    assert len(await rows(migrated_db.dsn, "SELECT 1 FROM orders")) == 1
    assert len(await rows(migrated_db.dsn, "SELECT 1 FROM outbox")) == 1


async def test_ri5_the_placed_fact_carries_the_request_id_as_its_causation_id(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
) -> None:
    await stand_in_stock_check(lambda request: stock_reply(ENOUGH))
    request_id = uuid.uuid4()

    reply = await call(orders_host.client, REQUEST | {"requestId": str(request_id)})

    [fact] = await rows(
        migrated_db.dsn,
        "SELECT causation_id FROM outbox WHERE aggregate_id = $1",
        uuid.UUID(reply["orderId"]),
    )
    assert fact["causation_id"] == request_id


async def test_ri3_the_unit_of_work_translates_only_the_request_id_index(
    uow: SqlAlchemyUnitOfWork, place_order: Callable[..., Order], migrated_db: Any
) -> None:
    request_id = uuid.uuid4()
    async with uow.begin() as tx:
        await tx.orders.save(place_order(order_reference="ORD-000001"), request_id=request_id)

    # the same request id on a new order: translated, after the rollback
    with pytest.raises(RequestIdAlreadyPlacedError) as same_request:
        async with uow.begin() as tx:
            await tx.orders.save(place_order(order_reference="ORD-000002"), request_id=request_id)
    assert isinstance(same_request.value.__cause__, IntegrityError)

    # the same order reference under a new request id: a different unique index, untranslated
    try:
        async with uow.begin() as tx:
            await tx.orders.save(place_order(order_reference="ORD-000001"), request_id=uuid.uuid4())
    except RequestIdAlreadyPlacedError as translated:
        raise AssertionError(
            "an order_reference collision was translated as a request-id collision"
        ) from translated
    except IntegrityError as same_reference_error:
        same_reference = same_reference_error
    else:
        raise AssertionError("the duplicate order reference was accepted")
    assert "uq_orders_order_reference" in str(same_reference.orig)

    # and the lookup finds the committed order
    async with uow.begin() as tx:
        found = await tx.orders.find_by_request_id(request_id)
        missing = await tx.orders.find_by_request_id(uuid.uuid4())
    assert found is not None
    assert found.order_reference.value == "ORD-000001"
    assert missing is None


class HoldingStockCheck:
    """A `fulfillment.stock.check` stand-in that answers NOBODY until `expected` requests have
    arrived, then answers them all (design 3.4). A NATS subscription's callback runs serially, so
    it never blocks: it parks the message and the last arrival releases every parked one."""

    def __init__(self, client: NatsClient, reply: bytes, *, expected: int, hold: bool) -> None:
        self._client, self._reply, self._expected, self._hold = client, reply, expected, hold
        self._parked: list[NatsMsg] = []
        self.arrivals = 0
        self.joint_releases = 0  # times `expected` requests were parked together, then released

    async def start(self) -> None:
        await self._client.subscribe("fulfillment.stock.check", cb=self._on_request)
        await self._client.flush()

    async def _on_request(self, message: NatsMsg) -> None:
        self.arrivals += 1
        if not self._hold:
            await message.respond(self._reply)
            return
        self._parked.append(message)
        if len(self._parked) == self._expected:
            released, self._parked = self._parked, []
            self.joint_releases += 1
            for parked in released:
                await parked.respond(self._reply)


@asynccontextmanager
async def holding_stock_check(
    url: str, reply: bytes, *, expected: int, hold: bool
) -> AsyncIterator[HoldingStockCheck]:
    client = await nats.connect(url)
    try:
        stand_in = HoldingStockCheck(client, reply, expected=expected, hold=hold)
        await stand_in.start()
        yield stand_in
    finally:
        await client.close()


async def test_r62_two_concurrent_first_requests_with_one_request_id_create_one_order_one_outbox_row_and_identical_replies(  # noqa: E501
    orders_host: Any,
    nats_server: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The counter the test injects: how often a unit of work raised the translated collision.
    collisions: list[uuid.UUID] = []
    original_begin = SqlAlchemyUnitOfWork.begin

    @asynccontextmanager
    async def counting_begin(self: SqlAlchemyUnitOfWork) -> Any:
        try:
            async with original_begin(self) as transaction:
                yield transaction
        except RequestIdAlreadyPlacedError:
            collisions.append(uuid.uuid4())
            raise

    monkeypatch.setattr(SqlAlchemyUnitOfWork, "begin", counting_begin)

    translated_per_round: list[int] = []
    async with holding_stock_check(
        nats_server.url, stock_reply(ENOUGH), expected=2, hold=True
    ) as stand_in:
        for round_number in range(ROUNDS):
            request_id = uuid.uuid4()
            before = len(collisions)
            try:
                async with asyncio.timeout(30):
                    first, second = await asyncio.gather(
                        call(orders_host.client, REQUEST | {"requestId": str(request_id)}),
                        call(orders_host.client, REQUEST | {"requestId": str(request_id)}),
                    )
            except TimeoutError as error:
                raise AssertionError(
                    f"round {round_number}: the two concurrent requests did not both answer"
                ) from error
            translated_per_round.append(len(collisions) - before)

            assert first.get("status") == second.get("status") == "placed", (first, second)
            assert first == second, "both replies equal field by field"
            assert (
                len({first["initialAmount"], first["initialDiscount"], first["totalAmount"]}) == 3
            )
            assert (first["initialAmount"], first["initialDiscount"], first["totalAmount"]) == (
                8465,
                350,
                8115,
            )
            stored = await rows(
                migrated_db.dsn,
                "SELECT id FROM orders WHERE request_id = $1",
                request_id,
            )
            assert len(stored) == 1, f"round {round_number}: exactly one order for the request id"
            facts = await rows(
                migrated_db.dsn,
                "SELECT event_type FROM outbox WHERE aggregate_id = $1",
                stored[0]["id"],
            )
            assert [f["event_type"] for f in facts] == ["order.placed.v1"], (
                f"round {round_number}: exactly one order.placed.v1 outbox row"
            )

    assert stand_in.arrivals == 2 * ROUNDS, "every request reached the stock check (no fast path)"
    assert stand_in.joint_releases == ROUNDS, (
        f"the barrier held both requests together in {stand_in.joint_releases} of {ROUNDS} rounds: "
        "the overlap is created by the test, not left to scheduling"
    )
    # the barrier worked: in EVERY round the loser met the unique index and was translated once
    assert translated_per_round == [1] * ROUNDS, (
        f"the translation path must run exactly once per round, ran {translated_per_round}: "
        "the barrier did not hold both requests past the fast path"
    )
    assert Counter(translated_per_round) == Counter({1: ROUNDS})
