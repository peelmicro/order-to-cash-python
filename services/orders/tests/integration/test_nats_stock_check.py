"""`NatsStockAvailability` against a real NATS server (feature 15, #8 D1 and id 46).

nats-py's own behaviour is MEASURED here, not assumed from its documentation (#8 found its library
contradicting its own docs): a request on a subject nobody subscribes to raises
`nats.errors.NoRespondersError` immediately, a subscribed responder that stays silent raises
`nats.errors.TimeoutError` after the deadline, and the first is not a `TimeoutError`. The port maps
them to different typed errors (`UNAVAILABLE` / `TIMEOUT` on the wire; feature 42 retries by the
split), and `test_the_two_transport_failures_are_different_errors` fails when the branches collapse.
"""

import json
import time
from collections.abc import Callable
from typing import Any

import nats
import nats.errors
import pytest
from nats.aio.client import Client as NatsClient

from otc_orders.application.ports.stock_availability import (
    StockAvailabilityLine,
    StockCheckBusinessError,
    StockCheckTimeoutError,
    StockCheckTransportError,
)
from otc_orders.infrastructure.messaging.nats_stock_availability import NatsStockAvailability
from otc_shared_kernel import Quantity

LINES = [StockAvailabilityLine("SKU-A", Quantity(3)), StockAvailabilityLine("SKU-B", Quantity(2))]


def checker(client: NatsClient, timeout_ms: int = 600) -> NatsStockAvailability:
    return NatsStockAvailability(client, timeout_ms=timeout_ms)


async def test_nats_py_signals_no_responders_and_a_timeout_as_two_unrelated_errors(
    nats_client: NatsClient, stand_in_stock_check: Any
) -> None:
    with pytest.raises(nats.errors.NoRespondersError) as no_responders:
        await nats_client.request("fulfillment.stock.check", b"{}", timeout=1)
    assert not isinstance(no_responders.value, TimeoutError)

    await stand_in_stock_check(lambda request: None)
    with pytest.raises(nats.errors.TimeoutError) as silent:
        await nats_client.request("fulfillment.stock.check", b"{}", timeout=0.3)
    assert isinstance(silent.value, TimeoutError)
    assert not isinstance(silent.value, nats.errors.NoRespondersError)


async def test_the_two_transport_failures_are_different_errors(
    nats_client: NatsClient, stand_in_stock_check: Any
) -> None:
    started = time.monotonic()
    with pytest.raises(StockCheckTransportError) as unavailable:
        await checker(nats_client, timeout_ms=3000).check("CMP-01", LINES)
    assert time.monotonic() - started < 1.5, "no responders is answered at once, not after 3 s"
    assert not isinstance(unavailable.value, StockCheckTimeoutError)
    assert unavailable.value.subject == "fulfillment.stock.check"
    # unique to the no-responders branch: the generic NATS-error branch words it differently
    assert str(unavailable.value) == "no responder is subscribed to fulfillment.stock.check."

    await stand_in_stock_check(lambda request: None)
    with pytest.raises(StockCheckTimeoutError) as timed_out:
        await checker(nats_client, timeout_ms=400).check("CMP-01", LINES)
    assert not isinstance(timed_out.value, StockCheckTransportError)
    assert timed_out.value.timeout_ms == 400


async def test_a_success_reply_is_decoded_line_by_line_and_the_request_is_the_contract(
    nats_client: NatsClient, stand_in_stock_check: Any, stock_reply: Callable[..., bytes]
) -> None:
    stand_in = await stand_in_stock_check(
        lambda request: stock_reply([("SKU-A", 3, 9), ("SKU-B", 2, 1)])
    )

    result = await checker(nats_client).check("CMP-01", LINES)

    assert result.available is False
    assert [(x.product_code, x.requested, x.available, x.sufficient) for x in result.lines] == [
        ("SKU-A", 3, 9, True),
        ("SKU-B", 2, 1, False),
    ]
    assert stand_in.requests == [
        {
            "companyCode": "CMP-01",
            "lines": [
                {"productCode": "SKU-A", "quantity": 3},
                {"productCode": "SKU-B", "quantity": 2},
            ],
        }
    ]


async def test_an_rpc_error_reply_is_read_as_the_responders_own_error_before_typed_decoding(
    nats_client: NatsClient, stand_in_stock_check: Any
) -> None:
    await stand_in_stock_check(
        lambda request: json.dumps(
            {"code": "INTERNAL_ERROR", "message": "stock table locked", "details": {"x": 1}}
        ).encode()
    )

    with pytest.raises(StockCheckBusinessError) as error:
        await checker(nats_client).check("CMP-01", LINES)

    assert error.value.rpc_error_code == "INTERNAL_ERROR"
    assert error.value.responder_message == "stock table locked"
    assert error.value.subject == "fulfillment.stock.check"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"<html>502</html>", "reply payload was not valid JSON."),
        (b"", "reply payload was not valid JSON."),
        (b"\xff\xfe", "reply payload was not valid JSON."),
        (b"[1, 2]", "neither a stock check reply nor an RpcError"),
        (b'{"available": true}', "neither a stock check reply nor an RpcError"),
        (b'{"available": "yes", "lines": []}', "neither a stock check reply nor an RpcError"),
        (b"null", "neither a stock check reply nor an RpcError"),
    ],
)
async def test_a_reply_that_is_neither_shape_is_a_transport_error_with_a_reason(
    nats_client: NatsClient, stand_in_stock_check: Any, body: bytes, reason: str
) -> None:
    await stand_in_stock_check(lambda request: body)

    with pytest.raises(StockCheckTransportError, match=reason):
        await checker(nats_client).check("CMP-01", LINES)


async def test_a_closed_connection_is_a_transport_error_not_a_bare_nats_error(
    nats_server: Any,
) -> None:
    client = await nats.connect(nats_server.url)
    await client.close()

    with pytest.raises(StockCheckTransportError, match="ConnectionClosedError"):
        await checker(client).check("CMP-01", LINES)
