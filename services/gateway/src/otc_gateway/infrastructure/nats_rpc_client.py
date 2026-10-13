"""`NatsRpcClient`: the `RpcClient` port over NATS core request-reply.

Copied in shape (not imported: service independence) from Orders' `nats_stock_availability.py` and
`rpc_reply.py`, the two #9 clients that were established against a real server (nats-py 2.16.0):

* no subscriber on the subject -> `nats.errors.NoRespondersError`, IMMEDIATELY (the server's 503
  status); it is not a timeout, so it is `RpcUnavailableError`, never waiting out the deadline;
* a subscriber that never replies -> `nats.errors.TimeoutError` after the deadline ->
  `RpcTimeoutError`;
* anything else nats-py raises as `nats.errors.Error` (a closed connection, no servers) is the
  transport being unavailable.

The reply is `success | RpcError` (#8 id 46): the body is parsed as JSON first and an object with a
string `code` is read as the responder's own error BEFORE any typed decoding; a body that is not
JSON, or is neither shape, is `RpcProtocolError`. `asyncio.CancelledError` is never caught.

Each call carries `x-correlation-id` and `x-request-id` (`asyncapi.yaml` `RpcHeaders`). The request
body is written by the one serializer (`to_wire_json`).
"""

import json
from typing import Any
from uuid import UUID

import nats.errors
from nats.aio.client import Client
from opentelemetry.trace import SpanKind, Tracer
from pydantic import ValidationError

from otc_contracts import WireModel, from_wire_json, to_wire_json
from otc_gateway.application.errors import (
    RpcProtocolError,
    RpcRemoteError,
    RpcTimeoutError,
    RpcUnavailableError,
)
from otc_gateway.infrastructure.observability.trace_context import NO_TRACER, inject_nats

CORRELATION_HEADER = "x-correlation-id"
REQUEST_HEADER = "x-request-id"


class NatsRpcClient:
    def __init__(self, connection: Client, *, timeout_ms: int, tracer: Tracer = NO_TRACER) -> None:
        self._connection = connection
        self._timeout_ms = timeout_ms
        self._tracer = tracer

    async def call[R: WireModel](
        self,
        subject: str,
        request: WireModel,
        reply_type: type[R],
        *,
        correlation_id: UUID,
        request_id: UUID,
    ) -> R:
        # A new dict per call: concurrent requests share this client (`R56`, ledger L23).
        headers = {
            CORRELATION_HEADER: str(correlation_id),
            REQUEST_HEADER: str(request_id),
        }
        try:
            with self._tracer.start_as_current_span(
                f"{subject} request",
                kind=SpanKind.CLIENT,
                attributes={"messaging.system": "nats", "messaging.destination.name": subject},
            ):
                inject_nats(headers)  # the CLIENT span's context, into THIS call's dict
                reply = await self._connection.request(
                    subject,
                    to_wire_json(request).encode("utf-8"),
                    timeout=self._timeout_ms / 1000,
                    headers=headers,
                )
        except nats.errors.NoRespondersError:
            raise RpcUnavailableError(
                subject, f"no responder is subscribed to {subject}."
            ) from None
        except nats.errors.TimeoutError:
            raise RpcTimeoutError(subject, self._timeout_ms) from None
        except nats.errors.Error as error:
            raise RpcUnavailableError(
                subject, f"the NATS request to {subject} failed: {type(error).__name__}."
            ) from error
        return self._decode(subject, reply.data, reply_type)

    @staticmethod
    def _decode[R: WireModel](subject: str, body: bytes, reply_type: type[R]) -> R:
        try:
            document: Any = json.loads(body)
        except ValueError:
            raise RpcProtocolError(
                subject, f"{subject} replied with a body that is not JSON."
            ) from None
        if isinstance(document, dict) and isinstance(document.get("code"), str):
            message = document.get("message")
            details = document.get("details")
            raise RpcRemoteError(
                subject,
                document["code"],
                message if isinstance(message, str) else "",
                details if isinstance(details, dict) else None,
            )
        try:
            return from_wire_json(reply_type, body)
        except ValidationError:
            raise RpcProtocolError(
                subject, f"{subject} replied with neither a {reply_type.__name__} nor an RpcError."
            ) from None
