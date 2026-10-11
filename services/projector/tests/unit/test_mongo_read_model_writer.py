"""E2 (PR6, PR7, PR42, ledger L3, L24, L25): the writer's two operations over a FAKE collection.

The fake records the arguments it received, so the driver defaults that a deletion probe cannot see
are asserted on the call itself: `upsert=True` (the default is `False`) and
`return_document=ReturnDocument.AFTER` (the default is `BEFORE`). The retry of the first operation
is proven to happen exactly once and ONLY there.
"""

from typing import Any, cast

import pytest
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, OperationFailure

from otc_projector.application.outcome import ProjectionOutcome
from otc_projector.application.ports.read_model import AppliedDocument
from otc_projector.application.projection import project
from otc_projector.infrastructure.messaging.idempotent_consumer import IdempotentConsumer
from otc_projector.infrastructure.persistence.mongo_read_model_writer import MongoReadModelWriter

ID_CONFLICT = DuplicateKeyError(
    "E11000 duplicate key error collection: x.order_timeline index: _id_ dup key",
    11000,
    {"keyPattern": {"_id": 1}},
)
REFERENCE_CONFLICT = DuplicateKeyError(
    "E11000 duplicate key error collection: x.order_timeline index: uq_order_reference dup key",
    11000,
    {"keyPattern": {"orderReference": 1}},
)
POST_APPLY = {
    "_id": "order-1",
    "status": "confirmed",
    "orderReference": "ORD-000777",
    "cancellationReason": None,
    "totals": {"initialAmount": 11, "initialDiscount": 22, "totalAmount": 33},
    "references": {"despatchReference": None, "invoiceReference": "INV-000777"},
}


class FakeCollection:
    def __init__(self) -> None:
        self.update_errors: list[Exception] = []
        self.apply_error: Exception | None = None
        self.apply_result: dict[str, Any] | None = POST_APPLY
        self.updates: list[tuple[Any, Any, dict[str, Any]]] = []
        self.applies: list[tuple[Any, Any, dict[str, Any]]] = []

    async def update_one(self, filter_: Any, update: Any, **options: Any) -> None:
        self.updates.append((filter_, update, options))
        if self.update_errors:
            raise self.update_errors.pop(0)

    async def find_one_and_update(
        self, filter_: Any, update: Any, **options: Any
    ) -> dict[str, Any] | None:
        self.applies.append((filter_, update, options))
        if self.apply_error is not None:
            raise self.apply_error
        return self.apply_result


def writer_over(fake: FakeCollection) -> MongoReadModelWriter:
    collection = cast("Any", fake)
    return MongoReadModelWriter(collection, IdempotentConsumer(collection))


class Callback:
    def __init__(self) -> None:
        self.documents: list[AppliedDocument] = []

    async def __call__(self, document: AppliedDocument) -> None:
        self.documents.append(document)


async def test_pr7_the_first_operation_is_retried_exactly_once_on_an_id_duplicate_key(
    facts: Any,
) -> None:
    fake = FakeCollection()
    fake.update_errors = [ID_CONFLICT]
    callback = Callback()
    outcome = await writer_over(fake).apply(
        project(facts.build("order.placed.v1")), after_applied=callback
    )
    assert outcome is ProjectionOutcome.PROCESSED
    assert len(fake.updates) == 2, "the lost upsert race must be retried exactly once"
    assert len(fake.applies) == 1
    assert fake.updates[0] == fake.updates[1], "the retry is the same operation"


async def test_pr7_a_second_id_duplicate_key_propagates_after_exactly_one_retry(facts: Any) -> None:
    fake = FakeCollection()
    fake.update_errors = [ID_CONFLICT, ID_CONFLICT]
    with pytest.raises(DuplicateKeyError):
        await writer_over(fake).apply(
            project(facts.build("order.placed.v1")), after_applied=Callback()
        )
    assert len(fake.updates) == 2, "more than one retry happened"
    assert fake.applies == [], "the apply ran after a failed first operation"


async def test_pr7_a_duplicate_key_on_another_index_in_the_first_operation_is_not_retried(
    facts: Any,
) -> None:
    fake = FakeCollection()
    fake.update_errors = [REFERENCE_CONFLICT]
    with pytest.raises(DuplicateKeyError):
        await writer_over(fake).apply(
            project(facts.build("order.placed.v1")), after_applied=Callback()
        )
    assert len(fake.updates) == 1


async def test_pr7_any_other_first_operation_error_propagates_unretried(facts: Any) -> None:
    fake = FakeCollection()
    fake.update_errors = [OperationFailure("not primary", 10107)]
    with pytest.raises(OperationFailure):
        await writer_over(fake).apply(
            project(facts.build("order.placed.v1")), after_applied=Callback()
        )
    assert len(fake.updates) == 1
    assert fake.applies == []


async def test_pr7_a_duplicate_key_in_the_second_operation_propagates_unretried(facts: Any) -> None:
    fake = FakeCollection()
    fake.apply_error = ID_CONFLICT
    callback = Callback()
    with pytest.raises(DuplicateKeyError):
        await writer_over(fake).apply(
            project(facts.build("order.placed.v1")), after_applied=callback
        )
    assert len(fake.updates) == 1, "the first operation was repeated"
    assert len(fake.applies) == 1, "the second operation was retried"
    assert callback.documents == []


async def test_pr6_pr42_the_arguments_the_driver_received_are_upsert_true_and_return_document_after(
    facts: Any,
) -> None:
    fake = FakeCollection()
    delta = project(facts.build("order.confirmed.v1"))
    await writer_over(fake).apply(delta, after_applied=Callback())
    _, _, update_options = fake.updates[0]
    assert update_options == {"upsert": True}, "the first operation must upsert"
    apply_filter, _, apply_options = fake.applies[0]
    assert apply_options == {"return_document": ReturnDocument.AFTER}
    assert apply_filter == {
        "_id": delta.order_id,
        "processedEventKeys": {"$ne": f"projector:{delta.entry.event_id}"},
    }


async def test_pr6_a_suppressed_redelivery_is_a_duplicate_and_runs_no_callback(facts: Any) -> None:
    fake = FakeCollection()
    fake.apply_result = None
    callback = Callback()
    outcome = await writer_over(fake).apply(
        project(facts.build("order.confirmed.v1")), after_applied=callback
    )
    assert outcome is ProjectionOutcome.DUPLICATE
    assert callback.documents == []


async def test_pr42_the_callback_receives_the_typed_post_apply_document(facts: Any) -> None:
    fake = FakeCollection()
    callback = Callback()
    await writer_over(fake).apply(
        project(facts.build("order.confirmed.v1")), after_applied=callback
    )
    assert callback.documents == [
        AppliedDocument(
            order_id="order-1",
            order_reference="ORD-000777",
            status="confirmed",
            cancellation_reason=None,
            despatch_reference=None,
            invoice_reference="INV-000777",
            payment_reference=None,
            totals=callback.documents[0].totals,
        )
    ]
    totals = callback.documents[0].totals
    assert totals is not None
    assert (totals.initial_amount, totals.initial_discount, totals.total_amount) == (11, 22, 33)


async def test_pr8_a_placeholder_post_apply_document_has_no_totals(facts: Any) -> None:
    fake = FakeCollection()
    fake.apply_result = {
        **POST_APPLY,
        "totals": {"initialAmount": None, "initialDiscount": None, "totalAmount": None},
    }
    callback = Callback()
    await writer_over(fake).apply(
        project(facts.build("order.confirmed.v1")), after_applied=callback
    )
    assert callback.documents[0].totals is None
