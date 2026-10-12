"""The request-reply port (NATS core in production)."""

from typing import Protocol
from uuid import UUID

from otc_contracts import WireModel


class RpcClient(Protocol):
    async def call[R: WireModel](
        self,
        subject: str,
        request: WireModel,
        reply_type: type[R],
        *,
        correlation_id: UUID,
        request_id: UUID,
    ) -> R:
        """Send `request` to `subject` with `x-correlation-id` and `x-request-id` and return the
        reply decoded as `reply_type`.

        Raises `RpcRemoteError` (the responder's own `RpcError`), `RpcTimeoutError`,
        `RpcUnavailableError` or `RpcProtocolError`; never anything else about the call itself.
        """
        ...
