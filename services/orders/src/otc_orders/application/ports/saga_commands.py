"""`SagaCommands`: the six saga commands over NATS request-reply (`design.md` 9.2).

`request` is the STORED payload bytes: the adapter sends what was committed, never a
re-serialisation. A returned reply is a resolved command, whatever its `outcome` (a business
rejection is a reply, SO6); only a `SagaCommandError` is a failed attempt.

Feature 42's amendment: an `RpcError` reply is split by its `code`. A terminal business code (a
definitive "no" from the responder's domain) is a `SagaCommandBusinessRejectionError`, resolved on
the first attempt (`rejected`, never retried); a transient code is a `SagaCommandRpcError` and is
retried and finally parked; a code outside the twelve is a plain `SagaCommandTransportError`.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from otc_contracts.generated.asyncapi import (
    CreditHoldReplyPayload,
    CreditReleaseReplyPayload,
    DespatchCreateReplyPayload,
    InvoiceIssueReplyPayload,
    StockReleaseReplyPayload,
    StockReserveReplyPayload,
)
from otc_shared_kernel import UniqueId


@dataclass(frozen=True, slots=True)
class SagaCommandMeta:
    correlation_id: UniqueId  # the order id: `x-correlation-id`
    request_id: UUID  # the `saga_commands` row id: `x-request-id`, unchanged across retries


class SagaCommandError(Exception):
    """A failed attempt to issue a saga command. Never caught by the domain."""

    def __init__(self, subject: str, message: str) -> None:
        super().__init__(f"{subject}: {message}")
        self.subject = subject


class SagaCommandTimeoutError(SagaCommandError):
    """No reply within the per-attempt budget. Retryable."""


class SagaCommandTransportError(SagaCommandError):
    """No responder, a closed connection, or a reply that could not be decoded. Retryable."""


class SagaCommandRpcError(SagaCommandTransportError):
    """The responder answered with a TRANSIENT `RpcError` code (INTERNAL_ERROR, UNAVAILABLE,
    TIMEOUT). Retryable."""

    def __init__(self, subject: str, code: str, message: str) -> None:
        super().__init__(subject, f"responder answered {code}: {message}")
        self.code = code


class SagaCommandBusinessRejectionError(SagaCommandError):
    """The responder answered with a TERMINAL business `RpcError` code (feature 42). Deliberately
    NOT a `SagaCommandTransportError`: it is never retried, and the dispatcher resolves the row to
    `rejected` on the first attempt."""

    def __init__(self, subject: str, code: str, message: str) -> None:
        super().__init__(subject, f"responder rejected with {code}: {message}")
        self.code = code


class SagaCommands(Protocol):
    async def reserve_stock(
        self, request: bytes, meta: SagaCommandMeta
    ) -> StockReserveReplyPayload: ...

    async def release_stock(
        self, request: bytes, meta: SagaCommandMeta
    ) -> StockReleaseReplyPayload: ...

    async def create_despatch(
        self, request: bytes, meta: SagaCommandMeta
    ) -> DespatchCreateReplyPayload: ...

    async def hold_credit(
        self, request: bytes, meta: SagaCommandMeta
    ) -> CreditHoldReplyPayload: ...

    async def issue_invoice(
        self, request: bytes, meta: SagaCommandMeta
    ) -> InvoiceIssueReplyPayload: ...

    async def release_credit(
        self, request: bytes, meta: SagaCommandMeta
    ) -> CreditReleaseReplyPayload: ...
