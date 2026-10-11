"""`dispatch`: the ONE unit every notify handler delegates to (R17, R18).

Record-first, then send, then forget-on-throw: the divergence from the canonical pattern, and why.
The canonical idempotent consumer writes the dedup row and the handler's effects in ONE
transaction because both are database writes. An email is not a database write and cannot be
enrolled in that transaction, and holding a transaction (and its connection and the unique
index's row lock) open across a slow, unpredictable network call is wrong on its own merits. So:

1. `ledger.record(event_id)` commits the dedup row as its own short transaction (the canonical
   `IdempotentConsumer` runs with a no-op `work`: the INSERT alone is the whole effect).
   A `DUPLICATE` returns here: no render, no send, no second row.
2. The message is rendered and handed to the bound `NotificationSender`, outside any transaction.
3. If the send raises, `ledger.forget(event_id)` removes the row before the error propagates, so
   the redelivery (the offset is not committed for a raising handler) gets a genuinely fresh
   attempt.

What each failure produces. A crash STRICTLY BETWEEN step 1 committing and the send being
attempted turns into "possibly lose one email", never "duplicate an email": the direction
`domain-model.md` section 6's "one delivery per `(eventId, consumer)`" points, and the opposite of
mark-after-send, which would re-run the SMTP call on every redelivery after a successful send whose
offset commit lagged. A crash between a successful send and the offset commit is absorbed by step
1 on the redelivery. #7 (`notification-dispatch.service.ts`) and #8
(`NotificationDispatchService.cs`) chose the same order for the same reason.

A failing compensation never masks the original send error: it is logged with the identifiers
needed to clear the orphaned row by hand, and the ORIGINAL error is what propagates.
"""

import dataclasses
import logging
from collections.abc import Callable
from uuid import UUID

from otc_notifications.application.ports.delivery_ledger import LedgerOutcome
from otc_notifications.application.ports.notification_sender import NotificationMessage
from otc_notifications.application.scope import NotificationsScope

log = logging.getLogger("otc_notifications.dispatch")


async def dispatch(
    scope: NotificationsScope, event_id: UUID, build: Callable[[], NotificationMessage]
) -> LedgerOutcome:
    outcome = await scope.ledger.record(event_id)
    if outcome is LedgerOutcome.DUPLICATE:
        # R18: acknowledged with no mutation, no second ledger row and no send. `build` is never
        # invoked on this path.
        return outcome

    message = dataclasses.replace(build(), message_id=f"{event_id}@order-to-cash")
    try:
        await scope.sender.send(message)
    except BaseException as send_error:
        try:
            await scope.ledger.forget(event_id)
        except Exception:
            log.exception(
                "compensating delete failed after a failed send: the ledger row is orphaned and "
                "must be cleared by hand",
                extra={"eventId": str(event_id), "sendError": repr(send_error)},
            )
        raise
    return outcome
