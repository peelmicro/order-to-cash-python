"""J3 (R53, PR8, PR9): the placeholder, and what fills it in later."""

import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.integration

ORDER = uuid.UUID("0a0b0c0d-aaaa-4000-8000-0000000000d1")


async def test_r53_creates_a_placeholder_document_keyed_by_correlation_id_and_fills_in_the_header_fields_when_order_placed_is_consumed_later(  # noqa: E501
    read_model: Any, facts: Any
) -> None:
    reserved = facts.build("stock.reserved.v1", correlation_id=ORDER)
    await read_model.apply(reserved)
    placeholder = await read_model.document(ORDER)
    assert placeholder["_id"] == placeholder["orderId"] == str(ORDER)
    assert placeholder["headerComplete"] is False
    assert placeholder["orderReference"] is None
    assert placeholder["status"] == "stock_reserved"
    placed = facts.build("order.placed.v1", correlation_id=ORDER)
    await read_model.apply(placed)
    document = await read_model.document(ORDER)
    assert document["headerComplete"] is True
    assert document["orderReference"] == "ORD-000101"
    assert document["currency"] == "EUR"
    assert document["retailer"]["code"] == "ACME"
    assert document["company"]["code"] == "GLOBEX"
    assert document["totals"] == {
        "initialAmount": 130007,
        "initialDiscount": 5753,
        "totalAmount": 124254,
    }
    assert [i["productCode"] for i in document["items"]] == ["WIDGET-A1", "WIDGET-A2"]
    assert document["status"] == "stock_reserved", "the late order.placed regressed the status"


async def test_pr9_master_data_names_stay_null_in_a_projected_document(
    read_model: Any, facts: Any
) -> None:
    await read_model.apply(facts.build("order.placed.v1", correlation_id=ORDER))
    document = await read_model.document(ORDER)
    for name in ("retailer", "company"):
        assert isinstance(document[name], dict), f"{name} must be an object, not {document[name]!r}"
    for name in ("retailer", "company"):
        assert set(document[name]) == {"code", "name", "gln"}, (
            f"{name} lost keys: {sorted(document[name])}"
        )
    assert document["retailer"]["name"] is None
    assert document["company"]["name"] is None
    assert all(item["name"] is None for item in document["items"])
    assert document["retailer"]["gln"] == "8412345678905"
    assert document["company"]["gln"] == "2022222222227"


async def test_pr8_the_placeholder_holds_every_key_with_nested_objects_of_null_leaves(
    read_model: Any, facts: Any
) -> None:
    await read_model.apply(facts.build("order.confirmed.v1", correlation_id=ORDER))
    document = await read_model.document(ORDER)
    for name in ("retailer", "company", "totals", "references"):
        assert isinstance(document[name], dict), f"{name} must be an object, not {document[name]!r}"
    for name in ("retailer", "company"):
        assert list(document[name]) == ["code", "name", "gln"], name
    assert list(document["totals"]) == ["initialAmount", "initialDiscount", "totalAmount"]
    assert list(document["references"]) == [
        "despatchReference",
        "invoiceReference",
        "paymentReference",
    ]
    # after order.placed, retailer still has all three keys (ledger L13: a null parent would have
    # been REPLACED by `{"code": ...}`, losing `name` and `gln`)
    await read_model.apply(facts.build("order.placed.v1", correlation_id=ORDER))
    after = await read_model.document(ORDER)
    assert list(after["retailer"]) == ["code", "name", "gln"]
    assert list(after["company"]) == ["code", "name", "gln"]
