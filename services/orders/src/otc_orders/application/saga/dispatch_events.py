"""The dispatch-owed events (`design.md` 7.7; #8's names, a deliberate parity cost): five owed by
facts, and (feature 41) two more, `CreditReleaseOwed` and `OperatorCancelAccepted`.

Published through `scope.dispatcher` strictly AFTER the transaction that enqueued the command
committed, and only when it enqueued one. Each is handled by one `order_sagas` handler, which
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


@dataclass(frozen=True, slots=True)
class CreditReleaseOwed:
    """`credit.release` was enqueued: by `stock.released.v1` at `credit_approved` / `confirmed`, or
    by a late `credit.approved.v1` after an accepted operator cancellation."""

    order_id: UniqueId
    triggering_event_id: UniqueId


@dataclass(frozen=True, slots=True)
class OperatorCancelAccepted:
    """The operator's cancellation was accepted and `stock.release` (reason `order_cancelled`) was
    enqueued. The only dispatch-owed event whose trigger is a request, not a fact: its
    `triggering_event_id` is the request's own id."""

    order_id: UniqueId
    triggering_event_id: UniqueId
