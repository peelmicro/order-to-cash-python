"""`catalog.reference.list` with no broker and no database: the wire, the query, the route.

Feature 40 has no `R<n>` (`sdd: false`): the specification of record is `asyncapi.yaml`'s
`catalogReferenceList` channel and the feature's two acceptance items. Names say what they prove.
Fixtures are pairwise distinct across fields (a `retailers` list read from the `companies` call, or
a price read from the wrong column, would not go unnoticed).
"""

import ast
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from otc_orders.application.ports.reference_catalog import (
    CurrencyListing,
    PartyListing,
    ProductListing,
)
from otc_orders.application.queries.list_reference_data import (
    ListReferenceDataQuery,
    ListReferenceDataQueryHandler,
    ReferenceKind,
    ReferenceListing,
)
from otc_orders.application.scope import OrdersScope
from otc_orders.composition import build_dispatcher
from otc_orders.presentation import catalog_reference_list as wire
from otc_orders.presentation.orders_create_responder import OrdersCreateResponder
from otc_shared_kernel import Money

NOW = datetime(2026, 10, 12, 9, 0, 0, tzinfo=UTC)

PRODUCT = ProductListing("PRD-1", "5400000000010", "Alpha", "first", Money(1999, "EUR"), True)
RETAILER = PartyListing("RET-1", "Norte", "ES", "ESV1", "4012345000016", "USD", True)
COMPANY = PartyListing("CMP-1", "Rio", "PT", "PTV2", "5412345000013", "JPY", False)
CURRENCY = CurrencyListing("EUR", "978", "EU€", 2)


class RecordingCatalog:
    """Answers the four listings with one distinct row each and records how it was asked."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool | None]] = []

    async def list_products(self, *, include_disabled: bool) -> Sequence[ProductListing]:
        self.calls.append(("products", include_disabled))
        return [PRODUCT]

    async def list_retailers(self, *, include_disabled: bool) -> Sequence[PartyListing]:
        self.calls.append(("retailers", include_disabled))
        return [RETAILER]

    async def list_companies(self, *, include_disabled: bool) -> Sequence[PartyListing]:
        self.calls.append(("companies", include_disabled))
        return [COMPANY]

    async def list_currencies(self) -> Sequence[CurrencyListing]:
        self.calls.append(("currencies", None))
        return [CURRENCY]


def scope_over(catalog: Any) -> OrdersScope:
    return OrdersScope(
        unit_of_work=object(),  # type: ignore[arg-type]
        catalog=catalog,
        stock=object(),  # type: ignore[arg-type]
        clock=object(),  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------------- the request, decoded


def test_an_absent_body_is_the_all_kinds_enabled_only_request() -> None:
    query = wire.to_query(wire.decode_request(b""))

    assert query.kinds == frozenset(ReferenceKind)
    assert len(query.kinds) == 4
    assert query.include_disabled is False


def test_an_empty_object_is_the_all_kinds_enabled_only_request() -> None:
    query = wire.to_query(wire.decode_request(b"{}"))

    assert (query.kinds, query.include_disabled) == (frozenset(ReferenceKind), False)


def test_the_kinds_field_reaches_the_query() -> None:
    query = wire.to_query(wire.decode_request(b'{"kinds":["retailers","currencies"]}'))

    assert query.kinds == {ReferenceKind.RETAILERS, ReferenceKind.CURRENCIES}


def test_include_disabled_true_reaches_the_query() -> None:
    query = wire.to_query(wire.decode_request(b'{"includeDisabled":true}'))

    assert query.include_disabled is True


def test_include_disabled_null_is_false() -> None:
    assert wire.to_query(wire.decode_request(b'{"includeDisabled":null}')).include_disabled is False


@pytest.mark.parametrize(
    "body",
    [
        b'{"kinds":[]}',  # minItems 1
        b'{"kinds":["gadgets"]}',  # outside the enum
        b'{"kinds":"products"}',  # not a list
        b'{"includeDisabled":"yes"}',  # strict boolean
        b'{"includeDisabled":1}',  # strict boolean
        b"[]",  # not an object
        b"null",
        b"not json",
    ],
)
def test_a_request_the_schema_refuses_is_a_validation_failure_not_an_internal_error(
    body: bytes,
) -> None:
    with pytest.raises(wire.InvalidCatalogReferenceListRequestError):
        wire.decode_request(body)


# --------------------------------------------------------------------------------- the query


@pytest.mark.parametrize("kind", list(ReferenceKind))
async def test_only_the_requested_collection_is_read_and_the_others_stay_none(
    kind: ReferenceKind,
) -> None:
    catalog = RecordingCatalog()
    handler = ListReferenceDataQueryHandler(scope_over(catalog))

    listing = await handler.handle(
        ListReferenceDataQuery(frozenset({kind}), include_disabled=False)
    )

    assert [name for name, _ in catalog.calls] == [kind.value], f"{kind.value} alone was requested"
    present = {
        name
        for name in ("products", "retailers", "companies", "currencies")
        if getattr(listing, name) is not None
    }
    assert present == {kind.value}


async def test_every_kind_asked_for_is_read_once() -> None:
    catalog = RecordingCatalog()
    handler = ListReferenceDataQueryHandler(scope_over(catalog))

    listing = await handler.handle(
        ListReferenceDataQuery(frozenset(ReferenceKind), include_disabled=False)
    )

    assert sorted(kind for kind, _ in catalog.calls) == [
        "companies",
        "currencies",
        "products",
        "retailers",
    ]
    assert listing == ReferenceListing((PRODUCT,), (RETAILER,), (COMPANY,), (CURRENCY,))


@pytest.mark.parametrize("include_disabled", [False, True])
async def test_include_disabled_reaches_every_listing_that_has_the_notion(
    include_disabled: bool,
) -> None:
    catalog = RecordingCatalog()
    handler = ListReferenceDataQueryHandler(scope_over(catalog))

    await handler.handle(
        ListReferenceDataQuery(frozenset(ReferenceKind), include_disabled=include_disabled)
    )

    asked = dict(catalog.calls)
    assert (asked["products"], asked["retailers"], asked["companies"]) == (include_disabled,) * 3
    assert asked["currencies"] is None  # a currency has no `disabled_at`


async def test_the_wire_flag_reaches_the_catalog_through_the_built_dispatcher() -> None:
    """The end of D1 inside the process: request bytes -> decode -> query -> REGISTERED handler ->
    the catalog's keyword argument."""
    catalog = RecordingCatalog()
    dispatcher = build_dispatcher()

    query = wire.to_query(wire.decode_request(b'{"kinds":["companies"],"includeDisabled":true}'))
    await dispatcher.ask(query, scope_over(catalog))

    assert catalog.calls == [("companies", True)]


# ------------------------------------------------------------------------------- the reply


def reply_document(listing: ReferenceListing) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(wire.encode(wire.to_reply(listing)))
    return document


def test_the_reply_carries_each_field_of_each_row_in_camel_case_with_integer_money() -> None:
    document = reply_document(ReferenceListing((PRODUCT,), (RETAILER,), (COMPANY,), (CURRENCY,)))

    assert document == {
        "products": [
            {
                "code": "PRD-1",
                "ean": "5400000000010",
                "name": "Alpha",
                "description": "first",
                "price": 1999,
                "currency": "EUR",
                "enabled": True,
            }
        ],
        "retailers": [
            {
                "code": "RET-1",
                "name": "Norte",
                "country": "ES",
                "vat": "ESV1",
                "gln": "4012345000016",
                "currency": "USD",
                "enabled": True,
            }
        ],
        "companies": [
            {
                "code": "CMP-1",
                "name": "Rio",
                "country": "PT",
                "vat": "PTV2",
                "gln": "5412345000013",
                "currency": "JPY",
                "enabled": False,
            }
        ],
        "currencies": [{"code": "EUR", "isoNumber": "978", "symbol": "EU€", "decimalPoints": 2}],
    }
    assert type(document["products"][0]["price"]) is int


def test_the_reply_is_compact_json_with_non_ascii_written_raw() -> None:
    body = wire.encode(wire.to_reply(ReferenceListing(currencies=(CURRENCY,))))

    assert (
        body
        == (
            '{"currencies":[{"code":"EUR","isoNumber":"978","symbol":"EU€","decimalPoints":2}]}'
        ).encode()
    )


def test_a_collection_that_was_not_asked_for_is_absent_and_an_empty_one_is_an_empty_list() -> None:
    assert reply_document(ReferenceListing(products=())) == {"products": []}


# --------------------------------------------------------------------------- the responder


class FakeMessage:
    def __init__(self, data: bytes, reply: str = "_INBOX.x") -> None:
        self.data = data
        self.reply = reply
        self.replies: list[bytes] = []
        self.answered = asyncio.Event()

    async def respond(self, data: bytes) -> None:
        self.replies.append(data)
        self.answered.set()


class FakeSubscription:
    def __init__(self) -> None:
        self.unsubscribed = 0

    async def unsubscribe(self) -> None:
        self.unsubscribed += 1


class FakeConnection:
    def __init__(self) -> None:
        self.subscribed: list[tuple[str, str]] = []
        self.callbacks: dict[str, Any] = {}
        self.subscriptions: list[FakeSubscription] = []
        self.flushes: list[int] = []

    async def subscribe(self, subject: str, queue: str, cb: Any) -> FakeSubscription:
        self.subscribed.append((subject, queue))
        self.callbacks[subject] = cb
        self.subscriptions.append(FakeSubscription())
        return self.subscriptions[-1]

    async def flush(self) -> None:
        self.flushes.append(len(self.subscribed))


class FakeClock:
    def now(self) -> datetime:
        return NOW


async def serve(body: bytes, catalog: Any) -> dict[str, Any]:
    connection = FakeConnection()
    responder = OrdersCreateResponder(
        connection=connection,  # type: ignore[arg-type]
        dispatcher=build_dispatcher(),
        scope_factory=lambda: scope_over(catalog),
        clock=FakeClock(),
    )
    await responder.start()
    stop = asyncio.Event()
    task = asyncio.create_task(responder.run(stop))
    message = FakeMessage(body)
    await connection.callbacks["catalog.reference.list"](message)
    async with asyncio.timeout(5):
        await message.answered.wait()
    stop.set()
    await task
    [reply] = message.replies
    document: dict[str, Any] = json.loads(reply)
    return document


async def test_the_responder_subscribes_both_subjects_in_the_queue_group_and_flushes_after() -> (
    None
):
    connection = FakeConnection()
    responder = OrdersCreateResponder(
        connection=connection,  # type: ignore[arg-type]
        dispatcher=build_dispatcher(),
        scope_factory=lambda: scope_over(RecordingCatalog()),
        clock=FakeClock(),
    )

    await responder.start()

    assert connection.subscribed == [
        ("orders.create", "otc-orders"),
        ("catalog.reference.list", "otc-orders"),
        ("orders.cancel", "otc-orders"),  # feature 41: the third subject, same task and group
    ]
    assert connection.flushes == [3]  # one flush, after the LAST subscribe


async def test_the_responder_answers_a_catalog_request_with_the_listing() -> None:
    catalog = RecordingCatalog()

    document = await serve(b'{"kinds":["products"],"includeDisabled":true}', catalog)

    assert document["products"][0]["price"] == 1999
    assert set(document) == {"products"}
    assert catalog.calls == [("products", True)]


@pytest.mark.parametrize("body", [b'{"kinds":["gadgets"]}', b'{"kinds":[]}', b"not json"])
async def test_a_malformed_catalog_request_is_answered_with_validation_failed(body: bytes) -> None:
    catalog = RecordingCatalog()

    document = await serve(body, catalog)

    assert document["code"] == "VALIDATION_FAILED"
    assert document["occurredAt"] == "2026-10-12T09:00:00.000Z"
    assert catalog.calls == []  # nothing was read for a refused request


class ExplodingCatalog(RecordingCatalog):
    async def list_products(self, *, include_disabled: bool) -> Sequence[ProductListing]:
        raise RuntimeError("password=hunter2 at /srv/secret")


async def test_a_failing_read_is_answered_with_internal_error_that_carries_no_internal_text() -> (
    None
):
    document = await serve(b'{"kinds":["products"]}', ExplodingCatalog())

    assert document["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in json.dumps(document)


# ------------------------------------------------------------- one adapter, constructed once

SRC = Path(__file__).resolve().parents[2] / "src" / "otc_orders"


def constructions_of(name: str, source: str) -> int:
    """Call sites of `name(...)` (a plain or an attribute reference) in `source`."""
    return sum(
        1
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    )


def test_the_reference_catalog_adapter_is_constructed_once_and_only_by_the_composition_root() -> (
    None
):
    """The listing and place-order read through ONE adapter: the root builds it once and binds it
    into every scope, and no handler builds a catalog of its own (#7 `app.module.ts:134-137`
    `useExisting`; #8 `CatalogReferenceListPortReuseTests`)."""
    found = {
        str(path.relative_to(SRC)): count
        for path in sorted(SRC.rglob("*.py"))
        if (count := constructions_of("SqlAlchemyReferenceCatalog", path.read_text("utf-8")))
    }

    assert found == {"composition.py": 1}


def test_the_construction_counter_sees_a_second_construction_and_an_attribute_form() -> None:
    assert constructions_of("SqlAlchemyReferenceCatalog", "a = SqlAlchemyReferenceCatalog(s)") == 1
    assert (
        constructions_of("SqlAlchemyReferenceCatalog", "a = m.SqlAlchemyReferenceCatalog(s)") == 1
    )
    assert (
        constructions_of(
            "SqlAlchemyReferenceCatalog", "a = Other(s)  # SqlAlchemyReferenceCatalog(s)"
        )
        == 0
    )
