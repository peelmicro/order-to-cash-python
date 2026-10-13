"""R58 for the Projector: every line the REAL server writes is JSON; a fact's id is on its lines.

A real `python -m uvicorn otc_projector.main:app --port 0` child over the suite's Docker-held
MongoDB, Kafka and NATS. The unit of work is one fact on the REAL topic `otc.orders.facts.v1` (the
topic is a constant of the service) whose `eventType` is well-formed but unregistered
(`order.shipped.v1`), so the consumer writes `unregistered fact type acknowledged without
processing` itself, with no correlation argument: only the binding of
`ProjectorFactsConsumerTask.handle` can put `correlationId` on it. The session broker holds every
fact earlier tests produced, so the child's consumer group is unique to this test and is committed
at the END of every partition first (`tests/observability/log_contract_support.py`, item 10's
"commits its group to the end first"). The child is stopped with SIGTERM and EVERY stderr line is
judged. The fact is published with a `traceparent` header: the lines carrying its trace id must be
exactly the lines carrying the `correlationId` (S3: the consumer's span continues the inbound
trace).
Loop scope: function.
"""

import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration

SUPPORT_PATH = Path(__file__).resolve().parents[4] / "tests/observability/log_contract_support.py"
ORDERS_FACTS_TOPIC = "otc.orders.facts.v1"
FACT_TOPICS = ("otc.orders.facts.v1", "otc.fulfillment.facts.v1", "otc.billing.facts.v1")

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TRACE_ID = TRACEPARENT.split("-")[1]


def load_support() -> Any:
    spec = importlib.util.spec_from_file_location("log_contract_support", SUPPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_r58_every_line_the_real_server_writes_is_json_and_every_line_of_one_unit_of_work_carries_its_correlation_id_and_trace_id(  # noqa: E501
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kafka_server: Any,
    nats_server: Any,
    fresh_mongo_database: Any,
) -> None:
    support = load_support()
    group = f"projector-log-contract-{uuid.uuid4().hex[:10]}"
    monkeypatch.chdir(tmp_path)  # no developer `.env`
    for name, value in {
        "MONGO_URI": fresh_mongo_database.uri,
        "MONGO_DB_READMODEL": fresh_mongo_database.name,
        "KAFKA_BROKERS": kafka_server.bootstrap_servers,
        "PROJECTOR_KAFKA_CLIENT_ID": "otc-projector-log-contract",
        "PROJECTOR_CONSUMER_GROUP": group,
        "NATS_URL": nats_server.url,
    }.items():
        monkeypatch.setenv(name, value)
    await support.commit_group_at_end(kafka_server.bootstrap_servers, group, FACT_TOPICS)
    correlation_id = str(uuid.uuid4())
    fact = {
        "eventId": str(uuid.uuid4()),
        "eventType": "order.shipped.v1",
        "aggregateId": correlation_id,
        "correlationId": correlation_id,
        "causationId": str(uuid.uuid4()),
        "occurredAt": "2026-10-12T16:30:00.123Z",
        "payload": {},
    }
    value = json.dumps(fact, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    process = support.spawn(
        support.python_module("uvicorn", "otc_projector.main:app", "--port", "0"),
        cwd=tmp_path,
        tmp_path=tmp_path,
        name="projector",
    )
    try:
        await support.wait_for_event(
            process, "the Projector's application startup complete", support.booted
        )
        await support.publish(
            kafka_server.bootstrap_servers,
            ORDERS_FACTS_TOPIC,
            correlation_id,
            value,
            headers=[("traceparent", TRACEPARENT.encode("ascii"))],
        )
        await support.wait_for_event(
            process,
            "the consumer's line for the unregistered fact",
            lambda line: "unregistered fact type" in line.get("event", ""),
        )
        exit_code = await support.stop(process)
    finally:
        support.kill(process)
    assert exit_code in {0, -15}, process.stderr_text()

    lines = support.check_contract(
        process,
        correlation_id=correlation_id,
        trace_id=TRACE_ID,
        provoked={
            "unregistered fact type": lambda line: (
                line["logger"] == "otc_projector.presentation.projector_facts_consumer"
                and line["event"].startswith("unregistered fact type")
            )
        },
    )
    assert any(line.get("traceId") == TRACE_ID for line in lines), (
        f"no line carries the inbound traceId {TRACE_ID}: "
        "the consume span did not continue the trace"
    )
