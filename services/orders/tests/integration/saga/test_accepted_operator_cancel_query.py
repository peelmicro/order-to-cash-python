# ruff: noqa: E501 - test names are the sentences the acceptance items use
"""`find_accepted_operator_cancel` against a REAL PostgreSQL (#8 id 91; #7 `c20bdc0`).

The query decides whether an operator cancellation was accepted for an order: the order's
`stock.release` row whose request carries the reason `order_cancelled`. It is the premise of the late
credit approval's branch and the source of the operator's note. #7 and #8 each guarded it first with
a fake and found, against a real database, a query that answered for the wrong row. A fake shares
the code's assumption of the schema; this file does not.

THE SHAPE OF THE CASES. A false negative of a substituted identifier is "no row matched", so every
case that expects NOTHING is run with a DECOY ROW PRESENT that differs from the accepted shape in
exactly one identifier: the order, the command, the reason. A "no accepted cancel" answered from an
empty table would stay green under all three substitutions. The positive cases carry decoys too, so
the note returned is the target's own.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg
import pytest

from otc_orders.application.ports.saga_command_store import AcceptedOperatorCancel, OwedCommand
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_shared_kernel import UniqueId

OrderAt = Callable[..., Awaitable[Order]]


def payload(order: Order, reason: str | None) -> str:
    body: dict[str, str] = {"orderReference": order.order_reference.value}
    if reason is not None:
        body["reason"] = reason
    return json.dumps(body, separators=(",", ":"))


async def plant(
    uow: SqlAlchemyUnitOfWork,
    order: Order,
    kind: SagaCommandKind,
    reason: str | None,
    *,
    note: str | None = None,
) -> None:
    async with uow.begin() as tx:
        await tx.saga_commands.enqueue(
            OwedCommand(
                order_id=order.id,
                order_reference=order.order_reference.value,
                kind=kind,
                payload=payload(order, reason),
                triggering_event_id=UniqueId.new(),
                operator_note=note,
            )
        )


async def accepted(uow: SqlAlchemyUnitOfWork, order: Order) -> AcceptedOperatorCancel | None:
    async with uow.begin() as tx:
        return await tx.saga_commands.find_accepted_operator_cancel(order.id)


async def test_an_accepted_cancel_is_found_with_its_own_note_among_decoys_of_every_kind(
    uow: SqlAlchemyUnitOfWork, order_at: OrderAt
) -> None:
    target = await order_at(OrderStatus.STOCK_RESERVED)
    sibling = await order_at(OrderStatus.STOCK_RESERVED)
    await plant(
        uow, sibling, SagaCommandKind.STOCK_RELEASE, "order_cancelled", note="the sibling's note"
    )
    await plant(
        uow, target, SagaCommandKind.CREDIT_RELEASE, "order_cancelled", note="credit's decoy note"
    )
    await plant(
        uow, target, SagaCommandKind.STOCK_RELEASE, "order_cancelled", note="the target's note"
    )

    assert await accepted(uow, target) == AcceptedOperatorCancel(note="the target's note")
    assert await accepted(uow, sibling) == AcceptedOperatorCancel(note="the sibling's note")


async def test_an_accepted_cancel_without_a_note_is_found_with_no_note(
    uow: SqlAlchemyUnitOfWork, order_at: OrderAt
) -> None:
    target = await order_at(OrderStatus.CONFIRMED)
    await plant(uow, target, SagaCommandKind.STOCK_RELEASE, "order_cancelled")

    result = await accepted(uow, target)

    assert result is not None, "an accepted cancel with no note is still an accepted cancel"
    assert result.note is None


async def test_a_note_starting_with_a_dollar_sign_with_quotes_and_non_ascii_comes_back_byte_for_byte(
    uow: SqlAlchemyUnitOfWork, order_at: OrderAt
) -> None:
    target = await order_at(OrderStatus.STOCK_RESERVED)
    note = "$set: {\"a\": 1} 'quoted' — café €"
    await plant(uow, target, SagaCommandKind.STOCK_RELEASE, "order_cancelled", note=note)

    assert await accepted(uow, target) == AcceptedOperatorCancel(note=note)


@pytest.mark.parametrize("status", ["pending", "sent", "parked", "rejected"])
async def test_a_row_in_any_status_still_means_the_cancel_was_requested(
    status: str, uow: SqlAlchemyUnitOfWork, order_at: OrderAt, migrated_db: Any
) -> None:
    target = await order_at(OrderStatus.STOCK_RESERVED)
    await plant(uow, target, SagaCommandKind.STOCK_RELEASE, "order_cancelled", note="n")
    connection = await asyncpg.connect(migrated_db.dsn)
    try:
        await connection.execute(
            "UPDATE saga_commands SET status = $1 WHERE order_id = $2", status, target.id.value
        )
    finally:
        await connection.close()

    assert await accepted(uow, target) == AcceptedOperatorCancel(note="n"), status


async def test_with_no_row_at_all_nothing_is_accepted(
    uow: SqlAlchemyUnitOfWork, order_at: OrderAt
) -> None:
    assert await accepted(uow, await order_at(OrderStatus.STOCK_RESERVED)) is None


# Each decoy differs from the accepted shape (order, `stock.release`, `order_cancelled`) in EXACTLY
# one identifier. The row is planted for `target` (the command and the reason) or for `sibling`
# (the order); the question is always asked about `target`.
DECOYS: dict[str, tuple[bool, SagaCommandKind, str | None]] = {
    "another order": (False, SagaCommandKind.STOCK_RELEASE, "order_cancelled"),
    "another command, same reason in its request": (
        True,
        SagaCommandKind.CREDIT_RELEASE,
        "order_cancelled",
    ),
    "another command, a real despatch request": (True, SagaCommandKind.DESPATCH_CREATE, None),
    "another reason, the saga's own credit_rejected release": (
        True,
        SagaCommandKind.STOCK_RELEASE,
        "credit_rejected",
    ),
    "the same command with no reason in its request": (True, SagaCommandKind.STOCK_RELEASE, None),
}


@pytest.mark.parametrize("decoy", list(DECOYS))
async def test_a_decoy_differing_in_one_identifier_is_not_an_accepted_cancel(
    decoy: str, uow: SqlAlchemyUnitOfWork, order_at: OrderAt
) -> None:
    target = await order_at(OrderStatus.STOCK_RESERVED)
    sibling = await order_at(OrderStatus.STOCK_RESERVED)
    for_target, kind, reason = DECOYS[decoy]
    await plant(uow, target if for_target else sibling, kind, reason, note="a decoy's note")

    assert await accepted(uow, target) is None, f"decoy ({decoy}) was taken for an accepted cancel"


async def test_every_decoy_at_once_is_still_not_an_accepted_cancel(
    uow: SqlAlchemyUnitOfWork, order_at: OrderAt
) -> None:
    target = await order_at(OrderStatus.STOCK_RESERVED)
    sibling = await order_at(OrderStatus.STOCK_RESERVED)
    await plant(uow, sibling, SagaCommandKind.STOCK_RELEASE, "order_cancelled", note="s")
    await plant(uow, target, SagaCommandKind.CREDIT_RELEASE, "order_cancelled", note="c")
    await plant(uow, target, SagaCommandKind.DESPATCH_CREATE, None)

    assert await accepted(uow, target) is None

    await plant(uow, target, SagaCommandKind.STOCK_RELEASE, "credit_rejected", note="r")

    assert await accepted(uow, target) is None
