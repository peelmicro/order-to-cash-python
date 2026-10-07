"""`NatsSagaCommandsAdapter`: the six saga commands over NATS request-reply (`design.md` 9.2, 9.3).

Holds feature 15's connected client (no second connection) and the per-attempt budget; it does no
I/O at construction. nats-py ships `py.typed` but types `request(headers=...)` loosely, so the one
call it makes is typed through a private `Protocol` and the adapter returns only the generated reply
models or its own errors (L27).

Which nats-py error is which (established against a real server by feature 15's measurement,
`nats_stock_availability.py`):

* `nats.errors.NoRespondersError` (the server's 503) -> `SagaCommandTransportError`;
* `nats.errors.TimeoutError` -> `SagaCommandTimeoutError`;
* any other `nats.errors.Error` -> `SagaCommandTransportError`.

TRAP (L16): `nats.errors.TimeoutError` subclasses `asyncio.TimeoutError`, which is the builtin
`TimeoutError`, so a bare `except TimeoutError` would also swallow an OUTER `asyncio.timeout`
deadline as a NATS timeout. This adapter catches the nats class by name, so an outer deadline
propagates as the builtin `TimeoutError`. `asyncio.CancelledError` is never caught.

The request body is the STORED payload text as bytes (L21), never a re-serialisation. A fresh header
dict is built per call (L19): concurrent per-command tasks share this one adapter, so a shared,
mutated dict would race across an `await`. `traceparent` is feature 27's.

Reply decode (SO15): the whole decode sits inside ONE `except ValueError` (`JSONDecodeError`,
`UnicodeDecodeError` and pydantic's `ValidationError` are all ValueErrors), so no decoding exception
escapes the adapter; a body that is not an object is refused explicitly; an `RpcError` is told apart
before typed decoding and is split by its code (feature 42, `TERMINAL_RPC_ERROR_CODES`): a terminal
business code becomes `SagaCommandBusinessRejectionError(code)` (never retried), a transient one
`SagaCommandRpcError(code)` (retried), and a code outside the twelve fails open to the retryable
side as a plain transport error with no `code` (L18).
"""

from typing import Protocol

import nats.errors

from otc_contracts import WireModel, from_wire_json
from otc_contracts.generated.asyncapi import (
    Code,
    CreditHoldReplyPayload,
    CreditReleaseReplyPayload,
    DespatchCreateReplyPayload,
    InvoiceIssueReplyPayload,
    RpcError,
    StockReleaseReplyPayload,
    StockReserveReplyPayload,
)
from otc_orders.application.ports.saga_commands import (
    SagaCommandBusinessRejectionError,
    SagaCommandMeta,
    SagaCommandRpcError,
    SagaCommandTimeoutError,
    SagaCommandTransportError,
)
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.infrastructure.messaging.rpc_reply import parse_reply
from otc_orders.infrastructure.messaging.saga_subjects import SAGA_SUBJECTS

# `asyncapi.yaml` gives the twelve `RpcError.code` values no per-code description (only `TIMEOUT` is
# described: caller-produced), so the split is #7's and #8's, member for member
# (`isTerminalRpcErrorCode`, `nats-saga-commands.adapter.ts:79`; `IsTerminalRpcErrorCode`,
# `NatsSagaCommandsAdapter.cs:179`).
# TERMINAL: a definitive "no" from the responder's own domain, which re-asking can never turn into a
# "yes". TRANSIENT (not listed): TIMEOUT, UNAVAILABLE, INTERNAL_ERROR.
TERMINAL_RPC_ERROR_CODES: frozenset[Code] = frozenset(
    {
        Code.validation_failed,
        Code.not_found,
        Code.conflict,
        Code.precondition_failed,
        Code.order_not_cancellable,
        Code.stock_unavailable,
        Code.invoice_not_payable,
        Code.payment_mismatch,
        Code.domain_error,
    }
)


class _Reply(Protocol):
    @property
    def data(self) -> bytes: ...


class _Requester(Protocol):
    async def request(
        self,
        subject: str,
        payload: bytes,
        *,
        timeout: float,  # noqa: ASYNC109 - nats-py's own parameter name, not an asyncio deadline
        headers: dict[str, str],
    ) -> _Reply: ...


class NatsSagaCommandsAdapter:
    def __init__(self, connection: _Requester, *, timeout_ms: int) -> None:
        self._connection = connection
        self._timeout_ms = timeout_ms

    async def reserve_stock(
        self, request: bytes, meta: SagaCommandMeta
    ) -> StockReserveReplyPayload:
        return await self._call(
            SagaCommandKind.STOCK_RESERVE, StockReserveReplyPayload, request, meta
        )

    async def release_stock(
        self, request: bytes, meta: SagaCommandMeta
    ) -> StockReleaseReplyPayload:
        return await self._call(
            SagaCommandKind.STOCK_RELEASE, StockReleaseReplyPayload, request, meta
        )

    async def create_despatch(
        self, request: bytes, meta: SagaCommandMeta
    ) -> DespatchCreateReplyPayload:
        return await self._call(
            SagaCommandKind.DESPATCH_CREATE, DespatchCreateReplyPayload, request, meta
        )

    async def hold_credit(self, request: bytes, meta: SagaCommandMeta) -> CreditHoldReplyPayload:
        return await self._call(SagaCommandKind.CREDIT_HOLD, CreditHoldReplyPayload, request, meta)

    async def issue_invoice(
        self, request: bytes, meta: SagaCommandMeta
    ) -> InvoiceIssueReplyPayload:
        return await self._call(
            SagaCommandKind.INVOICE_ISSUE, InvoiceIssueReplyPayload, request, meta
        )

    async def release_credit(
        self, request: bytes, meta: SagaCommandMeta
    ) -> CreditReleaseReplyPayload:
        return await self._call(
            SagaCommandKind.CREDIT_RELEASE, CreditReleaseReplyPayload, request, meta
        )

    async def _call[R: WireModel](
        self, kind: SagaCommandKind, reply_model: type[R], request: bytes, meta: SagaCommandMeta
    ) -> R:
        subject = SAGA_SUBJECTS[kind]
        # A new dict per call: this adapter is shared by concurrent per-command tasks (L19).
        headers = {
            "x-correlation-id": str(meta.correlation_id),
            "x-request-id": str(meta.request_id),
        }
        try:
            reply = await self._connection.request(
                subject, request, timeout=self._timeout_ms / 1000, headers=headers
            )
        except nats.errors.NoRespondersError:
            raise SagaCommandTransportError(
                subject, f"no responder is subscribed to {subject}."
            ) from None
        except nats.errors.TimeoutError:
            raise SagaCommandTimeoutError(
                subject, f"no reply within {self._timeout_ms} ms."
            ) from None
        except nats.errors.Error as error:
            raise SagaCommandTransportError(
                subject, f"the NATS request failed: {type(error).__name__}."
            ) from error
        return self._decode(subject, reply_model, reply.data)

    @staticmethod
    def _decode[R: WireModel](subject: str, reply_model: type[R], body: bytes) -> R:
        try:
            parsed = parse_reply(body)
            if not isinstance(parsed.document, dict):
                raise ValueError("reply is not a JSON object")
            if parsed.error is not None:
                error = from_wire_json(RpcError, body)  # an unknown code is a ValueError
                if error.code in TERMINAL_RPC_ERROR_CODES:
                    raise SagaCommandBusinessRejectionError(
                        subject, error.code.value, error.message
                    )
                raise SagaCommandRpcError(subject, error.code.value, error.message)
            return from_wire_json(reply_model, body)
        except ValueError as defect:
            raise SagaCommandTransportError(subject, f"malformed reply: {defect}") from defect
