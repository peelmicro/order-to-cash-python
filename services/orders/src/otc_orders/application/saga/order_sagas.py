"""The five `order_sagas` event handlers (`design.md` 7.7; #7's file name).

Each does one thing: signal its own command to the fast path and return. `signal` never blocks and
never raises, so the dispatcher's `publish` (which awaits each handler in turn) returns at once.
"""

from otc_orders.application.ports.saga_signal import SagaCommandRef, SagaCommandSignal
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.dispatch_events import (
    CreditRejectionRecorded,
    OrderConfirmedBySaga,
    OrderMarkedDespatched,
    OrderMarkedStockReserved,
    OrderPlacedFactRecorded,
)


class OrderPlacedSaga:
    def __init__(self, signal: SagaCommandSignal) -> None:
        self._signal = signal

    async def handle(self, event: OrderPlacedFactRecorded, /) -> None:
        self._signal.signal(SagaCommandRef(event.order_id, SagaCommandKind.STOCK_RESERVE))


class StockReservedSaga:
    def __init__(self, signal: SagaCommandSignal) -> None:
        self._signal = signal

    async def handle(self, event: OrderMarkedStockReserved, /) -> None:
        self._signal.signal(SagaCommandRef(event.order_id, SagaCommandKind.CREDIT_HOLD))


class CreditRejectedSaga:
    def __init__(self, signal: SagaCommandSignal) -> None:
        self._signal = signal

    async def handle(self, event: CreditRejectionRecorded, /) -> None:
        self._signal.signal(SagaCommandRef(event.order_id, SagaCommandKind.STOCK_RELEASE))


class CreditApprovedSaga:
    def __init__(self, signal: SagaCommandSignal) -> None:
        self._signal = signal

    async def handle(self, event: OrderConfirmedBySaga, /) -> None:
        self._signal.signal(SagaCommandRef(event.order_id, SagaCommandKind.DESPATCH_CREATE))


class OrderDespatchedSaga:
    def __init__(self, signal: SagaCommandSignal) -> None:
        self._signal = signal

    async def handle(self, event: OrderMarkedDespatched, /) -> None:
        self._signal.signal(SagaCommandRef(event.order_id, SagaCommandKind.INVOICE_ISSUE))
