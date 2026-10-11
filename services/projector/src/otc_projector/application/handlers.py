"""`ProjectFactHandler`: project the fact, apply it, then announce it.

The handler never branches on `eventType` (`PR27`): `project` holds the fourteen variations. It
hands the writer a post-apply callback, which is where the update signal is published, so a
suppressed redelivery (`DUPLICATE`) publishes nothing by construction (`PR18`).

THE one place a publication failure is caught (`PR19`): the apply already happened, so a redelivery
would be suppressed and could never re-emit; the failure is logged with both subjects and swallowed,
and the fact is committed. A boot that cannot reach NATS fails earlier (`PR45`), so this is the
runtime-outage path only. `asyncio.CancelledError` is a `BaseException` and is never caught here.
"""

import logging

from otc_projector.application.messages import ProjectFactCommand
from otc_projector.application.outcome import ProjectionOutcome
from otc_projector.application.ports.read_model import AppliedDocument
from otc_projector.application.ports.update_signal import (
    order_updated_subject,
    timeline_appended_subject,
)
from otc_projector.application.projection import project
from otc_projector.application.scope import ProjectorScope
from otc_projector.domain.projection_delta import ProjectionDelta

log = logging.getLogger("otc_projector.application.handlers")


class ProjectFactHandler:
    def __init__(self, scope: ProjectorScope) -> None:
        self._scope = scope

    async def handle(self, command: ProjectFactCommand, /) -> ProjectionOutcome:
        delta = project(command.event)

        async def announce(applied: AppliedDocument) -> None:
            await self._announce(delta, applied)

        return await self._scope.read_model.apply(delta, after_applied=announce)

    async def _announce(self, delta: ProjectionDelta, applied: AppliedDocument) -> None:
        try:
            await self._scope.signals.publish(applied, delta.entry)
        except Exception:
            updated = order_updated_subject(delta.order_id)
            appended = timeline_appended_subject(delta.order_id)
            log.exception(
                "the update signal could not be published on %s and %s; "
                "the fact is applied and committed",
                updated,
                appended,
                extra={"eventId": delta.entry.event_id, "correlationId": delta.order_id},
            )
