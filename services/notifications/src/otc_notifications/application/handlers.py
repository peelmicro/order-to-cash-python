"""The seven notify handlers, one line each: render the fact's template and `dispatch` it.

Registered one statement each in `composition.register_handlers`. Each closes over its own
template, so a copy-paste of the wrong template fails the same guard a deleted dispatch would.
"""

from otc_notifications.application.dispatch import dispatch
from otc_notifications.application.messages import (
    NotifyInvoiceIssuedCommand,
    NotifyOrderCancelledCommand,
    NotifyOrderCompletedCommand,
    NotifyOrderConfirmedCommand,
    NotifyOrderDespatchedCommand,
    NotifyOrderPlacedCommand,
    NotifyPaymentReceivedCommand,
)
from otc_notifications.application.scope import NotificationsScope
from otc_notifications.application.templates.invoice_issued import render_invoice_issued
from otc_notifications.application.templates.order_cancelled import render_order_cancelled
from otc_notifications.application.templates.order_completed import render_order_completed
from otc_notifications.application.templates.order_confirmed import render_order_confirmed
from otc_notifications.application.templates.order_despatched import render_order_despatched
from otc_notifications.application.templates.order_placed import render_order_placed
from otc_notifications.application.templates.payment_received import render_payment_received


class NotifyOrderPlacedHandler:
    def __init__(self, scope: NotificationsScope) -> None:
        self._scope = scope

    async def handle(self, command: NotifyOrderPlacedCommand, /) -> None:
        event = command.event
        await dispatch(self._scope, event.event_id, lambda: render_order_placed(event))


class NotifyOrderConfirmedHandler:
    def __init__(self, scope: NotificationsScope) -> None:
        self._scope = scope

    async def handle(self, command: NotifyOrderConfirmedCommand, /) -> None:
        event = command.event
        await dispatch(self._scope, event.event_id, lambda: render_order_confirmed(event))


class NotifyOrderDespatchedHandler:
    def __init__(self, scope: NotificationsScope) -> None:
        self._scope = scope

    async def handle(self, command: NotifyOrderDespatchedCommand, /) -> None:
        event = command.event
        await dispatch(self._scope, event.event_id, lambda: render_order_despatched(event))


class NotifyInvoiceIssuedHandler:
    def __init__(self, scope: NotificationsScope) -> None:
        self._scope = scope

    async def handle(self, command: NotifyInvoiceIssuedCommand, /) -> None:
        event = command.event
        await dispatch(self._scope, event.event_id, lambda: render_invoice_issued(event))


class NotifyPaymentReceivedHandler:
    def __init__(self, scope: NotificationsScope) -> None:
        self._scope = scope

    async def handle(self, command: NotifyPaymentReceivedCommand, /) -> None:
        event = command.event
        await dispatch(self._scope, event.event_id, lambda: render_payment_received(event))


class NotifyOrderCompletedHandler:
    def __init__(self, scope: NotificationsScope) -> None:
        self._scope = scope

    async def handle(self, command: NotifyOrderCompletedCommand, /) -> None:
        event = command.event
        await dispatch(self._scope, event.event_id, lambda: render_order_completed(event))


class NotifyOrderCancelledHandler:
    def __init__(self, scope: NotificationsScope) -> None:
        self._scope = scope

    async def handle(self, command: NotifyOrderCancelledCommand, /) -> None:
        event = command.event
        await dispatch(self._scope, event.event_id, lambda: render_order_cancelled(event))
