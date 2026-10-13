"""R58 for the Gateway: every line the REAL server writes is JSON; a request's id is on its lines.

* `test_r58_every_line_the_real_server_writes_...`: a real `python -m otc_gateway` child
  (`GATEWAY_PORT` a literal in the 38400s, free-checked first, as in
  `test_gateway_listens_on_gateway_port.py`; the settings refuse port 0) over the
  suite's Docker-held NATS and MongoDB. The unit of work is one HTTP request, `GET /orders` with an
  `x-correlation-id` and no token; it is refused 401, and the line uvicorn writes for it
  (`uvicorn.access`, a LIBRARY logger with no correlation argument) carries `correlationId` only
  because `CorrelationMiddleware` binds it around the inner app. EVERY stderr line is then judged
  (`tests/observability/log_contract_support.py`). The request also carries a `traceparent`: the
  lines carrying its trace id must be exactly the lines carrying the `correlationId` (S3: the
  `TelemetryMiddleware` span, outermost, continues the inbound trace, and uvicorn writes the access
  line from inside the app call, hence inside the span).
* `test_r58_a_problem_and_its_log_line_...` (#7's open point 6, #8 A3g): `CorrelationMiddleware` is
  OUTSIDE `ProblemMiddleware`, and a swap compiles and passed every test. A request that fails into
  a Problem (a wrong password) returns the id it sent in the body, and the failure line the Problem
  middleware writes carries the same id, read from the RENDERED line (a `LogRecord` does not hold a
  context variable). A Problem has no `X-Correlation-Id` response header: `openapi.yaml` declares it
  on the two 201 responses only (lines 228 and 722), so none is asserted.

Loop scope: function.
"""

import importlib.util
import io
import json
import logging
import socket
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

from otc_gateway.infrastructure.observability.logging import build_formatter
from otc_gateway.main import create_app

pytestmark = pytest.mark.integration

SUPPORT_PATH = Path(__file__).resolve().parents[4] / "tests/observability/log_contract_support.py"
OPERATOR_PASSWORD = "log-contract-operator-password"
JWT_SECRET = "log-contract-jwt-secret-0123456789abcdef-0123456789"
PORT = 38421

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TRACE_ID = TRACEPARENT.split("-")[1]


def load_support() -> Any:
    spec = importlib.util.spec_from_file_location("log_contract_support", SUPPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def something_listens(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


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


async def test_r58_every_line_the_real_server_writes_is_json_and_every_line_of_one_unit_of_work_carries_its_correlation_id_and_trace_id(  # noqa: E501
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, nats_server: Any, fresh_mongo_database: Any
) -> None:
    support = load_support()
    assert not something_listens(PORT), f"port {PORT} is already in use: free it and re-run"
    gateway_environment(monkeypatch, tmp_path, nats_server, fresh_mongo_database)
    monkeypatch.setenv("GATEWAY_HOST", "127.0.0.1")
    monkeypatch.setenv("GATEWAY_PORT", str(PORT))
    correlation_id = str(uuid.uuid4())
    process = support.spawn(
        support.python_module("otc_gateway"), cwd=tmp_path, tmp_path=tmp_path, name="gateway"
    )
    try:
        await support.wait_for_event(
            process, "the Gateway's application startup complete", support.booted
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"http://127.0.0.1:{PORT}/orders",
                headers={"x-correlation-id": correlation_id, "traceparent": TRACEPARENT},
            )
        assert response.status_code == 401, response.text
        assert response.json()["correlationId"] == correlation_id
        await support.wait_for_event(
            process,
            "the access line of the refused request",
            lambda line: line.get("logger") == "uvicorn.access" and "/orders" in line["event"],
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
            "uvicorn.access GET /orders": lambda line: (
                line["logger"] == "uvicorn.access" and "GET /orders" in line["event"]
            )
        },
    )
    assert any(line.get("traceId") == TRACE_ID for line in lines), (
        f"no line carries the inbound traceId {TRACE_ID}: "
        "the server span did not continue the trace"
    )


async def test_r58_a_problem_and_its_log_line_carry_the_request_correlation_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, nats_server: Any, fresh_mongo_database: Any
) -> None:
    gateway_environment(monkeypatch, tmp_path, nats_server, fresh_mongo_database)
    sent = str(uuid.uuid4())
    rendered = io.StringIO()
    handler = logging.StreamHandler(rendered)
    handler.setFormatter(build_formatter())
    asgi_log = logging.getLogger("otc_gateway.presentation.asgi")
    asgi_log.addHandler(handler)
    app = create_app()
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
            ) as client,
        ):
            response = await client.post(
                "/auth/login",
                json={"username": "operator", "password": "not-the-password"},
                headers={"x-correlation-id": sent},
            )
    finally:
        asgi_log.removeHandler(handler)
    assert response.status_code == 401, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["correlationId"] == sent
    failures = [json.loads(text) for text in rendered.getvalue().splitlines() if "refused" in text]
    assert len(failures) == 1, rendered.getvalue()
    assert failures[0].get("correlationId") == sent, (
        f"the Problem's failure line lacks the request's correlationId {sent}: {failures[0]}"
    )
