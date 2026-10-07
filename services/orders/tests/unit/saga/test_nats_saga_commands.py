"""`NatsSagaCommandsAdapter` against a fake requester: the taxonomy, the headers, the decode.

Tasks 4.3-4.5 and 4.7.

The fake records exactly what the adapter hands to nats-py (subject, payload, timeout, the headers
object itself), so the assertions are about what is SENT. Real-server behaviour is the integration
test's (`test_nats_saga_commands_reply_decode.py`).
"""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import nats.errors
import pytest

from otc_contracts import WireModel
from otc_contracts.generated.asyncapi import (
    Code,
    CreditHoldReplyPayload,
    CreditReleaseReplyPayload,
    DespatchCreateReplyPayload,
    InvoiceIssueReplyPayload,
    StockReleaseReplyPayload,
    StockReserveReplyPayload,
)
from otc_orders.application.ports.saga_commands import (
    SagaCommandBusinessRejectionError,
    SagaCommandError,
    SagaCommandMeta,
    SagaCommandRpcError,
    SagaCommandTimeoutError,
    SagaCommandTransportError,
)
from otc_orders.infrastructure.messaging.nats_saga_commands import (
    TERMINAL_RPC_ERROR_CODES,
    NatsSagaCommandsAdapter,
)
from otc_shared_kernel import UniqueId

ORDER = UniqueId(uuid.UUID("00000000-0000-4000-8000-000000000001"))
ROW_A = uuid.UUID("00000000-0000-4000-8000-00000000aaa1")
ROW_B = uuid.UUID("00000000-0000-4000-8000-00000000bbb2")
META = SagaCommandMeta(correlation_id=ORDER, request_id=ROW_A)
REQUEST = b'{"orderReference":"ORD-000007","note":"stored bytes, with   odd spacing"}'
RESERVATION = {
    "reservationId": "00000000-0000-4000-8000-0000000000f1",
    "productCode": "SKU-A",
    "units": 3,
}

# (adapter method, the subject it must use, a valid reply, the reply model)
SUBJECTS: list[tuple[str, str, dict[str, Any], type[WireModel]]] = [
    (
        "reserve_stock",
        "fulfillment.stock.reserve",
        {"outcome": "accepted", "orderReference": "ORD-000007", "reservations": [RESERVATION]},
        StockReserveReplyPayload,
    ),
    (
        "release_stock",
        "fulfillment.stock.release",
        {"outcome": "released", "orderReference": "ORD-000007", "released": [RESERVATION]},
        StockReleaseReplyPayload,
    ),
    (
        "create_despatch",
        "fulfillment.despatch.create",
        {
            "orderReference": "ORD-000007",
            "despatchReference": "DES-000001",
            "despatchDate": "2026-10-01T09:00:00.000Z",
            "created": True,
        },
        DespatchCreateReplyPayload,
    ),
    (
        "hold_credit",
        "billing.credit.hold",
        {
            "outcome": "approved",
            "orderReference": "ORD-000007",
            "creditCode": "CR-000001",
            "currency": "EUR",
            "heldAmount": 8115,
            "availableCredit": 91885,
        },
        CreditHoldReplyPayload,
    ),
    (
        "issue_invoice",
        "billing.invoice.issue",
        {
            "orderReference": "ORD-000007",
            "invoiceReference": "INV-000001",
            "invoiceDate": "2026-10-01T09:00:00.000Z",
            "currency": "EUR",
            "totalAmount": 8115,
            "status": "issued",
            "created": True,
        },
        InvoiceIssueReplyPayload,
    ),
    (
        "release_credit",
        "billing.credit.release",
        {
            "released": True,
            "orderReference": "ORD-000007",
            "currency": "EUR",
            "availableCreditAfter": 100000,
        },
        CreditReleaseReplyPayload,
    ),
]
METHODS = [row[0] for row in SUBJECTS]


@dataclass
class Call:
    subject: str
    payload: bytes
    timeout: float
    headers: dict[str, str]


@dataclass
class _Reply:
    data: bytes


@dataclass
class FakeRequester:
    answer: Callable[[Call], Awaitable[bytes]]
    calls: list[Call] = field(default_factory=list)

    async def request(
        self,
        subject: str,
        payload: bytes,
        *,
        timeout: float,  # noqa: ASYNC109 - mirrors nats-py's own parameter
        headers: dict[str, str],
    ) -> _Reply:
        call = Call(subject, payload, timeout, headers)
        self.calls.append(call)
        return _Reply(await self.answer(call))


def replying(body: bytes) -> Callable[[Call], Awaitable[bytes]]:
    async def answer(_call: Call) -> bytes:
        return body

    return answer


def raising(error: BaseException) -> Callable[[Call], Awaitable[bytes]]:
    async def answer(_call: Call) -> bytes:
        raise error

    return answer


def adapter_over(requester: FakeRequester, timeout_ms: int = 1234) -> NatsSagaCommandsAdapter:
    return NatsSagaCommandsAdapter(requester, timeout_ms=timeout_ms)


async def call_method(adapter: NatsSagaCommandsAdapter, method: str, meta: SagaCommandMeta) -> Any:
    return await getattr(adapter, method)(REQUEST, meta)


@pytest.mark.parametrize(("method", "subject", "reply", "model"), SUBJECTS, ids=METHODS)
async def test_each_method_uses_its_own_subject_sends_the_stored_bytes_and_returns_its_model(
    method: str, subject: str, reply: dict[str, Any], model: type[WireModel]
) -> None:
    requester = FakeRequester(replying(json.dumps(reply).encode()))

    result = await call_method(adapter_over(requester), method, META)

    assert isinstance(result, model)
    [call] = requester.calls
    assert call.subject == subject
    assert call.payload == REQUEST, "the stored bytes, never a re-serialisation"
    assert call.timeout == 1.234


@pytest.mark.parametrize("method", METHODS)
async def test_no_responders_is_a_transport_error_naming_its_subject(method: str) -> None:
    requester = FakeRequester(raising(nats.errors.NoRespondersError()))
    subject = next(row[1] for row in SUBJECTS if row[0] == method)

    with pytest.raises(SagaCommandTransportError) as refused:
        await call_method(adapter_over(requester), method, META)

    assert not isinstance(refused.value, SagaCommandTimeoutError)
    assert refused.value.subject == subject
    assert "no responder" in str(refused.value)


@pytest.mark.parametrize("method", METHODS)
async def test_a_nats_timeout_is_a_timeout_error_and_not_a_transport_error(method: str) -> None:
    requester = FakeRequester(raising(nats.errors.TimeoutError()))

    with pytest.raises(SagaCommandTimeoutError) as refused:
        await call_method(adapter_over(requester), method, META)

    assert not isinstance(refused.value, SagaCommandTransportError)


async def test_any_other_nats_error_is_a_transport_error() -> None:
    requester = FakeRequester(raising(nats.errors.ConnectionClosedError()))

    with pytest.raises(SagaCommandTransportError) as refused:
        await adapter_over(requester).hold_credit(REQUEST, META)

    assert "ConnectionClosedError" in str(refused.value)
    assert refused.value.__cause__ is not None


async def test_an_outer_deadline_is_not_reported_as_a_nats_timeout() -> None:
    # `nats.errors.TimeoutError` subclasses the builtin `TimeoutError` (L16): an adapter that caught
    # the builtin would turn THIS deadline into a retryable NATS timeout and hide it.
    async def never(_call: Call) -> bytes:
        await asyncio.Event().wait()
        return b""

    requester = FakeRequester(never)

    with pytest.raises(TimeoutError) as expired:
        async with asyncio.timeout(0.05):
            await adapter_over(requester).reserve_stock(REQUEST, META)

    assert not isinstance(expired.value, SagaCommandError)
    assert not isinstance(expired.value, nats.errors.TimeoutError)


async def test_a_builtin_timeout_surfacing_inside_the_call_is_not_reported_as_a_nats_timeout() -> (
    None
):
    # A deadline owned by someone else that expires inside the awaited call arrives as the BUILTIN
    # `TimeoutError`: the adapter must let it through, not classify it as a retryable NATS timeout.
    requester = FakeRequester(raising(TimeoutError("a caller-owned deadline")))

    with pytest.raises(TimeoutError, match="a caller-owned deadline") as surfaced:
        await adapter_over(requester).reserve_stock(REQUEST, META)

    assert not isinstance(surfaced.value, SagaCommandError)


def test_the_nats_timeout_is_a_builtin_timeout_which_is_why_the_adapter_names_it() -> None:
    assert issubclass(nats.errors.TimeoutError, TimeoutError)


BAD_REPLIES: list[tuple[str, bytes]] = [
    ("not UTF-8", b"\xff\xfe\x00\x80"),
    ("not JSON", b"this is not json"),
    ("a JSON array", b"[1,2,3]"),
    ("a JSON string", b'"hello"'),
    ("an object failing the reply model", b'{"outcome":"accepted"}'),
    ("an empty body", b""),
]


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize(("label", "body"), BAD_REPLIES, ids=[label for label, _ in BAD_REPLIES])
async def test_so15_each_reply_defect_is_classified_as_a_transport_error_of_its_subject(
    method: str, label: str, body: bytes
) -> None:
    subject = next(row[1] for row in SUBJECTS if row[0] == method)
    requester = FakeRequester(replying(body))

    with pytest.raises(SagaCommandError) as refused:
        await call_method(adapter_over(requester), method, META)

    assert type(refused.value) is SagaCommandTransportError, label
    assert refused.value.subject == subject
    assert "malformed reply" in str(refused.value)
    if label in {"a JSON array", "a JSON string"}:
        assert "reply is not a JSON object" in str(refused.value), (
            "refused as a non-object, by name"
        )


TERMINAL_CODES = (
    "VALIDATION_FAILED",
    "NOT_FOUND",
    "CONFLICT",
    "PRECONDITION_FAILED",
    "ORDER_NOT_CANCELLABLE",
    "STOCK_UNAVAILABLE",
    "INVOICE_NOT_PAYABLE",
    "PAYMENT_MISMATCH",
    "DOMAIN_ERROR",
)
TRANSIENT_CODES = ("INTERNAL_ERROR", "UNAVAILABLE", "TIMEOUT")


def rpc_error_body(code: str) -> bytes:
    return json.dumps({"code": code, "message": f"said {code}"}).encode()


@pytest.mark.parametrize("code", TERMINAL_CODES)
async def test_feature_42_a_terminal_code_is_a_business_rejection_not_a_transport_error(
    code: str,
) -> None:
    with pytest.raises(SagaCommandError) as refused:
        await adapter_over(FakeRequester(replying(rpc_error_body(code)))).reserve_stock(
            REQUEST, META
        )

    assert type(refused.value) is SagaCommandBusinessRejectionError, code
    assert refused.value.code == code
    assert refused.value.subject == "fulfillment.stock.reserve"
    assert f"said {code}" in str(refused.value)
    assert not isinstance(refused.value, SagaCommandTransportError), (
        "a terminal rejection is never on the retryable side"
    )


@pytest.mark.parametrize("code", TRANSIENT_CODES)
async def test_feature_42_a_transient_code_is_a_retryable_rpc_error_carrying_its_code(
    code: str,
) -> None:
    with pytest.raises(SagaCommandError) as refused:
        await adapter_over(FakeRequester(replying(rpc_error_body(code)))).reserve_stock(
            REQUEST, META
        )

    assert type(refused.value) is SagaCommandRpcError, code
    assert refused.value.code == code
    assert refused.value.subject == "fulfillment.stock.reserve"
    assert isinstance(refused.value, SagaCommandTransportError), "retryable"


def test_feature_42_terminal_and_transient_sets_partition_the_generated_code_enum() -> None:
    assert {code.value for code in TERMINAL_RPC_ERROR_CODES} == set(TERMINAL_CODES)
    assert {code.value for code in Code} == set(TERMINAL_CODES) | set(TRANSIENT_CODES)
    assert not set(TERMINAL_CODES) & set(TRANSIENT_CODES)


@pytest.mark.parametrize("method", METHODS)
async def test_feature_42_every_command_method_classifies_a_terminal_code(method: str) -> None:
    with pytest.raises(SagaCommandBusinessRejectionError):
        await call_method(
            adapter_over(FakeRequester(replying(rpc_error_body("CONFLICT")))), method, META
        )


async def test_so15_an_rpc_error_with_a_code_outside_the_twelve_fails_open_to_transport() -> None:
    body = json.dumps({"code": "A_CODE_NOBODY_DECLARED", "message": "x"}).encode()

    with pytest.raises(SagaCommandError) as refused:
        await adapter_over(FakeRequester(replying(body))).hold_credit(REQUEST, META)

    assert type(refused.value) is SagaCommandTransportError, "an unknown code is not an RpcError"
    assert not hasattr(refused.value, "code"), "no code: neither terminal nor transient"


def test_no_success_reply_model_declares_a_top_level_code_property() -> None:
    for model in (row[3] for row in SUBJECTS):
        names = set(model.model_fields)
        aliases = {
            field.alias for field in model.model_fields.values() if field.alias is not None
        } | {to_wire(name) for name in names}
        assert "code" not in names | aliases, f"{model.__name__} would be read as an RpcError"


def to_wire(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


@pytest.mark.parametrize(
    ("method", "reply"),
    [
        (
            "reserve_stock",
            {
                "outcome": "rejected",
                "orderReference": "ORD-000007",
                "shortages": [{"productCode": "SKU-A", "requested": 3, "available": 1}],
            },
        ),
        (
            "hold_credit",
            {
                "outcome": "rejected",
                "orderReference": "ORD-000007",
                "currency": "EUR",
                "availableCredit": 100,
                "reason": "over_limit",
            },
        ),
        ("reserve_stock", {"outcome": "already_reserved", "orderReference": "ORD-000007"}),
        (
            "hold_credit",
            {
                "outcome": "already_held",
                "orderReference": "ORD-000007",
                "currency": "EUR",
                "availableCredit": 100,
            },
        ),
        ("release_stock", {"outcome": "already_released", "orderReference": "ORD-000007"}),
        (
            "create_despatch",
            {
                "orderReference": "ORD-000007",
                "despatchReference": "DES-000001",
                "despatchDate": "2026-10-01T09:00:00.000Z",
                "created": False,
            },
        ),
    ],
    ids=[
        "stock rejected",
        "credit rejected",
        "already reserved",
        "already held",
        "already released",
        "despatch not created",
    ],
)
async def test_so6_a_typed_rejected_reply_is_returned_not_raised(
    method: str, reply: dict[str, Any]
) -> None:
    requester = FakeRequester(replying(json.dumps(reply).encode()))

    result = await call_method(adapter_over(requester), method, META)

    assert result.order_reference == "ORD-000007"
    assert len(requester.calls) == 1


async def test_every_call_builds_a_fresh_header_dict_carrying_the_order_id_and_the_request_id() -> (
    None
):
    reply = json.dumps(SUBJECTS[0][2]).encode()
    requester = FakeRequester(replying(reply))
    adapter = adapter_over(requester)
    other_order = UniqueId(uuid.UUID("00000000-0000-4000-8000-000000000002"))

    await adapter.reserve_stock(REQUEST, META)
    await adapter.reserve_stock(
        REQUEST, SagaCommandMeta(correlation_id=other_order, request_id=ROW_B)
    )

    first, second = requester.calls
    assert first.headers is not second.headers, (
        "one dict per call: concurrent tasks share the adapter"
    )
    assert first.headers == {"x-correlation-id": str(ORDER), "x-request-id": str(ROW_A)}
    assert second.headers == {"x-correlation-id": str(other_order), "x-request-id": str(ROW_B)}
    assert first.headers["x-request-id"] != second.headers["x-request-id"]
