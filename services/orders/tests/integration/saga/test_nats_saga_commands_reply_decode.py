# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""A malformed reply on EVERY saga subject is a transport error, never a decode exception (SO15; #8 id 110).

A real NATS server and a real nats-py responder answering bytes that are not JSON, on each of the six
subjects; the adapter under test is the production one over a real connection.
"""

import uuid

import nats
import pytest
from nats.aio.msg import Msg

from otc_orders.application.ports.saga_commands import SagaCommandMeta, SagaCommandTransportError
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.infrastructure.messaging.nats_saga_commands import NatsSagaCommandsAdapter
from otc_orders.infrastructure.messaging.saga_subjects import SAGA_SUBJECTS
from otc_shared_kernel import UniqueId

METHOD_OF = {
    SagaCommandKind.STOCK_RESERVE: "reserve_stock",
    SagaCommandKind.STOCK_RELEASE: "release_stock",
    SagaCommandKind.DESPATCH_CREATE: "create_despatch",
    SagaCommandKind.CREDIT_HOLD: "hold_credit",
    SagaCommandKind.INVOICE_ISSUE: "issue_invoice",
    SagaCommandKind.CREDIT_RELEASE: "release_credit",
}


@pytest.mark.parametrize("kind", list(SagaCommandKind), ids=lambda kind: kind.value)
async def test_so15_a_malformed_reply_on_every_saga_subject_is_a_transport_error_never_a_decode_exception(
    kind: SagaCommandKind, nats_server: object
) -> None:
    url = nats_server.url  # type: ignore[attr-defined]
    subject = SAGA_SUBJECTS[kind]
    responder = await nats.connect(url)
    caller = await nats.connect(url)
    try:

        async def answer_garbage(message: Msg) -> None:
            await message.respond(b"this is not json {")

        await responder.subscribe(subject, cb=answer_garbage)
        await responder.flush()  # a real subscribe-and-flush probe, never a fixed delay
        adapter = NatsSagaCommandsAdapter(caller, timeout_ms=3000)
        meta = SagaCommandMeta(correlation_id=UniqueId.new(), request_id=uuid.uuid4())

        with pytest.raises(SagaCommandTransportError) as refused:
            await getattr(adapter, METHOD_OF[kind])(b'{"orderReference":"ORD-000007"}', meta)

        assert refused.value.subject == subject
        assert "malformed reply" in str(refused.value)
        assert isinstance(refused.value.__cause__, ValueError), "the decode defect is chained"
    finally:
        await responder.close()
        await caller.close()
