"""`NatsStockAvailability`: the `fulfillment.stock.check` RPC client over NATS core request-reply.

Established against a real server (nats-py 2.16.0; `tests/integration/test_nats_stock_check.py`):

* no subscriber on the subject -> `nats.errors.NoRespondersError`, immediately (the server's 503
  status); it is NOT a `TimeoutError`;
* a subscriber that never replies -> `nats.errors.TimeoutError` (a subclass of the builtin
  `TimeoutError`) after the deadline.

They are different answers (`UNAVAILABLE` and `TIMEOUT`, feature 42 retries by the split), so each
has its own branch and its own typed error. Anything else nats-py raises as `nats.errors.Error` (a
closed connection, no servers) is the transport being unavailable too. `asyncio.CancelledError` is
never caught.

The reply is `success | RpcError` (#8 id 46): the body is parsed as JSON first and an error-shaped
one (a string `code` and no success fields) is read as the responder's own error BEFORE any typed
decoding; a body that is not JSON, or is neither shape, is a transport error with a reason, never a
bare exception out of the handler.
"""

from collections.abc import Sequence

import nats.errors
from nats.aio.client import Client
from pydantic import ValidationError

from otc_contracts import from_wire_json, to_wire_json
from otc_contracts.generated.asyncapi import Line1, StockCheckReplyPayload, StockCheckRequestPayload
from otc_orders.application.ports.stock_availability import (
    StockAvailabilityLine,
    StockAvailabilityLineResult,
    StockAvailabilityResult,
    StockCheckBusinessError,
    StockCheckTimeoutError,
    StockCheckTransportError,
)
from otc_orders.infrastructure.messaging.rpc_reply import ReplyNotJsonError, parse_reply
from otc_orders.infrastructure.messaging.subjects import STOCK_CHECK_SUBJECT


class NatsStockAvailability:
    def __init__(self, connection: Client, *, timeout_ms: int) -> None:
        self._connection = connection
        self._timeout_ms = timeout_ms

    async def check(
        self, company_code: str, lines: Sequence[StockAvailabilityLine]
    ) -> StockAvailabilityResult:
        request = StockCheckRequestPayload(
            company_code=company_code,
            lines=[
                Line1(product_code=line.product_code, quantity=line.quantity.value)
                for line in lines
            ],
        )
        try:
            reply = await self._connection.request(
                STOCK_CHECK_SUBJECT,
                to_wire_json(request).encode("utf-8"),
                timeout=self._timeout_ms / 1000,
            )
        except nats.errors.NoRespondersError:
            raise StockCheckTransportError(
                STOCK_CHECK_SUBJECT, f"no responder is subscribed to {STOCK_CHECK_SUBJECT}."
            ) from None
        except nats.errors.TimeoutError:
            raise StockCheckTimeoutError(STOCK_CHECK_SUBJECT, self._timeout_ms) from None
        except nats.errors.Error as error:
            raise StockCheckTransportError(
                STOCK_CHECK_SUBJECT, f"the NATS request failed: {type(error).__name__}."
            ) from error
        return self._decode(reply.data)

    @staticmethod
    def _decode(body: bytes) -> StockAvailabilityResult:
        try:
            reply = parse_reply(body)
        except ReplyNotJsonError:
            raise StockCheckTransportError(
                STOCK_CHECK_SUBJECT, "reply payload was not valid JSON."
            ) from None
        if reply.error is not None:
            raise StockCheckBusinessError(
                STOCK_CHECK_SUBJECT, reply.error.code, reply.error.message
            )
        try:
            payload = from_wire_json(StockCheckReplyPayload, body)
        except ValidationError:
            raise StockCheckTransportError(
                STOCK_CHECK_SUBJECT, "reply payload is neither a stock check reply nor an RpcError."
            ) from None
        return StockAvailabilityResult(
            available=payload.available,
            lines=tuple(
                StockAvailabilityLineResult(
                    product_code=line.product_code,
                    requested=line.requested,
                    available=line.available,
                    sufficient=line.sufficient,
                )
                for line in payload.lines
            ),
        )
