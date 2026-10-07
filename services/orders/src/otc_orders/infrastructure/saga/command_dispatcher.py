"""`SagaCommandDispatcher`: issue one owed command, with the retry policy.

Design: `design.md` 9.5; SO4, SO6.

* `dispatch(order_id, kind)` (the fast path) claims the row first: no row back (absent, `sent`,
  `rejected`, leased by someone else) is a silent no-op.
* `dispatch_claimed(row)` (the sweeper) does NOT claim: the sweeper already holds the lease, and
  claiming again would exclude the claimer from its own row and silently do nothing (#8's one
  production defect, L12; SO16).

Then, for attempt 1 .. `max_attempts`: the port is called with the STORED bytes and the headers'
meta (`x-correlation-id` = the order id, `x-request-id` = the row id, the same on every attempt). A
returned reply, a business `rejected` one included, marks the row `sent` and is never retried (SO6):
a command's response never advances the saga, the fact does. A `SagaCommandError` is remembered, and
the in-line back-off (`500 ms` doubling) is slept unless it was the last attempt. A terminal
business `RpcError` (`SagaCommandBusinessRejectionError`, feature 42) is resolved on the FIRST
attempt through `ledger.reject` (`rejected`, lease cleared), never retried and never parked.
Exhausted: the row is parked with the accumulated attempts and the last error, and a structured
ERROR is logged (SO5).
The order is never loaded or written here (R29: its status is unchanged).

Budget (`design.md` 5.2): the numbers are #7's and #8's (5 000 ms x 3 attempts, 500 ms back-off), so
the benchmark compares languages, not tuning. #7 sized them under kafkajs's 30 s session timeout
(about 16.5 s); #8 re-derived that the binding constraint for librdkafka is `max.poll.interval.ms`
(300 s). For aiokafka it is the same 300 s (`session_timeout_ms=10000`,
`max_poll_interval_ms=300000`), and heartbeats need a free loop. The RPC runs in other tasks (the
fast path, the sweeper), so a record's time on the consume path is one database transaction. Worst
case of one dispatch: `max_attempts * timeout_ms + the back-off sum` = 3 x 5 000 + 500 + 1 000 = 16
500 ms.

`sleep` and the clock are injected, so unit tests run instantly with fakes.
"""

import asyncio
import enum
import logging
from collections.abc import Awaitable, Callable

from otc_contracts import format_instant
from otc_orders.application.ports.clock import Clock
from otc_orders.application.ports.saga_command_store import ClaimedCommand, SagaCommandLedger
from otc_orders.application.ports.saga_commands import (
    SagaCommandBusinessRejectionError,
    SagaCommandError,
    SagaCommandMeta,
    SagaCommands,
)
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.infrastructure.saga.backoff import in_line_backoff_ms, park_backoff_ms
from otc_shared_kernel import UniqueId

log = logging.getLogger("otc_orders.saga.command_dispatcher")


class DispatchOutcome(enum.Enum):
    SENT = "sent"
    PARKED = "parked"
    REJECTED = "rejected"
    NOOP = "noop"


class SagaCommandDispatcher:
    def __init__(
        self,
        *,
        ledger: SagaCommandLedger,
        commands: SagaCommands,
        clock: Clock,
        max_attempts: int,
        backoff_ms: int,
        park_cap_ms: int,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._ledger = ledger
        self._commands = commands
        self._clock = clock
        self._max_attempts = max_attempts
        self._backoff_ms = backoff_ms
        self._park_cap_ms = park_cap_ms
        self._sleep = sleep

    async def dispatch(self, order_id: UniqueId, kind: SagaCommandKind) -> DispatchOutcome:
        row = await self._ledger.try_claim(order_id, kind)
        if row is None:
            return DispatchOutcome.NOOP
        return await self.dispatch_claimed(row)

    async def dispatch_claimed(self, row: ClaimedCommand) -> DispatchOutcome:
        request = row.payload.encode("utf-8")  # the committed text, never re-serialised (L21)
        meta = SagaCommandMeta(correlation_id=row.order_id, request_id=row.id)
        last_error = ""
        for attempt in range(1, self._max_attempts + 1):
            try:
                await self._issue(row.kind, request, meta)
            except SagaCommandBusinessRejectionError as rejection:
                # Feature 42: a terminal business "no" is resolved on THIS attempt, never retried
                # and never parked. Caught before the generic `SagaCommandError` clause.
                total_attempts = row.attempts + attempt
                await self._ledger.reject(
                    row.id, total_attempts=total_attempts, last_error=str(rejection)
                )
                log.error(
                    "saga command rejected",
                    extra={
                        "correlationId": str(row.order_id),
                        "command": row.kind.value,
                        "attempts": total_attempts,
                        "code": rejection.code,
                        "lastError": str(rejection),
                    },
                )
                return DispatchOutcome.REJECTED
            except SagaCommandError as error:
                last_error = str(error)
                log.warning(
                    "saga command attempt failed",
                    extra={
                        "correlationId": str(row.order_id),
                        "command": row.kind.value,
                        "attempt": attempt,
                        "lastError": last_error,
                    },
                )
                if attempt < self._max_attempts:
                    pause_ms = in_line_backoff_ms(attempt, base_ms=self._backoff_ms)
                    await self._sleep(pause_ms / 1000)
                continue
            await self._ledger.mark_sent(row.id)
            return DispatchOutcome.SENT
        total = row.attempts + self._max_attempts
        retry_after_ms = park_backoff_ms(
            total, max_attempts=self._max_attempts, cap_ms=self._park_cap_ms
        )
        next_attempt_at = await self._ledger.park(
            row.id, total_attempts=total, last_error=last_error, retry_after_ms=retry_after_ms
        )
        log.error(
            "saga command parked",
            extra={
                "correlationId": str(row.order_id),
                "command": row.kind.value,
                "attempts": total,
                "lastError": last_error,
                "nextAttemptAt": format_instant(next_attempt_at),
            },
        )
        return DispatchOutcome.PARKED

    async def _issue(self, kind: SagaCommandKind, request: bytes, meta: SagaCommandMeta) -> object:
        match kind:
            case SagaCommandKind.STOCK_RESERVE:
                return await self._commands.reserve_stock(request, meta)
            case SagaCommandKind.STOCK_RELEASE:
                return await self._commands.release_stock(request, meta)
            case SagaCommandKind.DESPATCH_CREATE:
                return await self._commands.create_despatch(request, meta)
            case SagaCommandKind.CREDIT_HOLD:
                return await self._commands.hold_credit(request, meta)
            case SagaCommandKind.INVOICE_ISSUE:
                return await self._commands.issue_invoice(request, meta)
            case SagaCommandKind.CREDIT_RELEASE:
                return await self._commands.release_credit(request, meta)
