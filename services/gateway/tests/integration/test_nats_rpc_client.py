"""`NatsRpcClient` against a real NATS and stand-in responders that follow the AsyncAPI contract
(#8's `NatsRpcClientIntegrationTests.cs`, ported; the trace-header rows are feature 27's).

The stand-ins here are NOT a substitute for the real responders
(`test_gateway_over_real_responders.py` is that): they are the only way to make a responder
misbehave on purpose - stay silent, answer garbage, answer an `RpcError` with details - and to
read the headers and the bytes it was sent.

* success: decoded to the contract's reply model; the responder received `x-correlation-id` and
  `x-request-id` exactly as sent, and the body the one serializer writes (camelCase);
* no responder subscribed: `RpcUnavailableError`, IMMEDIATELY (the server's 503 status), never after
  the deadline;
* a responder subscribed that never answers: `RpcTimeoutError`, after the deadline and not before;
  the two are different errors (they are different HTTP answers: `UPSTREAM_UNAVAILABLE` and
  `UPSTREAM_TIMEOUT`);
* an `RpcError` reply: `RpcRemoteError` carrying the code, message and details as sent;
* a reply that is not JSON, or JSON of neither shape: `RpcProtocolError`.

Loop scope: function; the clients and subscriptions are closed in the test's loop.
"""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import nats
import pytest
import pytest_asyncio
from nats.aio.client import Client
from nats.aio.msg import Msg

from otc_contracts import to_wire_json
from otc_contracts.generated import asyncapi
from otc_gateway.application.errors import (
    RpcProtocolError,
    RpcRemoteError,
    RpcTimeoutError,
    RpcUnavailableError,
)
from otc_gateway.infrastructure.nats_rpc_client import NatsRpcClient

pytestmark = pytest.mark.integration

TIMEOUT_MS = 600


def subject() -> str:
    """A subject no other test uses, so a stand-in here never answers somebody else's request."""
    return f"test.gateway.{uuid.uuid4().hex}"


@pytest_asyncio.fixture(loop_scope="function")
async def connection(nats_server: Any) -> AsyncIterator[Client]:
    client = await nats.connect(nats_server.url)
    try:
        yield client
    finally:
        await client.close()


@pytest_asyncio.fixture(loop_scope="function")
async def responder_side(nats_server: Any) -> AsyncIterator[Client]:
    client = await nats.connect(nats_server.url)
    try:
        yield client
    finally:
        await client.close()


def request() -> asyncapi.StockListRequestPayload:
    return asyncapi.StockListRequestPayload(page=2, page_size=7, company_code="IBERFOODS")


async def test_a_reply_is_decoded_and_the_responder_received_the_ids_and_the_contract_body(
    connection: Client, responder_side: Client
) -> None:
    target = subject()
    seen: list[Msg] = []

    async def answer(message: Msg) -> None:
        seen.append(message)
        reply = asyncapi.StockListReplyPayload(
            items=[], page=asyncapi.PageInfo(page=2, page_size=7, total=0)
        )
        await message.respond(to_wire_json(reply).encode())

    await responder_side.subscribe(target, cb=answer)
    await responder_side.flush()
    correlation, attempt = uuid.uuid4(), uuid.uuid4()

    reply = await NatsRpcClient(connection, timeout_ms=TIMEOUT_MS).call(
        target,
        request(),
        asyncapi.StockListReplyPayload,
        correlation_id=correlation,
        request_id=attempt,
    )

    assert reply.page.page_size == 7
    [message] = seen
    assert message.headers is not None
    assert message.headers["x-correlation-id"] == str(correlation)
    assert message.headers["x-request-id"] == str(attempt)
    assert correlation != attempt
    assert json.loads(message.data) == {"page": 2, "pageSize": 7, "companyCode": "IBERFOODS"}
    assert message.data == to_wire_json(request()).encode()


async def test_no_responder_is_unavailable_at_once_a_silent_one_is_a_timeout_after_the_bound(
    connection: Client, responder_side: Client
) -> None:
    client = NatsRpcClient(connection, timeout_ms=TIMEOUT_MS)
    silent = subject()

    async def never_answers(message: Msg) -> None:
        return None

    await responder_side.subscribe(silent, cb=never_answers)
    await responder_side.flush()
    ids: dict[str, Any] = {"correlation_id": uuid.uuid4(), "request_id": uuid.uuid4()}

    started = time.monotonic()
    with pytest.raises(RpcUnavailableError):
        await client.call(subject(), request(), asyncapi.StockListReplyPayload, **ids)
    unavailable_after = time.monotonic() - started

    started = time.monotonic()
    with pytest.raises(RpcTimeoutError) as timed_out:
        await client.call(silent, request(), asyncapi.StockListReplyPayload, **ids)
    timed_out_after = time.monotonic() - started

    assert unavailable_after < TIMEOUT_MS / 1000 / 2, "no responder must not wait out the deadline"
    assert TIMEOUT_MS / 1000 * 0.9 <= timed_out_after < 5.0
    assert timed_out.value.timeout_ms == TIMEOUT_MS
    assert not issubclass(RpcTimeoutError, RpcUnavailableError)  # two answers, not one
    assert not issubclass(RpcUnavailableError, RpcTimeoutError)


async def test_an_rpc_error_reply_carries_the_code_the_message_and_the_details_as_sent(
    connection: Client, responder_side: Client
) -> None:
    target = subject()
    sent = {
        "code": "PRECONDITION_FAILED",
        "message": "reference reused",
        "details": {"code": "payment.reference_reused", "paymentReference": "BANK-1"},
    }

    async def refuse(message: Msg) -> None:
        await message.respond(json.dumps(sent).encode())

    await responder_side.subscribe(target, cb=refuse)
    await responder_side.flush()

    with pytest.raises(RpcRemoteError) as refused:
        await NatsRpcClient(connection, timeout_ms=TIMEOUT_MS).call(
            target,
            request(),
            asyncapi.StockListReplyPayload,
            correlation_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
        )

    assert refused.value.subject == target
    assert refused.value.code == "PRECONDITION_FAILED"
    assert str(refused.value) == "reference reused"
    assert refused.value.details == sent["details"]


@pytest.mark.parametrize(
    "garbage",
    [
        b"this is not json",
        b"\xff\xfe",
        b"[1, 2, 3]",
        b'{"items": "not a list", "page": 1}',
        b'{"something": "else"}',
        b"",
    ],
)
async def test_a_reply_that_is_neither_the_success_shape_nor_an_rpc_error_is_a_protocol_error(
    connection: Client, responder_side: Client, garbage: bytes
) -> None:
    target = subject()

    async def reply_garbage(message: Msg) -> None:
        await message.respond(garbage)

    await responder_side.subscribe(target, cb=reply_garbage)
    await responder_side.flush()

    with pytest.raises(RpcProtocolError):
        await NatsRpcClient(connection, timeout_ms=TIMEOUT_MS).call(
            target,
            request(),
            asyncapi.StockListReplyPayload,
            correlation_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
        )


async def test_concurrent_calls_each_receive_their_own_reply(
    connection: Client, responder_side: Client
) -> None:
    target = subject()

    async def echo_the_page(message: Msg) -> None:
        page = json.loads(message.data)["page"]
        reply = asyncapi.StockListReplyPayload(
            items=[], page=asyncapi.PageInfo(page=page, page_size=1, total=page)
        )
        await asyncio.sleep(0.05 * (5 - page))  # the first request is answered LAST
        await message.respond(to_wire_json(reply).encode())

    await responder_side.subscribe(target, cb=echo_the_page)
    await responder_side.flush()
    client = NatsRpcClient(connection, timeout_ms=3000)

    replies = await asyncio.gather(
        *(
            client.call(
                target,
                asyncapi.StockListRequestPayload(page=page, page_size=1),
                asyncapi.StockListReplyPayload,
                correlation_id=uuid.uuid4(),
                request_id=uuid.uuid4(),
            )
            for page in (1, 2, 3, 4)
        )
    )

    assert [r.page.total for r in replies] == [1, 2, 3, 4]
