"""`SagaFastPath`: issue an owed command at once, one task per command (`design.md` 8; SO10, SO13,
SO14).

`signal` is synchronous, never blocks and never raises: it spawns ONE task per command in a
`TaskGroup` owned by `run` and returns. No command ever waits for another's dispatch (#7's
`mergeMap` semantics, not #8's bounded pool, whose N stuck dispatches stalled the N+1th: #8 ids 80,
88). Above `max_in_flight` the signal is DROPPED to the durable path, never queued: the row is
already committed `pending` and the sweeper issues it. Called before `run` starts or after it has
ended, it is dropped the same way.

* The caller's `contextvars` context is copied into the task at creation (`TaskGroup.create_task`
  copies the context of the code that calls it, which is the fact handling that owed the command),
  so feature 27's span context and `correlationId` log binding reach the dispatch with no capture
  field (L7). A queue drained by worker tasks would lose it.
* A child's `Exception` is logged and contained: a `TaskGroup` would otherwise cancel every sibling
  (L8). `asyncio.CancelledError` is a `BaseException` and is never caught here (L9): on stop the
  in-flight children are cancelled and awaited; their rows stay leased and the sweeper re-issues
  them after the lease, safe because responders are idempotent by (`orderReference`, operation).
"""

import asyncio
import logging
from typing import Protocol

from otc_orders.application.ports.saga_signal import SagaCommandRef
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.infrastructure.saga.command_dispatcher import DispatchOutcome
from otc_shared_kernel import UniqueId

log = logging.getLogger("otc_orders.saga.fast_path")


class DispatchesSagaCommands(Protocol):
    async def dispatch(self, order_id: UniqueId, kind: SagaCommandKind) -> DispatchOutcome: ...


class SagaFastPath:
    def __init__(self, *, dispatcher: DispatchesSagaCommands, max_in_flight: int) -> None:
        self._dispatcher = dispatcher
        self._max_in_flight = max_in_flight
        self._group: asyncio.TaskGroup | None = None
        self._children: set[asyncio.Task[None]] = set()

    @property
    def in_flight(self) -> int:
        return len(self._children)

    def signal(self, ref: SagaCommandRef) -> None:
        group = self._group
        if group is None or len(self._children) >= self._max_in_flight:
            log.warning(
                "fast path full or stopped; the sweeper will issue the command",
                extra={
                    "correlationId": str(ref.order_id),
                    "command": ref.kind.value,
                    "inFlight": len(self._children),
                },
            )
            return
        try:
            task = group.create_task(self._run(ref), name=f"saga-fast-path {ref.kind.value}")
        except RuntimeError:
            # The group is shutting down underneath us (stop raced the signal): durable path.
            log.warning(
                "fast path stopping; the sweeper will issue the command",
                extra={"correlationId": str(ref.order_id), "command": ref.kind.value},
            )
            return
        self._children.add(task)
        task.add_done_callback(self._children.discard)

    async def run(self, stop: asyncio.Event) -> None:
        async with asyncio.TaskGroup() as group:
            self._group = group
            try:
                await stop.wait()
            finally:
                self._group = None
                for child in list(self._children):
                    child.cancel()

    async def _run(self, ref: SagaCommandRef) -> None:
        try:
            await self._dispatcher.dispatch(ref.order_id, ref.kind)
        except Exception:
            log.exception(
                "fast path dispatch failed; the row stays leased and the sweeper re-issues it",
                extra={"correlationId": str(ref.order_id), "command": ref.kind.value},
            )
        finally:
            # Freed as soon as the dispatch ends, so the slot is free before anything that awaited
            # the dispatch resumes; the done callback covers a task cancelled before it started.
            self._children.discard(asyncio.current_task())
