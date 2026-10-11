"""`NatsUpdateSignalPublisher`: the two NATS core publishes that announce a changed document (`R55`,
`PR17`, `PR42`).

* `readmodel.order.updated.<orderId>` carries `openapi.yaml`'s `OrderStreamUpdate`;
  `readmodel.timeline.appended.<orderId>` carries `TimelineStreamEntry` (with `causationId`,
  `PR33`).
  Both are the generated models, serialised by `otc_contracts.to_wire_json` (camelCase, compact,
  non-ASCII raw, `.mmmZ`): no projector-owned signal
  record exists: the contract IS the model.
* Core publish only: no `request`, no `subscribe`, no reply subject, nothing awaiting it. The
  subjects are not in `asyncapi.yaml` (inherited from #7's gate row 2, as #7 and #8 shipped them).
* The status, references, cancellation reason and totals come from the POST-apply document
  (`AppliedDocument`, `PR18`, `PR42`); the event id, instant, type, causation and summary from the
  fact's own entry.
* Every publish gets a NEW headers mapping `{"x-correlation-id": <orderId>}`: a mapping shared
  between two publishes is a mutable value two messages could alias.

A failure to publish propagates from here; the handler logs it and swallows it (`PR19`).
"""

from typing import Protocol
from uuid import UUID

from otc_contracts import to_wire_json
from otc_contracts.generated.openapi import (
    CancellationReason,
    DespatchReference,
    InvoiceReference,
    OrderReferences,
    OrderStatus,
    OrderStreamUpdate,
    OrderTotals,
    PaymentReference,
    TimelineStreamEntry,
)
from otc_projector.application.ports.read_model import AppliedDocument
from otc_projector.application.ports.update_signal import (
    order_updated_subject,
    timeline_appended_subject,
)
from otc_projector.domain.projection_delta import TimelineEntryDelta


class NatsPublisher(Protocol):
    """The one `nats.aio.client.Client` method this adapter calls."""

    async def publish(
        self,
        subject: str,
        payload: bytes = b"",
        reply: str = "",
        headers: dict[str, str] | None = None,
    ) -> None: ...


def order_stream_update(applied: AppliedDocument, entry: TimelineEntryDelta) -> OrderStreamUpdate:
    return OrderStreamUpdate(
        event_id=UUID(entry.event_id),
        order_id=UUID(applied.order_id),
        order_reference=applied.order_reference,
        status=OrderStatus(applied.status),
        cancellation_reason=(
            CancellationReason(applied.cancellation_reason)
            if applied.cancellation_reason is not None
            else None
        ),
        references=OrderReferences(
            despatch_reference=(
                DespatchReference(applied.despatch_reference)
                if applied.despatch_reference is not None
                else None
            ),
            invoice_reference=(
                InvoiceReference(applied.invoice_reference)
                if applied.invoice_reference is not None
                else None
            ),
            payment_reference=(
                PaymentReference(applied.payment_reference)
                if applied.payment_reference is not None
                else None
            ),
        ),
        totals=(
            OrderTotals(
                initial_amount=applied.totals.initial_amount,
                initial_discount=applied.totals.initial_discount,
                total_amount=applied.totals.total_amount,
            )
            if applied.totals is not None
            else None
        ),
        occurred_at=entry.occurred_at,
    )


def timeline_stream_entry(
    applied: AppliedDocument, entry: TimelineEntryDelta
) -> TimelineStreamEntry:
    return TimelineStreamEntry(
        event_id=UUID(entry.event_id),
        causation_id=UUID(entry.causation_id),
        order_id=UUID(applied.order_id),
        order_reference=applied.order_reference,
        event_type=entry.event_type,
        occurred_at=entry.occurred_at,
        summary=entry.summary,
    )


class NatsUpdateSignalPublisher:
    def __init__(self, connection: NatsPublisher) -> None:
        self._connection = connection

    async def publish(self, applied: AppliedDocument, entry: TimelineEntryDelta) -> None:
        updated = to_wire_json(order_stream_update(applied, entry)).encode("utf-8")
        appended = to_wire_json(timeline_stream_entry(applied, entry)).encode("utf-8")
        await self._connection.publish(
            order_updated_subject(applied.order_id),
            updated,
            headers={"x-correlation-id": applied.order_id},
        )
        await self._connection.publish(
            timeline_appended_subject(applied.order_id),
            appended,
            headers={"x-correlation-id": applied.order_id},
        )
