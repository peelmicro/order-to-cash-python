"""R56 / R57: the Gateway opens a SERVER span for a request, from its OWN provider, and the NATS
request it makes is that span's child (feature 27 `design.md` 4.4; S3.9; #8 D10).

The REAL runtime (`start_runtime(load_settings())`, the lifespan's own call, over the suite's NATS
and MongoDB containers) is built with an in-memory processor handed to ITS provider. Nothing in this
test instruments the application: no span is made around the call, no ASGI instrumentation is
installed, no global provider is set. A caller's span (a provider of the test's own) supplies the
inbound `traceparent`; a real NATS subscriber stands in for Fulfillment and records the headers the
Gateway's request arrived with. Health routes are not traced (a probe every few seconds would bury
the traces that matter).
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from otc_gateway.composition import load_settings, start_runtime
from otc_gateway.infrastructure.observability.trace_context import extract_nats
from otc_gateway.presentation.app import create_app

pytestmark = pytest.mark.integration

SUPPORT_PATH = Path(__file__).resolve().parents[4] / "tests/observability/trace_support.py"
OPERATOR_PASSWORD = "server-span-operator-password"
JWT_SECRET = "server-span-jwt-secret-0123456789abcdef-0123456789"
EMPTY_PAGE = json.dumps({"items": [], "page": {"page": 1, "pageSize": 25, "total": 0}}).encode()


def _support() -> ModuleType:
    spec = importlib.util.spec_from_file_location("trace_support", SUPPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


support = _support()


def gateway_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, nats: Any, mongo: Any
) -> None:
    monkeypatch.chdir(tmp_path)  # no developer `.env`
    for name, value in {
        "NATS_URL": nats.url,
        "MONGO_URI": mongo.uri,
        "MONGO_DB_READMODEL": mongo.name,
        "JWT_SECRET": JWT_SECRET,
        "GATEWAY_OPERATOR_PASSWORD": OPERATOR_PASSWORD,
    }.items():
        monkeypatch.setenv(name, value)


async def test_r56_a_request_with_a_traceparent_yields_a_server_span_of_the_runtimes_own_provider_and_its_nats_call_is_its_child(  # noqa: E501
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, nats_server: Any, fresh_mongo_database: Any
) -> None:
    gateway_environment(monkeypatch, tmp_path, nats_server, fresh_mongo_database)
    receiver = await support.Receiver.start(nats_server.url, ["fulfillment.stock.list"], EMPTY_PAGE)
    exporter = InMemorySpanExporter()
    running = await start_runtime(load_settings(), span_processors=[SimpleSpanProcessor(exporter)])
    app = create_app()
    app.state.runtime = running.runtime
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
        ) as client:
            login = await client.post(
                "/auth/login", json={"username": "operator", "password": OPERATOR_PASSWORD}
            )
            assert login.status_code == 200, login.text
            with support.caller_tracer().start_as_current_span("caller") as origin:
                caller = origin.get_span_context()
                inbound = support.traceparent_header_of_current_span()
            response = await client.get(
                "/stock",
                headers={"Authorization": f"Bearer {login.json()['accessToken']}"} | inbound,
            )
            assert response.status_code == 200, response.text
            await client.get("/health/live")
    finally:
        app.state.runtime = None
        await running.stop()
        await receiver.close()

    infos = support.span_infos(exporter)
    servers = [i for i in infos if i.kind == trace.SpanKind.SERVER and "/stock" in i.name]
    assert len(servers) == 1, f"expected exactly one SERVER span for GET /stock, got {servers}"
    (server,) = servers
    assert server.name == "GET /stock", "named by the route template once matched"
    assert (server.trace_id, server.parent_id) == (caller.trace_id, caller.span_id), (
        "R56 hop caller -> Gateway SERVER span: the span does not continue the inbound traceparent"
    )
    assert server.service == "gateway", "exported by the runtime's own provider"
    assert server.attributes["http.response.status_code"] == 200
    (call,) = support.by_name(infos, "fulfillment.stock.list request")
    assert call.kind == trace.SpanKind.CLIENT
    assert (call.trace_id, call.parent_id) == (server.trace_id, server.span_id), (
        "R56 hop SERVER span -> NATS CLIENT span: the call is not the SERVER span's child"
    )
    # the subscriber received the CLIENT span's context
    ((_, _, headers),) = receiver.received
    assert headers is not None, "R56 hop Gateway -> NATS: the request arrived with no headers"
    received = trace.get_current_span(extract_nats(headers)).get_span_context()
    assert (received.trace_id, received.span_id) == (server.trace_id, call.span_id), (
        "R56 hop Gateway -> NATS: the request does not carry the CLIENT span's traceparent "
        f"(trace id {received.trace_id}, span id {received.span_id})"
    )
    assert [i for i in infos if "/health/" in i.name] == [], "health routes are not traced"
