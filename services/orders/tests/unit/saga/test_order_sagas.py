"""The five `order_sagas` handlers, through the dispatcher BUILT BY `composition.py` (task 6.9).

`HandlerRegistry.register_event` accepts zero handlers silently (an event with no listener is not a
boot error), so a missing registration would drop the fast path without failing anything. Publishing
each of the five events through the composition root's own dispatcher is the guard.
"""

import uuid
from typing import Any, cast

import pytest

from otc_orders.application.ports.saga_signal import SagaCommandRef
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.dispatch_events import (
    CreditRejectionRecorded,
    OrderConfirmedBySaga,
    OrderMarkedDespatched,
    OrderMarkedStockReserved,
    OrderPlacedFactRecorded,
)
from otc_orders.application.scope import MissingBindingError, OrdersScope
from otc_orders.composition import build_dispatcher
from otc_shared_kernel import UniqueId

ORDER = UniqueId(uuid.UUID("00000000-0000-4000-8000-000000000001"))
TRIGGER = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000e1"))

EXPECTED = [
    (OrderPlacedFactRecorded, SagaCommandKind.STOCK_RESERVE),
    (OrderMarkedStockReserved, SagaCommandKind.CREDIT_HOLD),
    (CreditRejectionRecorded, SagaCommandKind.STOCK_RELEASE),
    (OrderConfirmedBySaga, SagaCommandKind.DESPATCH_CREATE),
    (OrderMarkedDespatched, SagaCommandKind.INVOICE_ISSUE),
]


class RecordingSignal:
    def __init__(self) -> None:
        self.refs: list[SagaCommandRef] = []

    def signal(self, ref: SagaCommandRef) -> None:
        self.refs.append(ref)


def scope_with(signal: RecordingSignal | None) -> OrdersScope:
    return OrdersScope(
        unit_of_work=cast("Any", object()),
        catalog=cast("Any", object()),
        stock=cast("Any", object()),
        clock=cast("Any", object()),
        saga_signal=signal,
    )


@pytest.mark.parametrize(("event_type", "kind"), EXPECTED, ids=[e.__name__ for e, _ in EXPECTED])
async def test_each_dispatch_owed_event_signals_exactly_its_own_command_through_the_composition_root_dispatcher(  # noqa: E501
    event_type: type, kind: SagaCommandKind
) -> None:
    signal = RecordingSignal()

    await build_dispatcher().publish(
        event_type(order_id=ORDER, triggering_event_id=TRIGGER), scope_with(signal)
    )

    assert signal.refs == [SagaCommandRef(ORDER, kind)]


async def test_the_five_events_together_signal_five_distinct_commands() -> None:
    signal = RecordingSignal()
    dispatcher = build_dispatcher()
    scope = scope_with(signal)

    for event_type, _ in EXPECTED:
        await dispatcher.publish(event_type(order_id=ORDER, triggering_event_id=TRIGGER), scope)

    assert [ref.kind for ref in signal.refs] == [kind for _, kind in EXPECTED]
    assert len({ref.kind for ref in signal.refs}) == 5


async def test_a_scope_with_no_saga_signal_is_refused_not_dropped() -> None:
    with pytest.raises(MissingBindingError) as refused:
        await build_dispatcher().publish(
            OrderPlacedFactRecorded(order_id=ORDER, triggering_event_id=TRIGGER), scope_with(None)
        )

    assert refused.value.binding == "saga_signal"
