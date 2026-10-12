"""The Gateway's MongoDB read-model adapter against documents written by the REAL projector writer
from the REAL seeded sagas' facts (R53, R54; the projector's `PR33` hand-over).

Not a mock of the collection and not the Gateway's own idea of the shape: the six seeded sagas'
outbox facts go through `MongoReadModelWriter`, and the Gateway reads what that wrote. A renamed
element, a changed id format or a new internal field fails HERE.

Proven: every public field of every document reaches `ReadModelOrder` and the wire from its own
element; the three internal elements (`statusRank`, `processedEventKeys`, `timelineOrderVersion`)
are present in the stored document and absent from every response and from the `find` the driver
sent (an INCLUSION projection, read from the command log); the list is newest-first, filtered,
paged, and never holds a placeholder (R53) while the detail serves it with `headerComplete: false`;
and the adapter sent only read commands.
"""

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from pymongo import AsyncMongoClient, monitoring
from pymongo.asynchronous.collection import AsyncCollection

from otc_contracts import format_instant, parse_fact, to_wire_json
from otc_gateway.application.order_views import order_detail, order_summary
from otc_gateway.application.ports.order_read_model import OrderListFilter
from otc_gateway.infrastructure.mongo_order_read_model import (
    COLLECTION,
    DETAIL_FIELDS,
    SUMMARY_FIELDS,
    MongoOrderReadModel,
)
from otc_projector.application.projection import project
from otc_projector.infrastructure.messaging.idempotent_consumer import IdempotentConsumer
from otc_projector.infrastructure.persistence.mongo_read_model_writer import MongoReadModelWriter
from otc_projector.infrastructure.persistence.read_model_indexes import ensure_indexes
from otc_seed.domain.data.sagas import SAGAS

pytestmark = pytest.mark.integration

INTERNAL = ("statusRank", "processedEventKeys", "timelineOrderVersion")
WRITE_COMMANDS = {
    "insert",
    "update",
    "delete",
    "findAndModify",
    "create",
    "createIndexes",
    "drop",
    "dropIndexes",
    "dropDatabase",
    "renameCollection",
}


class CommandLog(monitoring.CommandListener):
    def __init__(self) -> None:
        self.started_commands: list[tuple[str, dict[str, Any]]] = []

    def started(self, event: monitoring.CommandStartedEvent) -> None:
        self.started_commands.append((event.command_name, dict(event.command)))

    def succeeded(self, event: monitoring.CommandSucceededEvent) -> None:
        pass

    def failed(self, event: monitoring.CommandFailedEvent) -> None:
        pass

    def named(self, name: str) -> list[dict[str, Any]]:
        return [command for n, command in self.started_commands if n == name]


def saga_facts(saga: Any) -> list[Any]:
    facts = []
    for row in (*saga.orders_outbox, *saga.fulfillment_outbox, *saga.billing_outbox):
        facts.append(
            parse_fact(
                json.dumps(
                    {
                        "eventId": row.event_id,
                        "eventType": row.event_type,
                        "aggregateId": row.aggregate_id,
                        "correlationId": row.correlation_id,
                        "causationId": row.causation_id,
                        "occurredAt": format_instant(row.occurred_at),
                        "payload": dict(row.payload),
                    }
                )
            )
        )
    return facts


async def no_signal(applied: Any) -> None:
    return None


class Fixture:
    def __init__(self, collection: AsyncCollection[dict[str, Any]], log: CommandLog) -> None:
        self.collection = collection
        self.log = log
        self.adapter = MongoOrderReadModel(collection)
        self.writer = MongoReadModelWriter(collection, IdempotentConsumer(collection))

    async def project(self, facts: list[Any]) -> None:
        for fact in facts:
            await self.writer.apply(project(fact), after_applied=no_signal)

    async def raw(self, order_id: str) -> dict[str, Any]:
        found = await self.collection.find_one({"_id": order_id})
        assert found is not None
        return found


@pytest_asyncio.fixture(loop_scope="function")
async def model(fresh_mongo_database: Any) -> AsyncIterator[Fixture]:
    log = CommandLog()
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
        fresh_mongo_database.uri, event_listeners=[log]
    )
    collection = client.get_database(fresh_mongo_database.name).get_collection(COLLECTION)
    await ensure_indexes(collection)
    fixture = Fixture(collection, log)
    for saga in SAGAS:
        await fixture.project(saga_facts(saga))
    log.started_commands.clear()
    try:
        yield fixture
    finally:
        await client.close()


def without_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: without_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [without_nulls(v) for v in value]
    return value


# --------------------------------------------------------------------------- the detail


@pytest.mark.parametrize("index", range(6))
async def test_the_detail_of_each_seeded_saga_equals_the_stored_document_field_by_field(
    model: Fixture, index: int
) -> None:
    saga = SAGAS[index]
    raw = await model.raw(saga.order_id)
    assert all(name in raw for name in INTERNAL), "the stored document must hold the internals"

    order = await model.adapter.find_by_id(UUID(saga.order_id))

    assert order is not None
    wire = json.loads(to_wire_json(order_detail(order)))
    public = {name: raw[name] for name in DETAIL_FIELDS}
    assert without_nulls(wire) == without_nulls(public)
    # and against the seed's own account of the saga, not only the stored copy
    assert wire["orderReference"] == saga.order_reference
    assert wire["status"] == saga.status
    assert wire["totals"] == {
        "initialAmount": saga.initial_amount,
        "initialDiscount": saga.initial_discount,
        "totalAmount": saga.total_amount,
    }
    assert [e["eventType"] for e in wire["events"]] == [e["eventType"] for e in raw["events"]]
    assert len(wire["events"]) == len(saga.timeline)
    for name in INTERNAL:
        assert name not in json.dumps(wire), f"{name} reached the wire"


async def test_the_totals_of_each_seeded_saga_are_the_seeds_own_three_numbers(
    model: Fixture,
) -> None:
    # NOT a swap guard: every seeded saga has `initialDiscount == 0`, so `initialAmount ==
    # totalAmount` in each document and a transposition of those two is invisible here. The swap is
    # guarded by the next test, on a document whose three totals are pairwise distinct.
    for saga in SAGAS:
        order = await model.adapter.find_by_id(UUID(saga.order_id))
        assert order is not None
        totals = order_detail(order).totals
        assert totals is not None
        assert (totals.initial_amount, totals.initial_discount, totals.total_amount) == (
            saga.initial_amount,
            saga.initial_discount,
            saga.total_amount,
        )


DISTINCT_TOTALS = {"initialAmount": 8525, "initialDiscount": 165, "totalAmount": 8360}


async def test_the_three_totals_reach_the_list_summary_and_the_detail_each_from_its_own_element(
    model: Fixture,
) -> None:
    # A document in the shape the projector wrote (a copy of a seeded one), with three PAIRWISE
    # DISTINCT totals and no value contained in another: a transposition of any two fails.
    assert len(set(DISTINCT_TOTALS.values())) == 3
    document = await model.raw(SAGAS[0].order_id)
    order_id = str(UUID(int=424242))
    document |= {
        "_id": order_id,
        "orderId": order_id,
        "orderReference": "ORD-000777",
        "totals": dict(DISTINCT_TOTALS),
    }
    await model.collection.insert_one(document)

    detail = await model.adapter.find_by_id(UUID(order_id))
    page = await model.adapter.list_orders(all_filter(order_reference="ORD-000777"))

    assert detail is not None
    assert [h.order_reference for h in page.items] == ["ORD-000777"]
    expected = {"initialAmount": 8525, "initialDiscount": 165, "totalAmount": 8360}
    detail_totals = order_detail(detail).totals
    summary_totals = order_summary(page.items[0]).totals
    assert detail_totals is not None
    assert summary_totals is not None
    assert json.loads(to_wire_json(detail_totals)) == expected
    assert json.loads(to_wire_json(summary_totals)) == expected
    assert (
        detail.header.totals.initial_amount,
        detail.header.totals.initial_discount,
        detail.header.totals.total_amount,
    ) == (8525, 165, 8360)


async def test_an_unknown_id_is_none_and_a_reference_resolves_to_its_order_id(
    model: Fixture,
) -> None:
    assert await model.adapter.find_by_id(UUID(int=12345)) is None
    for saga in SAGAS:
        found = await model.adapter.find_order_id_by_reference(saga.order_reference)
        assert found == UUID(saga.order_id)
    assert await model.adapter.find_order_id_by_reference("ORD-999999") is None


# --------------------------------------------------------------------------- the list


def all_filter(**override: Any) -> OrderListFilter:
    values: dict[str, Any] = {
        "statuses": (),
        "retailer_code": None,
        "company_code": None,
        "order_reference": None,
        "page": 1,
        "page_size": 25,
    }
    return OrderListFilter(**(values | override))


async def test_the_list_is_newest_order_date_first_and_each_row_equals_its_document(
    model: Fixture,
) -> None:
    page = await model.adapter.list_orders(all_filter())

    assert page.total == 6
    references = [h.order_reference or "" for h in page.items]
    assert references == sorted(references, reverse=True)  # sagas are dated in sequence
    for header in page.items:
        raw = await model.raw(str(header.order_id))
        wire = json.loads(to_wire_json(order_summary(header)))
        assert without_nulls(wire) == without_nulls({n: raw[n] for n in SUMMARY_FIELDS})
        for name in (*INTERNAL, "items", "events", "references", "headerComplete"):
            assert name not in wire


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"statuses": ("cancelled",)}, ["ORD-000006"]),
        (
            {"statuses": ("completed",)},
            ["ORD-000005", "ORD-000004", "ORD-000003", "ORD-000002", "ORD-000001"],
        ),
        ({"statuses": ("cancelled", "placed")}, ["ORD-000006"]),
        ({"retailer_code": "CarrefourEs"}, ["ORD-000006", "ORD-000001"]),
        ({"company_code": "GERMANFOODS"}, ["ORD-000004"]),
        ({"order_reference": "ORD-000003"}, ["ORD-000003"]),
        ({"retailer_code": "CarrefourEs", "statuses": ("completed",)}, ["ORD-000001"]),
        ({"retailer_code": "NoSuchRetailer"}, []),
    ],
)
async def test_each_list_filter_selects_exactly_its_documents_and_total_counts_the_same_set(
    model: Fixture, override: dict[str, Any], expected: list[str]
) -> None:
    page = await model.adapter.list_orders(all_filter(**override))

    assert [h.order_reference for h in page.items] == expected
    assert page.total == len(expected)


async def test_the_list_pages_without_repeating_or_skipping_a_row(model: Fixture) -> None:
    seen: list[str | None] = []
    for number in (1, 2, 3):
        page = await model.adapter.list_orders(all_filter(page=number, page_size=2))
        assert page.total == 6
        assert len(page.items) == 2
        seen += [h.order_reference for h in page.items]

    assert seen == [f"ORD-00000{n}" for n in (6, 5, 4, 3, 2, 1)]
    beyond = await model.adapter.list_orders(all_filter(page=4, page_size=2))
    assert (beyond.items, beyond.total) == ((), 6)


async def test_a_placeholder_is_served_by_the_detail_and_never_by_the_list_or_its_total(
    model: Fixture,
) -> None:
    saga = SAGAS[0]
    stray = next(f for f in saga_facts(saga) if f.event_type == "stock.reserved.v1")
    outran = UUID(int=987654321)
    # the same fact, re-keyed to an order id no `order.placed.v1` has been projected for (R53)
    document = json.loads(stray.model_dump_json(by_alias=True))
    document["correlationId"] = str(outran)
    document["eventId"] = str(UUID(int=555))
    await model.project([parse_fact(json.dumps(document))])

    placeholder = await model.adapter.find_by_id(outran)
    page = await model.adapter.list_orders(all_filter())

    assert placeholder is not None
    assert placeholder.header_complete is False
    assert placeholder.header.order_reference is None
    assert len(placeholder.events) == 1
    assert outran not in {h.order_id for h in page.items}
    assert page.total == 6  # the placeholder is in neither the rows nor the count


# --------------------------------------------------------------------------- what was sent


async def test_every_find_names_the_fields_it_wants_and_no_internal_field_is_among_them(
    model: Fixture,
) -> None:
    order_id = UUID(SAGAS[0].order_id)
    await model.adapter.find_by_id(order_id)
    await model.adapter.find_order_id_by_reference(SAGAS[0].order_reference)
    await model.adapter.list_orders(all_filter())

    finds = model.log.named("find")
    projections = [f["projection"] for f in finds]
    assert projections == [
        {"_id": 0, **dict.fromkeys(DETAIL_FIELDS, 1)},
        {"_id": 0, "orderId": 1},
        {"_id": 0, **dict.fromkeys(SUMMARY_FIELDS, 1)},
    ]
    for projection in projections:
        assert set(projection.values()) <= {0, 1}
        assert projection["_id"] == 0
        assert [k for k, v in projection.items() if v == 0] == ["_id"]  # only `_id` is excluded
        assert not set(INTERNAL) & set(projection)


async def test_the_adapter_sends_only_read_commands_and_no_pipeline_writes(model: Fixture) -> None:
    await model.adapter.find_by_id(UUID(SAGAS[1].order_id))
    await model.adapter.find_order_id_by_reference(SAGAS[1].order_reference)
    await model.adapter.list_orders(all_filter(statuses=("completed",)))

    sent = {name for name, _ in model.log.started_commands}

    assert sent <= {"find", "aggregate", "getMore", "hello", "isMaster", "ping", "endSessions"}, (
        sent
    )
    assert not sent & WRITE_COMMANDS
    for pipeline in model.log.named("aggregate"):
        stages = [next(iter(stage)) for stage in pipeline["pipeline"]]
        assert not {"$out", "$merge"} & set(stages), stages
