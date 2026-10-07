"""The five dispatch-owed events (`design.md` 7.7; #8's names, a deliberate parity cost).

Published through `scope.dispatcher` strictly AFTER the fact's transaction committed, and only for a
fact that was processed and enqueued a command. Each is handled by one `order_sagas` handler, which
signals the fast path. (`OrderConfirmedBySaga`, not #7's `OrderConfirmed`: the domain event of that
name exists.)
"""

from dataclasses import dataclass

from otc_shared_kernel import UniqueId


@dataclass(frozen=True, slots=True)
class OrderPlacedFactRecorded:
    order_id: UniqueId
    triggering_event_id: UniqueId


@dataclass(frozen=True, slots=True)
class OrderMarkedStockReserved:
    order_id: UniqueId
    triggering_event_id: UniqueId


@dataclass(frozen=True, slots=True)
class CreditRejectionRecorded:
    order_id: UniqueId
    triggering_event_id: UniqueId


@dataclass(frozen=True, slots=True)
class OrderConfirmedBySaga:
    order_id: UniqueId
    triggering_event_id: UniqueId


@dataclass(frozen=True, slots=True)
class OrderMarkedDespatched:
    order_id: UniqueId
    triggering_event_id: UniqueId
