# `observability_reliability` — Design (assessment #9: Python 3.14, FastAPI, SQLAlchemy/asyncpg, aiokafka, nats-py, PyMongo, structlog, OpenTelemetry)

> Realises `requirements.md`: shared `R16`, `R29`'s dead-letter clause, `R56` (mechanism), `R57` – `R60`, `R62`; local `OR1` – `OR13`, `RI1` – `RI5`.
>
> **Read §11 (the ported-idiom ledger) and §14 (the defect classes of #8's three rejections) first.** #8's counterpart took four review rounds, three rejected, ≈3.1× #7 (`../order-to-cash-dotnet/progress/history.md:2122`); eleven blocking defects, most of them *guards that could not see their own defect*. §14 turns each class into a named guard or a stated "not applicable because".
>
> **Staging.** `tasks.md` is ordered into eight stages, each a coherent slice that ends green with its arms done: **S1** log contract → **S2** `R62` → **S3** tracing → **S4** retry / DLQ / first park / migration `0003` (items 8, 10, 11, 12) → **S5** metrics → **S6** readiness → **S7** items 7, 9, 13 → **S8** close-out and live walkthrough. The leader decides the review cadence; a pass may end at any stage boundary.

---

## 1. Scope and what exists

### 1.1 Census (commands run 2026-10-12, this session)

| Fact | Command | Result |
|---|---|---|
| No structured logging, no OTel | `grep -rln 'structlog\|opentelemetry' services/*/src packages/*/src` | 0 files |
| stdlib logging users | `grep -rl 'import logging\|from logging' services/*/src packages/*/src` | 36 files |
| No logging configured | `grep -rn 'basicConfig\|dictConfig' services/*/src` | 0 |
| `opentelemetry-api` already locked | `uv.lock` | `opentelemetry-api 1.45.0`, pulled by **`fastapi 0.142.2`** (`Requires-Dist: opentelemetry-api>=1.44.0`) |
| FastAPI ships native telemetry | `.venv/.../fastapi/telemetry/_runtime.py`, `_asgi.py`, `applications.py:1033-1045, 1197-1225` | server spans + HTTP metrics whenever a global provider is configured; `auto_configure` adds OTLP exporters from `OTEL_*` at lifespan start (§4.6) |
| `traceparent` placeholders | `grep -rn 'feature 27' services/*/src` | `application/ports/fact_stream.py:20` (×3 consumers), `orders/.../outbox/wire.py:8`, `outbox/writer.py:69` (`trace_parent=None`), `messaging/nats_saga_commands.py:22` |
| RPC responders and subjects | `grep -n 'SUBJECT = "' services/{orders,fulfillment,billing}/src/*/infrastructure/messaging/subjects.py` | 3 responder classes (`orders_create_responder.py`, `stock_responder.py`, `credit_responder.py`); **15 subjects** (Orders 3, Fulfillment 6, Billing 6) |
| Kafka client confinement literal | `tests/architecture/test_kafka_client_confinement.py:27-37` | 6 modules import aiokafka today |
| Copy families already guarded | `tests/architecture/test_outbox_copy_parity.py` (9 modules × Fulfillment, Billing); `services/orders/tests/unit/test_idempotent_consumer_parity.py` (declared `IDEMPOTENCY_MODE`) | the instruments this feature extends |
| Test Kafka topics | root `conftest.py:242-245, 320` | the three fact topics only; `KAFKA_AUTO_CREATE_TOPICS_ENABLE=false` — **no `.dlq` topic exists in tests** |
| `otc_orders` migration head | `services/orders/alembic/versions/` | `0002_saga_commands_operator_note.py` |
| R62 schema | `0001_initial_orders_schema.py:101, 126`; `persistence/models.py:115, 122` | `request_id uuid NULL` + plain `CREATE UNIQUE INDEX uq_orders_request_id` (PostgreSQL's default `NULLS DISTINCT`) |

### 1.2 The thirteen acceptance items → stages

| Item | Claim (short) | Stage | Requirement |
|---|---|---|---|
| 1 | one trace HTTP → NATS → write DB → Kafka → consumers | S3 (mechanism per hop) | R56 mechanism, R57, OR4, OR10 |
| 2 | `correlationId` in every log line | S1 | R58, OR7 |
| 3 | `<topic>.dlq` after N attempts, SA-3 headers, selected by content | S4 | R16, OR1, OR2, OR8 |
| 4 | readiness bounded, proven against paused containers | S6 | R60, OR6 |
| 5 | repeated `requestId` → original; concurrent → one order | S2 | R62, RI1 – RI5 |
| 6 | the five series names | S5 | R59, OR9 |
| 7 | no fixture runs a server with reload, by enumeration | S7 | — (repository guard) |
| 8 | re-run SO9 arms after the wrapper (#8 id 94) | S4 | SO9, OR8 |
| 9 | terminal `rejected` decided and armed | S7 | OR11 |
| 10 | `earliest` consumer tests on private topics | S4 (first task) | — (test isolation) |
| 11 | re-run the Projector's `I4-commit-before-handler` and `PR38` | S4 | PR38, OR8 |
| 12 | operator-cancel park's dead letter | S4 | OR12 (gate G1) |
| 13 | no ERROR line from an SSE stream open at shutdown | S7 | OR13 |

### 1.3 What this feature does not do

- The composed-stack observation of `R56` (all services, a real Jaeger): feature 28, acceptance item 4. This feature proves every **hop** against an in-memory exporter, and shows one Jaeger trace in the live walkthrough (§16), which is evidence, not the guard.
- Dashboards: feature 35. `infra/` is **not edited**: `infra/otel-collector/otel-collector-config.yaml` and `infra/prometheus/prometheus.yml` are already in their post-decision state (measured in §6.1).
- A `.dlq` redrive consumer: `asyncapi.yaml:194-196` makes redrive a human act.
- Fulfillment and Billing fact consumption: neither consumes a fact; neither receives the retry module, and `OR2`'s guard asserts it.
- The projector's NATS update signals (`readmodel.*`): not declared in `asyncapi.yaml` (`grep -n readmodel specs/shared/asyncapi.yaml` → 0), not in `R56`'s list of units of work, and neither #7 nor #8 injects there (`grep -rln traceparent` over `../order-to-cash-dotnet/src/Projector` and `../order-to-cash-nestjs/apps/projector/src` names only the consumer and the dead-letter publisher). Not applicable.

---

## 2. Stage S1 — the log contract (`R58`, `OR7`; acceptance item 2)

### 2.1 Rendering: structlog renders, stdlib stays the call API

Every service keeps its 36 `logging.getLogger(...)` call sites and their `extra={...}` fields. structlog is the **renderer**: one `logging.StreamHandler(sys.stderr)` on the root logger whose formatter is `structlog.stdlib.ProcessorFormatter` with:

- `foreign_pre_chain` (records from stdlib loggers, i.e. ours and every library's): `structlog.contextvars.merge_contextvars` (brings `correlationId`), `structlog.stdlib.add_log_level`, `structlog.stdlib.add_logger_name`, `structlog.stdlib.ExtraAdder()` (our `extra` fields), `add_trace_context` (below), `structlog.processors.TimeStamper(fmt=None)` replaced by our own processor writing `timestamp` through `otc_contracts.wire.format_instant` (one instant format, `wire.py:47`), `structlog.processors.format_exc_info`;
- `processors`: `ProcessorFormatter.remove_processors_meta`, `structlog.processors.JSONRenderer(serializer=…)` whose serializer is compact JSON with `ensure_ascii=False` (CLAUDE.md "JSON wire shape", applied to log lines too).

`add_trace_context` reads `opentelemetry.trace.get_current_span().get_span_context()` **at format time**; when `is_valid` it adds `traceId` (32 hex) and `spanId` (16 hex), otherwise it adds **neither key** (`OR7`'s omit clause; #7 `apps/orders/src/presentation/saga-facts-log-trace-id.spec.ts:71`, #8 `LogCorrelationTests` › `…OmitsTheTraceFieldsEntirely…`).

Why stdlib stays the API: the existing tests read `LogRecord` attributes through `caplog` (`services/orders/tests/integration/saga/test_saga_consumption.py:111-118` filters on `r.levelno`, `getattr(r, "offset")`); `ProcessorFormatter` changes no record, so those guards keep their meaning. The handler is **synchronous**: the trace fields are read in the emitting task's context. A `QueueHandler` would format on another thread, where `get_current_span()` is the invalid span and every line silently loses its trace (ledger L7).

Key names are the wire's: `correlationId`, `traceId`, `spanId`, `level`, `logger`, `event`, `timestamp`. **One literal key `correlationId` at every binding site** — #8 bound `order_id` in its saga dispatcher (`src/Orders/Infrastructure/Saga/SagaCommandDispatcher.cs:84`) and `correlation_id` in its relay (`src/Orders/Infrastructure/Outbox/OutboxRelay.cs:151`), so those lines carried no `correlationId` key at all; §2.4's census guard makes the key a literal.

### 2.2 Where it is installed, and uvicorn's own lines

`otc_<svc>/infrastructure/observability/logging.py` (a six-service copy family, §8.2) exposes `install_json_logging(service: str) -> None`, idempotent (the handler is tagged; a second call adds nothing), which:

1. adds the one handler to the root logger and sets the root level to `INFO`; it **never removes** other root handlers (pytest's `caplog` handler must survive);
2. for each logger in the literal `FOREIGN_HANDLER_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")`, removes that logger's own handlers and sets `propagate = True`, so uvicorn's lines reach the root handler.

It is called **at module level in each service's `main.py`**, before `app = create_app()`. The reason is measured, not assumed: uvicorn applies its `LOGGING_CONFIG` in `Config.__init__` (`uvicorn/config.py:303`), imports the app in `config.load()` and only then logs `Started server process [%d]` (`uvicorn/server.py:96-103`). Configuring in the lifespan instead would leave `Started server process` and `Waiting for application startup.` in uvicorn's plain-text format. `main.py` lives outside the layers (CLAUDE.md), and installing a stderr handler reads no configuration and opens no resource; each `main.py` docstring's "Importing this module reads no configuration and opens nothing" is kept true and gains one sentence saying so. The Gateway's `python -m otc_gateway` path runs `uvicorn.run("otc_gateway.main:app", …)` and therefore follows the same order.

### 2.3 The population of loggers that emit, and the contract per logger

Population, from a run (not from memory): `uv run pytest services/orders/tests/integration/saga/test_saga_happy_path.py::test_saga_reaches_invoiced_then_completed_from_orders_create_against_stand_in_responders services/orders/tests/integration/test_orders_host_lifespan.py::test_a_transport_task_that_dies_takes_readiness_down_and_names_it --log-level=DEBUG -rP --log-format='LOGGER|%(name)s|%(levelname)s'`, emitting loggers counted (3 passed, 9.26 s): `aiokafka.consumer.fetcher` 420, `aiokafka.conn` 289, `aiokafka.consumer.group_coordinator` 84 + 9 INFO, `urllib3.connectionpool` 70, `docker.utils.config` 52, `aiokafka` 49, `docker.auth` 25, `aiokafka.producer.producer` 22, `aiokafka.cluster` 18, `aiokafka.admin.client` 13, `testcontainers.core.*` 22, `asyncio` 5, `httpx` 4, `alembic.runtime.migration` 6, `aiokafka.consumer.consumer` 4, `aiokafka.producer.sender` 3, `aiokafka.consumer.subscription_state` 2, `otc_orders.composition` 4, `otc_orders.saga.fact_handler` 1. Complemented by a static enumeration of the runtime dependencies (`grep -rhoE 'getLogger\([^)]*\)'` over the installed packages): `uvicorn.error`, `uvicorn.access`, `uvicorn.asgi`, `fastapi`, `nats.*` (`__name__`), `sqlalchemy.engine`/`pool`/`dialects.postgresql`, `asyncpg`, `pymongo.{client,command,connection,serverSelection,topology}`, `alembic`, `opentelemetry.*`.

| Logger family | Emits in production | Inside a unit of work? | Contract |
|---|---|---|---|
| `otc_<svc>.*` | yes | at the binding sites of §2.4; boot/shutdown lines outside | JSON always; `correlationId` + trace on every line inside a unit; none fabricated outside |
| `uvicorn.error` | boot, shutdown, `Exception in ASGI application` | the exception line is emitted in the request task | JSON always (§2.2); OR13 removes the shutdown ERROR lines at the source (§9.3) |
| `uvicorn.access` | one line per HTTP request, from `send(http.response.start)` inside the request task | yes (Gateway requests) | carries the Gateway's binding because it runs inside the middleware's `bound_contextvars` |
| `aiokafka.*` | INFO at group join/rebalance; WARNING/ERROR on connection loss | background coroutines created at `consumer.start()` / `producer.start()` carry the context of `start()` (none) | JSON; no `correlationId` (not produced while handling a fact). A producer `send` inside a relay row's binding inherits it |
| `nats.*` | reconnect/error callbacks | background reading task | JSON; no `correlationId` |
| `sqlalchemy.*`, `asyncpg` | silent at INFO (no `echo`) | — | JSON if ever emitted |
| `asyncio` | `Task exception was never retrieved`, slow-callback in debug | loop callbacks, no context | JSON; no `correlationId` |
| `opentelemetry.*` | exporter failures (`Failed to export …`) from the exporter's own thread | no | JSON; no `correlationId` |
| `alembic.*`, `httpx`, `urllib3`, `docker.*`, `testcontainers.*` | test harness only (no service runs migrations at boot; httpx is a test client) | — | classified test-only; outside the contract |

### 2.4 Binding sites (the units of work)

`structlog.contextvars.bound_contextvars(correlationId=str(id))` — the **context-manager** form, which resets on exit — at exactly these sites (literal population for `tests/architecture/test_correlation_binding_sites.py`):

| Service | Site | Value |
|---|---|---|
| Gateway | `presentation/asgi.py` `CorrelationMiddleware.__call__`, around the inner app call | the request's correlation id (already resolved there) |
| Orders, Fulfillment, Billing | each responder's per-message `_serve` | `x-correlation-id` header when it parses as a UUID; otherwise no binding (never a fabricated id) |
| Orders, Projector, Notifications | each facts consumer's `handle`, immediately after the envelope guard | `envelope.correlation_id` |
| Orders | `infrastructure/saga/command_dispatcher.py` around one row's dispatch (fast path and sweeper) | the row's `order_id` (the correlation id, `saga.md` §1) |
| Orders, Fulfillment, Billing | `infrastructure/outbox/relay.py`, around the publication of one row | the row's `correlation_id` |

**Revision 2026-10-12 (S1, implementer).** The relay row reads "around the publication of one row", but `OutboxRelay._cycle` publishes a BATCH through `FactPublisher.publish(facts)`: there is no per-row publication in `relay.py` to wrap. The delivered site is `OutboxRelay._cycle` (three copies), wrapping the per-row error log emission (the only per-row lines the relay writes); S3.5 starts the per-row `outbox.publish` span and can move the binding with it. The explicit `extra={"correlationId": ...}` the relay, the dispatcher and the fast path already passed are kept (tests read them as `LogRecord` attributes), so for those sites a deleted binding is caught by the census (`test_correlation_binding_sites.py`) and not yet by a rendered line; the per-service real-process tests (S1.6) delete-arm the responder, consumer and Gateway sites on lines that carry no explicit argument.

The bare `bind_contextvars` is forbidden in `services/*/src` (census guard): in a consumer loop that runs in **one** task, a binding that is not reset leaks fact N's id onto fact N+1's lines (ledger L8). The fast path's dispatch tasks are created inside the fact's handling and copy its context (orchestrator design L7), so they inherit the binding and the span with no capture field.

### 2.5 Guards

- **Every line, per service, through the real server** — `services/<svc>/tests/integration/test_<svc>_log_contract.py` ×6 (literal set; #8 D2 found the settings guarded in two hosts of six). Each starts the **real** process (`python -m uvicorn otc_<svc>.main:app --port 0`, the pattern of `services/orders/tests/integration/test_orders_host_sigterm.py:44-45`; the Gateway through `python -m otc_gateway`, `test_gateway_listens_on_gateway_port.py`) against the suite's containers, drives one unit of work through its real transport, stops it with SIGTERM, and asserts over **every** stderr line: it parses as one JSON object with `level`, `logger`, `event`, `timestamp`; every line carrying the unit's `traceId` carries the unit's `correlationId` and vice versa; at least the lines the test provokes (named per service) are among them; no line carries an empty `traceId`/`correlationId`. Armed by: removing the root handler install (lines become plain text), removing the uvicorn propagation step (the `Started server process` line is plain), removing `merge_contextvars` from the pre-chain, dropping one binding site per service.
- **Unit rendering** — `services/orders/tests/unit/test_log_rendering.py`: omit-not-empty with no span; `extra` fields rendered; non-ASCII written raw; a binding does not outlive its `with` (two consecutive units in one task, the second's line carries the second id). Armed by `ensure_ascii=True`, by `bind_contextvars` without reset.
- **Ordering of the Gateway middlewares** (#7's open point 6, #8 A3g): `CorrelationMiddleware` is outside `ProblemMiddleware` (`asgi.py:6-7`), and `correlation_of` falls back to `uuid4()` when the scope has none (`asgi.py:39-41`). A swap compiles and passes every test today. `test_gateway_log_contract.py` › `test_r58_a_problem_and_its_log_line_carry_the_request_correlation_id` — armed by swapping the two middlewares.

---

## 3. Stage S2 — `R62` idempotent replay (`RI1` – `RI5`)

### 3.1 Schema: none owed, one property to prove

`uq_orders_request_id` exists since `0001` as a plain unique index. PostgreSQL treats NULLs as **distinct** in a unique index unless `NULLS NOT DISTINCT` is declared (PostgreSQL 15+), so any number of orders without a `requestId` are admitted — the property #7 got from MySQL (`apps/orders/src/infrastructure/persistence/schema/orders.schema.ts:34-37`) and #8 had to restore with a filtered index (#8 `design.md` §2.1, L1). **No migration for R62.** Task S2.1 reads `pg_index.indnullsnotdistinct` for the index from the real catalog and records it; the guard is two orders with no `requestId` (`RI4`), armed by recreating the index `NULLS NOT DISTINCT` in the test database.

### 3.2 Flow

1. **Fast path (RI2)** — before reference data: when `command.request_id` is set, open a read transaction and `tx.orders.find_by_request_id(request_id)`; a hit returns `PlaceOrderResult` built from the stored order through the same mapper the write path uses (no second projection).
2. **Insert** — `transaction.orders.save(order, request_id=command.request_id)`; `order_mapper` writes it (`order_mapper.py:57` stops writing `None`). The domain `Order` does not learn the request id: it is a request property, not an aggregate one.
3. **RI5** — `causation_id = UniqueId(command.request_id) if command.request_id else UniqueId.new()` (`place_order.py:166`).
4. **Race (RI3)** — PostgreSQL aborts the whole transaction on any error, so the collision **cannot** be caught inside it (orchestrator design L10, same engine fact). The unit of work's `begin()` (`infrastructure/persistence/unit_of_work.py:88`) translates an `IntegrityError` whose underlying asyncpg `UniqueViolationError` names `constraint_name == "uq_orders_request_id"` into the application exception `RequestIdAlreadyPlacedError` (a port-level type in `application/ports/unit_of_work.py`), **after** the rollback; any other integrity error (e.g. on `orders.order_reference`) propagates unchanged. The handler catches it **outside** `async with begin()` and re-reads the winner in a new transaction; no winner found → the original error propagates (never a silent `None`).

The structured `constraint_name` is better than #8's message parse (#8 L3), **but the attribute path through SQLAlchemy's asyncpg adapter is an engine claim**: task S2.3 captures, from a real `postgres:18.6` container, the exception chain (`type(error.orig)`, `error.orig.__cause__`, `constraint_name`, `sqlstate`) and quotes it in the record before the translation is written.

### 3.3 Why no orphan outbox row

The outbox row is written by `transaction.orders.save` in the same transaction (`order_repository.py:60-71`) — before or after the orders `INSERT` does not matter in PostgreSQL, because the failed transaction is rolled back whole. #8's trap (L2: outbox row first, collision caught inside the transaction and committed) cannot be built here; the guard still counts it: after the race the `outbox` holds **exactly one** `order.placed.v1` for the request.

### 3.4 The race test creates its own overlap

Both requests must pass the fast path before either commits, or the test proves only the fast path. The Orders responder serves each request in its own task (`orders_create_responder.py:159`), so one runtime suffices. The test's stand-in `fulfillment.stock.check` responder **holds both replies until both requests have arrived**, then releases them together: both are past the fast path, both enter their transactions, and they serialise only on the order-number counter (`FOR UPDATE`) and the unique index. Repeated ≥ 5 rounds. Assertions: one `orders` row for the request id, one `order.placed.v1` outbox row, both replies equal field by field (all three money fields). Armed: delete the translation (the loser answers an error), translate every integrity error (an `order_reference` collision is then swallowed — the unit case), and drop the barrier (the test must then report that it did not observe a collision, not pass: the case asserts the translation path ran exactly once per round, read from a counter the test injects).

---

## 4. Stage S3 — tracing (`R56` mechanism, `R57`, `OR4`, `OR5`, `OR10`; acceptance item 1)

### 4.1 Packages

`opentelemetry-sdk==1.45.0` and `opentelemetry-exporter-otlp-proto-http==1.45.0` (the API is already at 1.45.0 through FastAPI; one band, recorded). Probed in an isolated venv this session: all import cleanly under `-W error::DeprecationWarning -W error::PendingDeprecationWarning`; the SDK, the exporter and structlog ship `py.typed`; a probe module using `TracerProvider`, `BatchSpanProcessor`, `InMemorySpanExporter`, `InMemoryMetricReader`, `TraceContextTextMapPropagator` and `structlog.contextvars` passes `mypy --strict` with **no new override**. One `Any` leak was measured: `InMemorySpanExporter().get_finished_spans()[0].context` reveals `Any`; tests read spans through one typed helper (`span_ids(span) -> tuple[int, int, int | None]`).

**Not added**, each with its reason: `opentelemetry-exporter-otlp-proto-grpc` (pulls `grpcio 1.84.0`, a compiled dependency; the collector accepts OTLP/HTTP on 4318, `otel-collector-config.yaml:9-13`; FastAPI's own auto-configuration uses http/protobuf); `opentelemetry-instrumentation-{fastapi,asgi,sqlalchemy,asyncpg,aiokafka}` (all `0.66b0`, monkey-patching; the Kafka one would inject the *current* context into producer headers, colliding with the relay's restored context; neither #7 nor #8 instrumented Kafka or the database by package); no NATS instrumentation exists on PyPI (`uv pip compile` of `opentelemetry-instrumentation-nats` → "not found in the package registry").

### 4.2 Providers belong to the lifespan, never to the process

`otc_<svc>/infrastructure/observability/telemetry.py` (copy family) builds, inside `start_runtime`, one `TracerProvider(resource=Resource({"service.name": "<svc>"}), sampler=ParentBased(ALWAYS_ON))` and one `MeterProvider(resource=…, metric_readers=[…])`; with `TelemetrySettings.otlp_endpoint` set it adds `BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{base}/v1/traces"))` and `PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"{base}/v1/metrics"))` — **an explicit endpoint is used verbatim, path included** (`opentelemetry/exporter/otlp/proto/http/trace_exporter/__init__.py:118, 139`); with it empty, no exporter. The runtime's `stop()` calls `force_flush()` and `shutdown()` on both, last, after every task is awaited.

**The global providers are never set.** `trace.set_tracer_provider` and `metrics.set_meter_provider` are set-once per process ("Overriding of current TracerProvider is not allowed", `opentelemetry/trace/__init__.py:552`, `metrics/_internal/__init__.py:867`): one pytest process boots many runtimes, and several Gateway tests boot Orders, the Projector and the Gateway in one process, so a global provider would give every later runtime the first one's exporter and `service.name`. Every component that makes a span or a measurement receives a `Tracer` / instrument from its runtime's providers through the composition root. Propagation uses an explicit `TraceContextTextMapPropagator()` instance, never `opentelemetry.propagate`, which reads `OTEL_PROPAGATORS` from the environment at import (`opentelemetry/propagate/__init__.py:108, 157`) — an environment read outside pydantic-settings. `Resource(...)` is constructed directly, never `Resource.create(...)`, whose detectors read `OTEL_SERVICE_NAME` / `OTEL_RESOURCE_ATTRIBUTES`. The sampler is passed explicitly, so `OTEL_TRACES_SAMPLER` is not read.

### 4.3 The one carrier module

`otc_<svc>/infrastructure/observability/trace_context.py` (six-service copy family): pure functions over `dict[str, str]` (NATS) and `Sequence[tuple[str, bytes]]` (Kafka): `inject_nats(headers, context)`, `extract_nats(headers) -> Context`, `kafka_trace_headers(context) -> tuple[tuple[str, bytes], ...]`, `extract_kafka(headers) -> Context`, `current_traceparent() -> str | None`, `context_from_traceparent(value: str | None) -> Context | None` (malformed → `None`, never a raise). With no valid span, no `traceparent` is produced (`OR4`).

### 4.4 The hops

| Hop | Inject | Extract / continue | Span |
|---|---|---|---|
| HTTP → Gateway | — | `traceparent` request header | `TelemetryMiddleware` (new, pure ASGI, outermost in `presentation/asgi.py`): `SERVER` span `"<METHOD> <route template>"`, status from the final response; health routes excluded |
| Gateway → NATS | `infrastructure/nats_rpc_client.py:60` header dict (built per call) | — | `CLIENT` span per request |
| Orders → NATS (saga commands, stock check) | `nats_saga_commands.py` (headers per call, orchestrator L19), `nats_stock_availability.py:57` | — | `CLIENT` span per request |
| NATS → responder | — | the per-message `_serve` of each of the 3 responder classes, covering all 15 subjects | `SERVER` span per request |
| Write transaction | — | — | `writemodel.transaction` `INTERNAL` span around each transaction of `orders/.../persistence/unit_of_work.py`, `fulfillment/.../persistence/stock_transactions.py`, `billing/.../persistence/credit_transactions.py` (implementer confirms the population by search), and Notifications' delivery-ledger transactions — #8's L23, stronger than #7 |
| Write → outbox | `outbox/writer.py:69`: `trace_parent = current_traceparent()` (NULL with no span) | — | — |
| Outbox → Kafka | `outbox/relay.py` + `wire.py`: restore the row's `trace_parent`, start a `PRODUCER` span `outbox.publish` under it, inject **that** span's context as the `traceparent` header (#7 `trace-context.spec`, #8 `OutboxRelay.cs:211-219`); a row with NULL `trace_parent` publishes no header | — | `PRODUCER` |
| Kafka → consumer | — | `kafka_fact_subscriber.py` (×3) wraps each `handler(message)` call in a `CONSUMER` span whose parent is `extract_kafka(record.headers)` — so the malformed-envelope log line, the retries and the dead letter all carry the inbound trace (#8 `LogCorrelationTests` › `…MalformedEnvelopeLogCarriesTheRealInboundTraceId`) | `CONSUMER` |
| Fact → saga fast path | — | the dispatch task copies the fact's context at creation (orchestrator L7, `design.md` §11) | `CLIENT` span of the command |
| Sweeper → command | — | `OR10`: `saga_commands.trace_parent` (migration `0003`, written at enqueue from the current context) restored as the parent of the dispatch | `INTERNAL` `saga.command.dispatch` |

The outbox modules are a copy family (`test_outbox_copy_parity.py`): the change is made in the canonical (Orders) and the two copies follow byte for byte; the existing parity test is the guard that they do.

### 4.5 What "continued" means in a test

A test that asserts "a `traceparent` header is present" proves nothing: a fresh span produces one. Every continuation assertion extracts the header back, compares the trace id to the **real originating span's** and asserts the span id differs and the parent span id is the originator's (#8 L24). Every responder and consumer is driven **through its production class** over the real transport; a stand-in that re-implements extraction is not a guard (#8 D1). The Gateway server span is asserted exported by the **runtime's own** provider with no test-owned instrumentation (#8 D10).

### 4.6 FastAPI's native telemetry is switched off, explicitly, in all six apps

FastAPI 0.142.2 creates server spans and `http.server.request.duration` metrics whenever a global provider is configured, and at lifespan startup adds OTLP exporters from `OTEL_EXPORTER_OTLP_ENDPOINT` unless `auto_configure` is false (`fastapi/telemetry/_runtime.py:76-197`, `applications.py:1033-1045`). Every `create_app` passes `telemetry={"tracing": False, "metrics": False, "logs": False, "operation_spans": False, "auto_configure": False}`. Guard (`tests/architecture/test_telemetry_wiring.py`): with a global SDK provider installed **by the test** and `OTEL_EXPORTER_OTLP_ENDPOINT` set, one request to each app yields no FastAPI span and no FastAPI instrument; armed by deleting the argument from one app.

---

## 5. Stage S4 — retry, dead letter, first park (`R16`, `R29`, `OR1` – `OR3`, `OR8`, `OR12`; items 3, 8, 10, 11, 12)

### 5.1 Item 10 first: private topics for every `earliest` consumer test

Before any poison fact is published by a test, the population is enumerated (`grep -rln 'KafkaFactSubscriber\|start_runtime\|saga_harness\|AIOKafkaConsumer' services/*/tests tests`, then each module classified as *private topics* / *committed to end first* / *never earliest*), and every new dead-letter test runs on **private source topics and private `.dlq` companions** created by the test (the Projector's `Topics` precedent, `services/projector/tests/integration/conftest.py:239-252`). The Orders saga harness (`services/orders/tests/integration/saga/conftest.py:830-857`) and the Notifications harness gain the same seam the Projector's `Externals` provides: the runtime's subscriber and dead-letter publisher are built over topics the test names, through the composition root's existing test seam — never an environment variable production could set. The SO1 test (`test_saga_consumption.py:65`) still reads the real topics' history; after this feature no suite publishes a poison fact there, and S4.1's enumeration is what proves it.

### 5.2 Where the wrapper sits, per consumer

| Consumer | Outside the wrapper (log and acknowledge, unchanged) | Inside the wrapper |
|---|---|---|
| Orders (`presentation/saga_facts_consumer.py`) | malformed envelope; the four self-produced facts (`SO2`); an unknown `eventType` | `dispatcher.send(command_type(envelope=…, topic=…, raw=message.value), scope)` with a **fresh scope per attempt** — per-fact payload validation and `UniqueId` construction already happen inside the handler (orchestrator L23) |
| Projector (`presentation/projector_facts_consumer.py`) | malformed envelope | `parse_fact(message.value)` + `dispatcher.send(...)`; `UnknownFactTypeError` is caught **inside** the wrapped callable and logged at ERROR, returning normally (`PR4`; #7 and #8 L11) |
| Notifications (`presentation/notification_facts_consumer.py`) | malformed envelope; a type not in `NOTIFIED_FACTS` | `from_wire_json(notified.event_model, …)` + `dispatcher.send(...)`. A **permanent** SMTP failure never reaches the wrapper: `DegradingNotificationSender` renders it to the console and returns (`degrading_sender.py`, #8 id 73); a **transient** one is re-raised and retried; `dispatch`'s forget-on-throw (`application/dispatch.py`) runs per attempt, so the next attempt genuinely re-sends |

### 5.3 The wrapper (canonical `otc_orders/infrastructure/messaging/fact_retry.py`, copied to the Projector and Notifications)

```python
class FactRetry:
    def __init__(self, *, consumer: ConsumerName, policy: FactRetryPolicy, clock: Clock,
                 sleep: Callable[[float], Awaitable[None]], dead_letters: DeadLetterPublisher,
                 latency: FactLatency) -> None: ...

    async def process(self, message: FactMessage, event_type: str,
                      work: Callable[[], Awaitable[None]]) -> None: ...
```

- `entered = clock.now()`; `for attempt in range(1, policy.max_attempts + 1)`: `await work()` and on success record latency and **return**; `except Exception as error`: `first_failed_at = first_failed_at or clock.now()` **inside the except** (the first failure's instant, `SA-3`; #8 id 75), `last_failed_at = clock.now()`, log WARNING with `attempt`, `maxAttempts`, `eventType`, `error`; if another attempt remains, `await sleep(policy.backoff_ms * (1 << (attempt - 1)) / 1000)`.
- `asyncio.CancelledError` is a `BaseException`, so `except Exception` never catches it: a shutdown during `work()` or `sleep` propagates, is never counted and never dead-lettered (ledger L10). No `except BaseException`, no bare `except:`.
- Exhausted: `await dead_letters.publish(DeadLetter(source_topic=message.topic, key=message.key, value=message.value, consumer=…, attempts=<the loop's own count>, error=…, first_failed_at=…, failed_at=last_failed_at, event_type=event_type))`, record latency, return. **If `publish` raises, the exception propagates** (`OR8`): the subscriber does not commit, seeks back and redelivers (`kafka_fact_subscriber.py` `_consume`), and the record gets another full round of attempts.
- `x-attempts` comes from the loop's own counter, never from `policy.max_attempts` read at the end (#8 L19).
- Latency (`otc_fact_processing_latency_ms`, tag `consumer`) is `(clock.now() - entered) / timedelta(milliseconds=1)` — a float of milliseconds exact to the microsecond, from the **injected clock** so a unit test asserts an exact value (#8 D8: `>= 0` guarded nothing). Recorded on success and on the dead-letter path.
- The module takes only ports (`Clock`, `DeadLetterPublisher`, `FactLatency`); it imports no aiokafka, so the presentation task may hold it (`fact-producer-confinement`).

`FactRetryPolicy` is built from `FactRetrySettings` (`FACT_RETRY_MAX_ATTEMPTS`, default 3, refused outside `1 … 10`; `FACT_RETRY_BACKOFF_MS`, default 500, refused below 0), one `validation_alias` each, in each consuming service's `infrastructure/settings.py`; the class joins `test_composition_env_reads.py`'s `EXPECTED_SETTINGS` (an instrument change, re-armed).

**S4a delivery notes (deviations, with reasons).** (1) The presentation task holds the wrapper through a port, `FactProcessor` in each service's `application/ports/fact_stream.py` (the layers contract lets `presentation` import `infrastructure`, but the port keeps the task testable with a recording fake and keeps `application` free of the concrete class); `FactRetry` satisfies it structurally. (2) `FactRetry` takes the consumer token as a plain `str` and a local `FactClock` protocol, so the copied module names no per-service enum and no per-service clock port (the Projector has none; it gained a one-class `infrastructure/clock.py`). (3) The test seams are keyword arguments of `start_runtime` in Orders and Notifications (`fact_topics`, `dead_letter_producer_factory`) and a field of the Projector's existing `Externals` (`dead_letters`); production passes none. (4) In Orders the dead-letter producer is started only when `SAGA_CONSUMER_ENABLED` is true (the existing host tests boot with `KAFKA_BROKERS` pointing at a closed port and the relay off); S4.14's first-park hook needs the publisher regardless, and decides then whether to start it unconditionally. (5) *Superseded by S4b (leader decisions F1, F2):* the back-off is stop-aware. The composition hands `FactRetry` a `sleep` built by `stop_aware_sleep(<the consumer's stop event>)`, which raises `FactRetryStopped` (not a `CancelledError`, which still propagates untouched) when the signal ends the wait; `process` lets it out, the subscriber names it and logs an INFO line, not the handler-failure line, with no commit, no seek and no failure count, so the record is redelivered after the restart for a fresh round of attempts (ledger L41; task S4.24). And the settings refuse at boot a `FACT_RETRY_MAX_ATTEMPTS` x `FACT_RETRY_BACKOFF_MS` whose worst-case total back-off, `backoff x (2^(attempts-1) - 1)`, reaches the consumer's `max_poll_interval_ms` (300 000, now configured explicitly by each subscriber from one constant in `infrastructure/settings.py`; aiokafka's own default): between attempts the partition is held and nothing is polled (task S4.25).

### 5.4 The dead-letter publisher (canonical `otc_orders/infrastructure/messaging/dead_letter_publisher.py`, copied)

- One `AIOKafkaProducer` per service, built and started **inside the lifespan's loop** and stopped by it (ledger L13), over **the service's own `KafkaSettings.brokers`** — there is no second bootstrap setting to default to `localhost` (#8 id 104). `acks="all"`, `enable_idempotence=True` (#7 `kafka-dlq-publisher.ts:62`, #8 `KafkaDeadLetterPublisher.cs:41-42`); `send_and_wait` returns only after the broker's acknowledgement, which is the durability `OR8` waits for. `client_id` `otc-<svc>-dlq` joins `test_kafka_client_ids.py`.
- Topic `f"{source_topic}.dlq"`; **key = the original record key** (the correlation id; `asyncapi.yaml` `DeadLetterRecord.bindings.kafka.key` is `UniqueId`, as #7 `kafka-dlq-publisher.ts:65`; #8 keyed by event type, `KafkaDeadLetterPublisher.cs:72`); **value = the original bytes**, never a re-serialised envelope.
- Headers, all `bytes` (UTF-8): `x-failed-consumer`, `x-attempts` (decimal), `x-error` (`f"{type(error).__name__}: {error}"`, cut to 1 000 characters; no traceback), `x-original-topic`, `x-first-failed-at`, `x-failed-at` (both through `format_instant`, `YYYY-MM-DDTHH:MM:SS.mmmZ` — never `isoformat()`; #8 rendered `ToString("O")`, seven digits and `+00:00`), `x-event-type`, `content-type: application/json`, and `traceparent` from the current (consumer) span when one is valid. The original record's own headers are not copied (its `traceparent` would collide with the dead letter's; the trace id is the same).
- A missing `.dlq` topic (auto-creation is off in the test broker and in compose, where `kafka-init` creates the companions, `docker-compose.infra.yml:197`) makes `send_and_wait` fail after the producer's metadata wait: task S4.4 measures what aiokafka 0.14.0 raises and after how long, sets `request_timeout_ms` from the measurement, and the failure is `OR8`'s path (no commit). *S4.4 measured (real `apache/kafka:4.3.1`, auto-creation off, `acks="all"`, idempotent): `aiokafka.errors.UnknownTopicOrPartitionError` after 40.07 s with aiokafka's default `request_timeout_ms` (40 000), 5.02 s with 5 000; the setting is therefore `request_timeout_ms`, set to 10 000.*
- The confinement literal of `tests/architecture/test_kafka_client_confinement.py:37` gains the three publisher modules and the readiness and DLQ-depth clients (§6, §7); an instrument change, so the rule is **re-armed**: an `AIOKafkaProducer` import added under `application/` must still fail it.

### 5.5 Copy parity (`OR2`)

`fact_retry.py` and `dead_letter_publisher.py` form one family: canonical in Orders, copies in the Projector and Notifications, compared after the docstring with a per-service token map and the formatter's reflow, exactly the instrument of `test_outbox_copy_parity.py`. **The publisher is inside the family** — #8's three publishers were outside every parity family, and a corrupted `x-first-failed-at` in one copy left that service green (#8 review round 1, D3/P7). **The population is declared, not discovered**: the literal `{"orders", "projector", "notifications"}` must equal the set of packages `asyncapi.yaml`'s fact `receive` operations name (the mapping `SPEC_CONSUMER_PACKAGE` already in `test_idempotent_consumer_parity.py`), and a copy found in any other service fails. Armed: a one-character change in one copy; a deleted copy; a copy planted in Billing; a fourth consumer declared with no copy (temporary tree).

### 5.6 The saga's first park (`R29` dead-letter clause, `OR3`)

**Migration `0003_saga_commands_dead_letter`** (one revision; R62 owes none, §3.1), additive, nullable:

| Column | Type | Why |
|---|---|---|
| `triggering_event_envelope` | `bytea` | the **received bytes**, stored byte-exact by type: `json` would validate and re-encode text, `jsonb` normalises (CLAUDE.md "payload columns"); #7's MySQL `json` normalised its copy (orchestrator L21) |
| `triggering_event_topic` | `varchar(64)` | the `.dlq` name is `topic + ".dlq"`, never guessed from the event type |
| `dead_lettered_at` | `timestamptz(3)` | the at-most-once marker |
| `trace_parent` | `varchar(55)` | the enqueue-time `traceparent` (`OR10`; gate G3) |
| `first_failed_at` | `timestamptz(3)` | **review round 1, B1:** the instant of the row's first failed attempt, SA-3's `x-first-failed-at`; set once by `COALESCE(first_failed_at, :given)` in `park` and in `reject` (the only two ledger writes that record a failed attempt: `try_claim`, `claim_due` and `mark_sent` record none) |

`models.py`, `test_orders_models_match_migration.py` and `test_orders_migration_lifecycle.py` follow; the column census of `tests/database_parity/test_reliability_table_parity.py` is checked for whether it covers `saga_commands` (task S4.10 reads it).

**Threading the bytes.** `SagaFactsConsumerTask.handle` already holds `message.value` and `message.topic`; the fact commands gain `raw: bytes` beside `topic`, and the enqueue in `application/saga/fact_command_handlers.py` → `infrastructure/saga/command_queue.py` writes `triggering_event_envelope=raw`, `triggering_event_topic=topic`, `trace_parent=current_traceparent()`. `ON CONFLICT DO NOTHING` (orchestrator L10) keeps the first row's envelope on a duplicate enqueue.

**The hook**, in `infrastructure/saga/command_dispatcher.py`'s exhaustion path, after `ledger.park(...)`:

1. **One transaction**: `UPDATE saga_commands SET dead_lettered_at = :now WHERE id = :id AND status = 'parked' AND dead_lettered_at IS NULL RETURNING triggering_event_envelope, triggering_event_topic` — one statement whose returned row is the answer, never select-then-update (#8 L16); if a row came back, load the order with the order-row lock (`FOR UPDATE OF orders`, orchestrator L24), `order.record_saga_failure(command, attempts, last_error, occurred_at, causation_id)` and `save` — the `order.saga_failed.v1` outbox row commits **with** the claim (#8 L17).
2. **After the commit**, if an envelope came back, `dead_letters.publish(...)` with `x-failed-consumer = orders.saga`, `x-attempts` the row's accumulated attempts, `x-error` the last error, `x-first-failed-at` the claim's `first_failed_at` (the instant of the first failed attempt, which the dispatcher reads from its clock inside the first `except` of its in-line loop and hands to `park`), `x-failed-at` the clock's at the claim (the park). *(Round 1, B1: the first design said "both instants the clock's at the claim", copied from #7 `saga-first-park-dead-letter-handler.ts:50` and #8 `SagaFirstParkDeadLetterHandler.cs:113-121`; SA-3 says the two are equal only when one attempt was made, and the row's `x-attempts` is at least the in-line policy's 3.)* A failed publish is logged at ERROR naming the row id; the bytes stay in the row for a manual republish. Gate G4 records this order (#8's) against #7's publish-first.

`Order.record_saga_failure` (domain) raises one `OrderSagaFailed` event and changes **nothing else** (status, lines, totals, `updated_at`); `outbox/payloads.py` gains its `case` (the `assert_never` exhaustiveness makes a missing arm a type error); `FACT_MODELS`, the projector's summary and the saga's `Skip` already carry `order.saga_failed.v1` (`step_table.py:255`, `projection.py:153`), so no "thirteen → fourteen" sweep is owed — task S4.13 proves that absence as a search result.

**Rows that predate the migration.** Rows parked before `0003` have `dead_lettered_at` NULL, no envelope and no `first_failed_at`: their next park appends `order.saga_failed.v1` once and publishes nothing (and its `park` now stores `first_failed_at`). Stated, because the live data has parked rows (§16).

**A row with an envelope and no `first_failed_at` cannot arise (round 1, B1; verified).** The envelope is written only at enqueue by a build that has `0003`; the only statement that makes a row `parked` is `park`, which writes `first_failed_at` in the same statement (`COALESCE`), and the claim requires `status = 'parked'`. A dispatch interrupted before its park persists no attempt (`attempts` and `last_error` are written only by `park` and `reject`), so no earlier failure is lost. The code falls back to the park instant for a `NULL` (`claim.first_failed_at or now`), unreachable by construction and not tested.

**S4b delivery notes (deviations, with reasons).** (1) The hook is `SqlAlchemySagaFirstPark` (`infrastructure/saga/first_park.py`) behind the `SagaFirstPark` port (`application/ports/saga_first_park.py`); the dispatcher calls it after `ledger.park` on EVERY park and catches `Exception` (logged, the park is already durable; the next park tries again), so a failure of the bookkeeping can never change a dispatch outcome. (2) **The order row is locked BEFORE the claim**, not after as the list above reads: every other writer of these two rows (a fact's handler, the operator cancel) locks the order and then touches `saga_commands`; claiming first would hold a `saga_commands` row while waiting for the order and could deadlock with them. The claim is still the one `UPDATE ... RETURNING` statement. (3) The claim is `SagaCommandQueue.claim_first_park(row_id, at=...)`, a method of the transaction-bound queue, so it shares the transaction with the order's `save` (G4's order). (4) The dead-letter publisher is built beside the unit of work and **started whenever the runtime has a Kafka role** (`OUTBOX_RELAY_ENABLED` or `SAGA_CONSUMER_ENABLED`), before any task exists; a runtime with neither (the existing host tests boot against a closed port) logs the ERROR of an unpublished dead letter at its first park. (5) The dead letter's key is the order id (`correlationId`, the original record's key by construction: every fact is keyed by it), its `x-event-type` is parsed from the stored bytes (`unknown` if they do not parse), `x-failed-at` is the claim's instant and, since round 1 (B1), `x-first-failed-at` is the row's stored `first_failed_at`. (6) `Order.record_saga_failure` validates only the instant (`require_utc`); `attempts >= 1` is the payload model's (`OrderSagaFailedPayload.attempts` is `ge=1`), checked when the outbox builds the fact. (7) The `OrderEvent` union has five members; `test_order_events.py`'s census and `test_order_instants.py`'s parameter literal (14) were updated, both forced by the new event.

### 5.7 Item 12 and `OR12` (gate G1)

`orders.cancel`'s compensation enqueue (`application/commands/cancel_order.py`) stores **no** envelope; its first park appends `order.saga_failed.v1` and publishes no dead letter. The operator's note is already stored (`saga_commands.operator_note`, migration `0002`), which is the other purpose the synthetic envelope served in #7 and #8 (#8 id 71 bullet 5). The ported guard is #8's `StockReserved_OperatorCancelCompensationParks_PublishesADlqCopyByteEqualToTheStoredEnvelope` (`tests/Orders.IntegrationTests/OrdersCancelAcceptanceTests.cs:549`), **ported with its claim inverted**: one `order.saga_failed.v1`, zero records on `otc.orders.facts.v1.dlq` for that order (read from the broker by content), armed by storing a synthetic envelope. If G1 is overruled toward parity, tasks S4.15 – S4.16 switch to #7's `buildTriggeringEnvelope` shape (`apps/orders/src/application/cancel-order.handler.ts:237`) and #8's guard verbatim; no other task moves.

### 5.8 The re-run arms (items 8 and 11)

After the wrapper exists, an in-process retry absorbs a single failure, so the SO9 tests as written would either pass for the wrong reason (#8 id 94) or fail with correct code. The redelivery path that still exists — and that `OR8` creates — is **a dead letter that is not durable**. The rewritten cases inject both failures with the existing technique (`failing_once_for` monkeypatches `SagaFactHandler.handle`, `test_saga_consumption.py:29-55`; a sibling patches the dead-letter publisher's `publish` for the test's event id):

| Arm | Test after the rewrite (name is a claim) | The redelivery that turns it red |
|---|---|---|
| 3.9 commit-before-handler; `enable_auto_commit=True` | `test_so9_a_fact_whose_dead_letter_is_not_durable_leaves_the_committed_offset_unchanged_and_a_restarted_consumer_redelivers_it`: the handler fails all N attempts and the publish fails in lifespan 1; the committed offset is read from the broker unchanged (held over the 5 s auto-commit window, as today); lifespan 2 (failure cleared) processes it; committed = offset + 1; handler attempts = N + 1 | lifespan 2's new consumer |
| 3.10 remove the `seek` | `test_so9_a_failed_record_is_never_committed_past_while_its_dead_letter_is_not_durable`: handler and publish fail until a flag; ≥ 3 subscriber-level redeliveries sampled; then both records processed in order | the subscriber's seek-and-redeliver |
| 3.12 `auto_offset_reset="latest"` | unchanged (`test_so1_first_boot…`), re-run | first boot |
| 3.8 validate in presentation | `test_a_well_formed_envelope_with_a_poisoned_payload_is_not_committed_and_is_retried` is **retired by R16** (its claim — "not committed" — is now false by requirement); its arm moves to the Orders R16 case: validating the payload in presentation turns the poison into a log-and-acknowledge and the dead letter never arrives | — |
| Projector `I4-commit-before-handler` on `PR38` | `test_offset_contract.py::test_pr38_…` drives the subscriber with a raising handler, which is exactly what the wrapper raises when the dead letter is not durable; re-run unchanged, **plus** `test_or8_…` through the real projector lifespan (poison + failing publish → offset unchanged → restart → dead-lettered and committed), armed by the same mutation | the restarted consumer |

Each re-run is recorded with its mutation, its verbatim failure and the sentence naming the redelivery that turned it red. An arm that survives means the test does not prove SO9 and is rewritten before anything else proceeds (orchestrator task 3.9's own rule).

---

## 6. Stage S5 — metrics (`R59`, `OR9`; acceptance item 6)

### 6.1 Series names, measured

A throwaway collector built from `infra/otel-collector/` (`docker build -t otc9-measure-collector:probe infra/otel-collector`, the config mounted byte-identical) and a throwaway `prom/prometheus:v3.14.0` with the reused `infra/prometheus/prometheus.yml`, on a private network with the collector aliased `otel-collector`; a Python OTel SDK 1.45.0 client pushed OTLP/HTTP from two `service.name`s (`gateway`, `orders`). Collector `:8889` exposition and Prometheus' stored series:

| Instrument as created | Stored series |
|---|---|
| histogram `otc_request_latency_ms`, no unit, attr `endpoint` | `otc_request_latency_ms_bucket` / `_sum` / `_count` |
| histogram `otc_fact_processing_latency_ms`, no unit | `otc_fact_processing_latency_ms_bucket` … |
| histogram `otc_saga_completion_ms`, no unit, attr `outcome` | `otc_saga_completion_ms_bucket` … |
| gauge `otc_outbox_lag_ms`, no unit | `otc_outbox_lag_ms` |
| observable gauge `otc_dlq_depth`, attr `topic` | `otc_dlq_depth{topic=…}` |
| histogram `otc_probe_with_unit_ms`, `unit="ms"` | `otc_probe_with_unit_ms_milliseconds_bucket` |
| gauge, `unit="1"` | `…_ratio` |
| counter | `…_total` |

Every series carried `exported_job` = the `service.name` (the collector's exporter writes `job=<service.name>`; Prometheus' scrape job is `otel-collector` and, `honor_labels` being false, renames the conflicting label to `exported_job`), plus `otel_scope_name`. The dashboard's `histogram_quantile(0.95, sum(otc_request_latency_ms_bucket) by (le, exported_job, endpoint))` returned both services. Default SDK buckets (0, 5, 10, 25, 50, 75, 100, 250, 500, 750, 1 000, 2 500, 5 000, 7 500, 10 000) are kept: they are milliseconds-shaped. **So: no instrument declares a unit** — #8's shape, which its id 109 accepted after #7's `unit: 'ms'` produced `_milliseconds` names (`../order-to-cash-nestjs/apps/orders/src/infrastructure/observability/metrics.ts:42-62`) and #8's dashboard had to be corrected (`../order-to-cash-dotnet/progress/impl_observability_dashboards.md:68-75`). Containers, network and image removed after the measurement.

### 6.2 Where each series is recorded

| Instrument | Service(s) | Code path | Value |
|---|---|---|---|
| `otc_request_latency_ms` | Gateway | `TelemetryMiddleware`, on response completion, **error path included**; `endpoint = "<METHOD> <route path template>"` read from `scope["route"]` after the inner call (task S5.3 verifies Starlette leaves it in the outer scope), `"unmatched"` otherwise | clock-based ms float |
| `otc_fact_processing_latency_ms` | Orders, Projector, Notifications | `FactRetry.process` entry → exit (§5.3), success and dead-letter paths; `consumer` = the `ConsumerName` token | injected clock |
| `otc_saga_completion_ms` | Orders | after the saga fact command's transaction **commits** and the transition landed on `completed` or `cancelled`, through an application port `SagaMetrics` (application may not import OTel); a deduplicated redelivery returns before it and records nothing; `outcome` attribute, one instrument | `(closing occurred_at − order.order_date)` in ms, both stored instants |
| `otc_outbox_lag_ms` | Orders, Fulfillment, Billing | `outbox/relay.py` (copy family) at the start of each cycle: `SELECT min(occurred_at) FROM outbox WHERE published_at IS NULL`; `0` when none | `(clock.now() − oldest) / timedelta(milliseconds=1)` |
| `otc_dlq_depth` | Orders | a new Orders task `DlqDepthTask`, on the relay's interval: per `.dlq` topic of the three, `Σ(end − beginning)` over its partitions from a dedicated group-less `AIOKafkaConsumer` (`beginning_offsets` / `end_offsets`); a missing topic reports `0` and never raises; one `Gauge.set(value, {"topic": …})` per topic *(S5 deviation: the partitions come from an admin client's `describe_topics`, not from the consumer: a group-less consumer's own metadata knows only topics it was told about, and `AIOKafkaConsumer.topics()` returns a throw-away copy. `describe_topics` answers error code 3 for a missing topic AND for a topic created moments ago, so a missing topic reports 0 until the broker asked knows it.)* | the **broker's** count |

**Per topic** is `R59`'s word ("dead-letter depth per topic"): #7 recorded per topic (`outbox-relay.ts:241-242`); #8 summed the three into one series with no topic (`KafkaDlqDepthGauge.cs:57-66`). #9 follows the requirement.

**Synchronous gauges only.** An observable instrument's callback runs on the `PeriodicExportingMetricReader`'s **thread** at export time; asyncpg and aiokafka objects belong to the loop, so a callback that touched them would cross threads. Every gauge is a synchronous `Gauge.set` from the asyncio task that owns the client; guard: no `create_observable_` call under `services/*/src` (ledger L12). `DlqDepthTask` is owned and awaited by the lifespan and joins readiness (CLAUDE.md "a task that dies takes readiness down").

### 6.3 Guards

Unit cases over `InMemoryMetricReader` with exact values (latency 240.5 from a fake clock; the dead-letter path's exact sum; saga completion from two stored instants; lag from a clock-aged row) — armed by deleting each record call, by `//` instead of `/` (240.5 → 240), by seconds for milliseconds, by transposing `completed`/`cancelled`, and by recording on a non-closing step. Integration: the real relay's lag against a real aged row then `0`; the real DLQ depth against counts the test reads from the broker, a missing topic → `0`. And the **name guard that #8 lacked** (its id 109: "no compile-time or test-time guard tying an instrument's name to a dashboard query"): `tests/observability/test_prometheus_series_names.py` builds the collector image from `infra/otel-collector/` with testcontainers, runs it and a Prometheus on a private network, exports from the **real** `telemetry.py` of each recording service, and asserts the five series the dashboard JSON queries (parsed from the file, not retyped) exist in Prometheus with their attribute keys. Armed by adding `unit="ms"` to one instrument.

---

## 7. Stage S6 — readiness (`R60`, `OR6`; acceptance item 4)

### 7.1 Checks per service (`openapi.yaml` `HealthResponse.checks` keys)

| Service | `writeModel` | `factStream` | `rpcTransport` | `readModel` |
|---|---|---|---|---|
| Gateway | — | — | NATS (exists) | MongoDB (exists) |
| Orders | PostgreSQL | Kafka | NATS | — |
| Fulfillment | PostgreSQL | — | NATS | — |
| Billing | PostgreSQL | — | NATS | — |
| Notifications | PostgreSQL | Kafka | — | — |
| Projector | — | Kafka | NATS (it publishes update signals) | MongoDB |

#7 and #8 agree on this table except the Projector's NATS, which #8 added and #9 already treats as a readiness reason (`PR45`). Fulfillment and Billing publish to Kafka only through their outbox: with Kafka down they can still accept commands and commit facts durably, so withdrawing them would stop the saga for nothing; outbox lag is the signal (`R59`).

### 7.2 Probes — each a real call, each bounded

The Gateway's shape is the canonical (`services/gateway/src/otc_gateway/infrastructure/health_checks.py`: `HealthCheck(name, probe, timeout_seconds=2.0)` run under `asyncio.timeout`, all checks gathered so a hung one costs one bound). New probes, in a `infrastructure/health/` copy family per kind:

- **PostgreSQL**: `SELECT 1` on a dedicated **`NullPool`** engine owned by the lifespan, `connect_args={"timeout": 2}`. A cancelled probe then never returns a half-used connection to the service's pool — #8 found exactly that defect in its pooled probe (`tests/Fulfillment.IntegrationTests/MsSqlHealthCheckPoolingTests.cs`) and fixed it with `Pooling = false` (`src/Orders/Infrastructure/Health/MsSqlHealthCheck.cs:21-33`).
- **Kafka**: a dedicated long-lived `AIOKafkaAdminClient` (never the relay producer or the consumer; #7 `kafka-health-check.ts:22` `retries: 0`, #8 L27) calling `describe_cluster()`; task S6.3 measures recovery after a pause longer than the bound and, if the client does not recover within two probe calls, switches to a client per call and records why.
- **NATS**: the existing closed/reconnecting reasons, then `await connection.flush(timeout=2)` (a PING that waits for a PONG), inside `asyncio.timeout`. `nats.errors.TimeoutError` subclasses the builtin `TimeoutError` (orchestrator L16): the check names the nats classes and lets the outer bound's `TimeoutError` be the timeout.
- **MongoDB** (Projector): `admin.command("ping")`, the Gateway's existing shape.

**Task liveness stays.** Today's `unready_reasons()` (dead transport task, closed NATS, shutting down) is kept and attributed to the check of the dependency the task serves (responder and saga tasks → `rpcTransport`; consumer, relay and `DlqDepthTask` → `factStream`; shutting down → every check `down`, detail `shutting down`). `/health/live` answers `200 {"status":"up"}` and consults nothing. The response is `HealthResponse` through the service's wire serializer; the existing `test_<svc>_health.py` assertions of the old `{"status":"ready"}` shape change with it.

### 7.3 Guards

- Unit, per service: liveness consults nothing; ready `200` when all up; `503` naming only the failing check, **driven once per check position**; task-death attribution.
- `tests/architecture/test_health_probe_bounds.py`: every probe under `services/*/src` (found by AST, expected set a literal, the rest by subtraction) runs under a bound; armed by removing one bound and by adding an unbounded probe on a temporary tree.
- Integration, per service — `test_r60_readiness_reports_the_paused_dependency_down_within_its_bound_while_liveness_answers_throughout_and_recovers`: the dependency is a **private** container started by the test module (never the session-wide one: a failed test that leaves a shared container paused would stall every later test), paused with `container.get_wrapped_container().pause()` and unpaused in a `finally`; polls paced at 250 ms; readiness reports **that check only** `down` within bound + one poll interval; liveness `200` on every poll; readiness `up` again after unpause; and for PostgreSQL a write succeeds afterwards (no poisoned pooled connection). The Gateway gains the paused NATS case (its leg was proven with **stopped** containers, `test-matrix.md` R60 row). Armed per service by hard-coding the paused check to `up`, and once by removing the bound (the case then times out naming the claim).

---

## 8. Stage S7 — items 7, 9, 13

### 8.1 Item 7 — no fixture runs a server with reload

Population (AST, not grep): every call in `services/*/tests/**`, `tests/**`, `packages/*/tests/**` and the root `conftest.py` to `uvicorn.run`, `uvicorn.Config`, `uvicorn.Server`, and every `subprocess.Popen`/`run`/`asyncio.create_subprocess_exec` whose argument list contains `"uvicorn"` or a `"-m", "otc_…"` pair; plus `apps/web/playwright.config.*` and `apps/web/vite*.config.*` `webServer` commands (text). Guard `tests/architecture/test_no_reload_servers.py`: none passes `reload=True`, `reload_dirs`, `--reload`, `--watch`; no module under any test tree imports `watchfiles`; the population count is recorded and compared with a literal, so a new server-starting helper is a deliberate edit. Sentinels on a temporary tree: a reload in a comment is not counted, a reload hidden under `if TYPE_CHECKING:` is, an aliased `from uvicorn import run as serve` is. #8's analogue was a host-builder `reloadOnChange` (id 77, `HostInotifyReloadGuardTests`); uvicorn has no file watcher unless asked, so the guard is about what tests ask for.

### 8.2 Item 9 — a terminal `rejected` command (`OR11`; gate G2)

What #7 and #8 finally shipped: the row resolves to `rejected`, one ERROR line, nothing else — #7 `apps/orders/src/infrastructure/saga/saga-command-dispatcher.ts:180-193` (`markRejected`, `logger.error`, `return 'rejected'`), #8 `src/Orders/Infrastructure/Saga/SagaCommandDispatcher.cs:109-130` (`RejectAsync`, `LogError`, `return`). What `specs/shared/` prescribes: `R29` triggers on "times out or returns a transport error"; `domain-model.md:475` defines `order.saga_failed.v1` as a command that "exhausted its in-line retries and parked"; `saga.md:237-240` names a terminal refusal (`PRECONDITION_FAILED` on `despatch.create` after a lost race) "the expected end of a lost race, not a saga failure: no retry, no dead-letter, no `order.saga_failed.v1`". **The shared spec decides it; no `SA-10`.** What this feature builds: the ERROR line gains the log contract's fields (`correlationId`, `traceId`) and keeps `command` and `code`; and the **absence** is guarded — `test_or11_…` drives a terminal `RpcError` through the real dispatcher and asserts no `order.saga_failed.v1` outbox row, no record on the private `.dlq` topic (read by content), `dead_lettered_at` NULL, and exactly one ERROR record with those fields. Armed by routing `reject` through the first-park hook.

### 8.3 Item 13 — open streams at Gateway shutdown (`OR13`)

**Evidence.** Today, after SIGTERM uvicorn waits `timeout_graceful_shutdown` (5 s, `services/gateway/src/otc_gateway/__main__.py:19, 28`) for open responses, then logs `Cancel N running task(s), timeout graceful shutdown exceeded` at ERROR (`uvicorn/server.py:299-307`) and one `Exception in ASGI application … CancelledError` per stream (`progress/review_gateway_sse_push.md:66`). #8 ends a stream at host shutdown through the framework: Kestrel aborts in-flight requests, the request's `CancellationToken` fires and the endpoint catches it as a normal end — `catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)` with the comment *"The client disconnected (or the app is shutting down)"* (`src/Gateway/Presentation/Endpoints/StreamEndpoints.cs:144-150`). #7's stream ends when its response closes (`apps/gateway/src/presentation/stream.controller.ts:80-83`); its shutdown path with an open stream was not measured in #7's records (searched: `grep -n -i shutdown progress/impl_gateway_sse_push.md progress/review_gateway_sse_push.md` → one unrelated hit). Neither treats an open stream at shutdown as an error.

**Decision: the Gateway ends its streams on the exit signal.** Classifying uvicorn's ERROR line instead would match on uvicorn's message text (defeat row 11: an instrument that a wording change silently defeats), keep the 5 s stop, and keep a traceback per stream. Mechanism: `otc_gateway/__main__.py` builds `uvicorn.Server(uvicorn.Config(app, …))` with a `GatewayServer` subclass whose `handle_exit` calls `super().handle_exit(...)` and then `loop.call_soon_threadsafe(stream_hub.end_all)` on the runtime the app object holds (the app object is passed to `Config`, not an import string, so the subclass can reach it). `end_all` ends every open subscription; each `EventStreamResponse` sees its subscription ended, finishes its body and returns normally; uvicorn's `_wait_tasks_to_complete` then finds no task and the lifespan shutdown proceeds. The `uvicorn otc_gateway.main:app` by-hand path keeps the bounded graceful window (documented in `__main__.py`).

**Guard.** `test_or13_…` starts the real `python -m otc_gateway` (the `test_gateway_listens_on_gateway_port.py` pattern) with its NATS and MongoDB, opens two `GET /orders/stream` responses over raw sockets and reads `stream.ready`, sends SIGTERM, and asserts: both streams end (EOF) before 2 s, the process exits 0 before `GRACEFUL_SHUTDOWN_SECONDS`, and no stderr line has `level` ERROR or contains `Exception in ASGI application` (every line JSON, S1). Armed by removing the `end_all` call (exit takes ≥ 5 s and the ERROR lines return).

---

## 9. Packages, settings, files

### 9.1 Packages (each in the phase's commit message, `Packages installed:`)

| Package | Services | Version |
|---|---|---|
| `structlog` | all six | 26.1.0 (resolved this session) |
| `opentelemetry-sdk` | all six | 1.45.0 (= the locked API) |
| `opentelemetry-exporter-otlp-proto-http` | all six | 1.45.0 (its `opentelemetry-exporter-http-transport 0.66b0` and `urllib3` come with it; recorded) |

Added by the implementer with `uv add --package otc-<svc> …` (a workspace member's dependencies are not the leader's). `test_dependency_freedom.py` and the Projector's `test_projector_dependencies.py` literal (`"uvicorn"` …) are read and updated where they enumerate dependencies.

### 9.2 Settings (each a `BaseSettings` with `validation_alias`; each joins `EXPECTED_SETTINGS` and the service's `test_<svc>_settings_env.py`)

| Class | Variables | Default | Services |
|---|---|---|---|
| `TelemetrySettings` | `OTEL_EXPORTER_OTLP_ENDPOINT` (base URL) | `""` = no export | six |
| `FactRetrySettings` | `FACT_RETRY_MAX_ATTEMPTS`, `FACT_RETRY_BACKOFF_MS` | 3, 500 | Orders, Projector, Notifications |

The variable name is #8's and the OTel standard one; FastAPI's auto-configuration would read it too, which §4.6's explicit `auto_configure: False` and its guard close. **Empty by default** so nothing exports to whatever listens on `localhost` (#8 id 104's shape). Every settings class reads `.env` (`env_file=".env"`), so the developer's `.env` would leak into test runtimes: the test session sets `OTEL_EXPORTER_OTLP_ENDPOINT=""` (root `conftest.py`, autouse, session) and a guard asserts no runtime built during the suite holds an OTLP exporter. **Leader-routed:** `.env.example` gains `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`, `FACT_RETRY_MAX_ATTEMPTS=3`, `FACT_RETRY_BACKOFF_MS=500` in the existing comment style, and the developer `.env` the same three (task S8.4). No `infra/` or compose change.

### 9.3 Per-service composition and lifespan changes

| Service | `main.py` | `composition.py` (`start_runtime`) | New / changed modules |
|---|---|---|---|
| Gateway | `install_json_logging("gateway")` | telemetry providers; `TelemetryMiddleware`; tracer into `nats_rpc_client`; Mongo/NATS checks unchanged | `__main__.py` (`GatewayServer`); `application/stream/hub.py` `end_all`; `presentation/asgi.py` (middleware, binding); `infrastructure/observability/*` |
| Orders | same | telemetry; `FactRetry` + dead-letter producer (started after the engine, stopped before it); NullPool probe engine; Kafka admin probe; `DlqDepthTask`; `SagaMetrics` | `fact_retry.py`, `dead_letter_publisher.py`, `dlq_depth.py`, `observability/*`, `health/*`, `unit_of_work.py`, `outbox/{writer,wire,relay}.py`, `saga/{command_dispatcher,command_queue,command_ledger}.py`, `messaging/{kafka_fact_subscriber,nats_saga_commands,nats_stock_availability}.py`, `presentation/{saga_facts_consumer,orders_create_responder,app}.py`, `application/commands/{place_order,cancel_order}.py`, `application/saga/fact_command_handlers.py`, `domain/{order,events}.py`, `persistence/{models,order_mapper,order_repository}.py`, `alembic/versions/0003_…` |
| Fulfillment | same | telemetry; NullPool probe; NATS probe | `stock_responder.py`, `stock_transactions.py`, `outbox/*` (copy), `observability/*`, `health/*`, `presentation/app.py` |
| Billing | same | same | `credit_responder.py`, `credit_transactions.py`, `outbox/*` (copy), `observability/*`, `health/*`, `presentation/app.py` |
| Notifications | same | telemetry; `FactRetry` + producer; NullPool probe; Kafka admin probe | `notification_facts_consumer.py`, `kafka_fact_subscriber.py`, `delivery_ledger.py`, `fact_retry.py`, `dead_letter_publisher.py`, `observability/*`, `health/*`, `presentation/app.py` |
| Projector | same | telemetry; `FactRetry` + producer; Kafka admin probe; NATS probe | `projector_facts_consumer.py`, `kafka_fact_subscriber.py`, `fact_retry.py`, `dead_letter_publisher.py`, `observability/*`, `health/*`, `presentation/app.py` |

Start order adds: providers first (so boot spans and lines have them), then today's stages; the dead-letter producer before the consumer task (a consumer that cannot dead-letter must not start); stop order is the reverse, providers flushed last. Every new task is created, owned and awaited by the lifespan, and joins readiness.

---

## 10. Copy families this feature adds (the parity instrument extended, its premises re-armed)

| Family | Canonical | Copies | Guard |
|---|---|---|---|
| `observability/{logging,trace_context,telemetry,metrics}.py` | Orders | Gateway, Fulfillment, Billing, Notifications, Projector | `tests/architecture/test_observability_copy_parity.py` (new) |
| `messaging/{fact_retry,dead_letter_publisher}.py` | Orders | Projector, Notifications | same module (`OR2`) |
| `health/{checks,postgres_probe,kafka_probe,nats_probe,mongo_probe}.py` | Orders (Mongo: Projector) | per the table of §7.1; the Gateway's `infrastructure/health_checks.py` becomes a copy of `checks.py` | same module |
| `outbox/{writer,wire,relay}.py` (existing) | Orders | Fulfillment, Billing | `test_outbox_copy_parity.py` (unchanged instrument; its premises still hold) |

The new test reuses `test_outbox_copy_parity.py`'s instrument (docstring-normalised, token map, `ruff format` reflow, preamble allow-list, tail check) and its premises P1 – P4; changing the instrument's population swaps its premises (CLAUDE.md), so its sentinels are re-run for the new families, not inherited.

---

## 11. The ported-idiom ledger

> **How the rows were produced.** One row per boundary where #7's engine, language or library supplied a property this design must obtain from somewhere, enumerated from the checkouts and from the Python questions CLAUDE.md lists (integer division, JSON serialisation, event-loop affinity, cancellation, typing). The "#7" and "#8" halves are cited from the checkouts with file and line (or from #8's own ledger where it cited #7, re-opened where marked). The **Guard** half names a `tasks.md` task carrying `[ARM]`; naming it creates the obligation, it does not discharge it. Before ticking a row the walker answers: **does this guard execute the code the row is about?**

| # | Boundary | #7 relied on | #8 supplied it with | #9 supplies it with | Guard (task) |
|---|---|---|---|---|---|
| L1 | Structured lines everywhere | per-call-site `...(traceId ? { traceId } : {})` in JSON log calls, 8 sites at `95e883a` (#8 ledger L25, e.g. `apps/orders/src/infrastructure/messaging/fact-retry-dispatcher.ts:167`) | host settings: `AddJsonConsole` + `IncludeScopes` + activity tracking (`src/Orders/OrdersHost.cs:49-59`) | one `ProcessorFormatter` handler on the root logger, installed in `main.py` (§2.1 – 2.2) | S1.6 (×6, real process) |
| L2 | Library lines in the same format | Nest's logger | the .NET logging pipeline owns every `ILogger` | uvicorn installs its own handlers with `propagate=False` before the app is imported (`uvicorn/config.py:303`): removed and re-propagated in `install_json_logging`. *S8a: since S7 the Gateway started by `python -m otc_gateway` passes `log_config=None`, so uvicorn installs no handler there and this step is not exercised (an arm of it survives); it is still needed, and guarded, for the five services started with `python -m uvicorn`; the Gateway's by-hand `uvicorn otc_gateway.main:app` path has no guard.* | S1.6 (`Started server process` line JSON) |
| L3 | Trace id on a line | explicit read per site | activity tracking, on by default (#8 L25, corrected in its round 2) | `add_trace_context` reads `get_current_span()` at format time; omits both keys when invalid | S1.3, S1.6 |
| L4 | `correlationId` on a line | explicit field per site | `BeginScope` at five sites — two with the wrong key (`SagaCommandDispatcher.cs:84` `order_id`, `OutboxRelay.cs:151` `correlation_id`) | `bound_contextvars(correlationId=…)` at the literal site list of §2.4; key a literal. *S8a: a rendered-line guard exists for the Gateway, the three responders, the Projector, Notifications and (added in S8a) the Orders consumer (`test_saga_malformed_envelope_log.py`, the retry wrapper's lines name no correlation id of their own). The relay (x3 copies), the command dispatcher and the fast path bind AND pass `extra={"correlationId": ...}` on every line they write, so a deleted binding changes no rendered line: the census alone guards them.* | S1.4 (census), S1.6, S8a |
| L5 | JSON shape of a line | `JSON.stringify` (compact, raw non-ASCII) | `System.Text.Json` console formatter | `JSONRenderer` with a compact, `ensure_ascii=False` serializer; timestamp through `format_instant` | S1.3 |
| L6 | Context reaches spawned work | `otelContext.with(...)` around the handler (`apps/orders/src/presentation/saga-facts.controller.ts:155`); Node's async context follows the promise chain | captured `Activity.Current?.Id` on the channel item (`src/Orders/Application/Ports/ISagaCommandSignal.cs:30`) | `asyncio.Task` copies `contextvars` at creation; the fast-path task is created inside the fact's handling (orchestrator L7). Responder request tasks are created from `run`'s context (`orders_create_responder.py:159`), so each `_serve` extracts and binds its own. *S8a: since S4.21 `dispatch_claimed` restores `saga_commands.trace_parent` when the context is empty, so S3.10 passes with `context=contextvars.Context()` on the fast-path task (re-armed: it survives). S3.10 guards the observable property (trace continuity); the mechanism is guarded by `test_so14_the_dispatch_runs_in_the_context_of_the_fact_handling_that_owed_it` (feature 16), armed in S8a with the same mutation.* | S3.10 (property), `test_so14` (mechanism), S3.6 (responders) |
| L7 | Trace read in the emitting context | n/a (one thread) | n/a (`Activity.Current` is async-local) | a synchronous `StreamHandler`; a `QueueHandler` would format on another thread with no span. Probed both ways in S1.3: the sync handler carries the id; a `QueueHandler` variant loses it | S1.3 |
| L8 | A binding ends with its unit | per-call fields cannot leak | `using` scope disposal | `bound_contextvars` context manager; bare `bind_contextvars` forbidden in `services/*/src` | S1.3, S1.4 |
| L9 | Provider lifetime | `@opentelemetry/sdk-node` started once per process in `tracing.ts` (#7 `metrics.ts:1-17` comment) | DI-registered providers per host (`src/Orders/Infrastructure/Observability/Telemetry.cs:69-75`) | per-runtime providers, never global; set-once globals measured (`trace/__init__.py:552`). *S8a: the assertion is on the TYPE of the process-global tracer and meter providers (not an SDK provider); the first form (`is not` against this test's own providers) passed whenever an earlier runtime in the same pytest process had set the global, and the meter half had no arm. Both halves armed.* | S3.2 |
| L10 | Cancellation is not a poison message | a closed consumer, no exception through the handler (#8 L13) | `OperationCanceledException` rethrown (`src/Orders/Infrastructure/Messaging/FactRetryDispatcher.cs:87`) | `CancelledError` is a `BaseException`; only `except Exception` in `fact_retry.py`, never `BaseException` *S4a delivery: the work-side half is armed by `except BaseException` (the cancel case then fails); the back-off half cannot fail that mutation because the `sleep` call is outside the `try` (a `CancelledError` raised there propagates whatever the `except` says), so it is armed by wrapping the back-off in `contextlib.suppress(BaseException)` instead.* | S4.3 |
| L11 | A deliberate ignore is not dead-lettered | `UnknownFactTypeError` caught inside the delegate (#8 L11) | same | same, in the Projector's wrapped callable | S4.8 |
| L12 | Gauges and threads | one Node thread | `Gauge.Record` from the relay cycle | observable callbacks run on the reader's thread; synchronous `Gauge.set` from the owning task; no `create_observable_` in `src` | S5.6 |
| L13 | Event-loop affinity of the new clients | n/a | n/a (thread pool) | the dead-letter producer, the Kafka admin probe and the DLQ-depth consumer are built and started inside the lifespan's loop, never in `__init__` (orchestrator L28) *S4a delivery: the dead-letter producer's two-successive-loops cases are `test_saga_dead_letter_composition.py` (Orders), `test_notifications_dead_letter_composition.py` (Notifications) and `test_projector_lifespan.py` (Projector, the existing case now crossing the producer). S8a: the dead-letter producer's two-loop case armed with a module-level cache of the started producer (`Please create objects with the same loop as running with`).* | S4.5, S6.3 (each runtime started and stopped in two successive event loops) |
| L14 | Offset commits after the dead letter is durable | `@nestjs/microservices` committed when the handler returned (#8 L12) | `StoreOffset` only after the handler returns, `EnableAutoOffsetStore=false` (`KafkaFactStreamSubscriber.cs:96, 133-134`); producer `Acks.All` | explicit `commit` after the handler returns (`kafka_fact_subscriber.py` `_consume`); `send_and_wait` with `acks="all"` inside the handler; a publish failure raises through it | S4.6 (OR8), S4.17 – S4.19 |
| L15 | Dead letter byte-for-byte | kafkajs handed the raw `Buffer` (#8 L15) | raw `Value` bytes | `message.value` bytes; never `to_wire_json(envelope)` | S4.6 |
| L16 | Dead-letter key | `envelope.correlationId` (`kafka-dlq-publisher.ts:65`) | `publication.EventType` (`KafkaDeadLetterPublisher.cs:72`) | the original record key (`asyncapi.yaml` `DeadLetterRecord` key is `UniqueId`) | S4.6 |
| L17 | Header instants | `toISOString()` (`kafka-dlq-publisher.ts:49-50`), entry instant as first failure (#8 id 75) | `ToString("O")` (`KafkaDeadLetterPublisher.cs:56-57`); first failure `firstFailedAt ??= clock.UtcNow` (`FactRetryDispatcher.cs:97`) | `format_instant` (`otc_contracts/wire.py:47`); first failure read in the first `except` | S4.3 (distinct instants), S4.6. *Round 1 (B1): the SAME class on the first-park path; there the first failure is stored in `saga_commands.first_failed_at` (§5.6) and read back by the claim.* |
| L18 | `x-attempts` from the loop | one loop, one counter | the loop's own `attempt - 1` (`FactRetryDispatcher.cs:117-121`) | the loop's own counter | S4.3 |
| L19 | Latency arithmetic | `clock.now() - enteredAt` in JS numbers (`fact-retry-dispatcher.ts:135-142`) | `TotalMilliseconds` `double`, after a `Stopwatch` regression (#8 D8) | `timedelta / timedelta(milliseconds=1)` (float, exact to the µs); never `//`, never `total_seconds() * 1000`. *S8a: the composition-root binding (`latency=FactLatencyHistogram(...)`, default no-op) is guarded by `test_saga_metrics_wiring.py`, `test_projector_metrics_wiring.py`, `test_notifications_metrics_wiring.py` (real Kafka fact, the runtime's own meter; armed by `latency=NoFactLatency()`), and the saga completion binding by the Orders case.* | S5.2, S8a |
| L20 | Dead-letter bootstrap | one Kafka config | a separate default `localhost:9092` until id 104 (`e58ea63`) | no second setting: the producer reads `KafkaSettings.brokers` *S4a delivery: the producer's `bootstrap_servers` is asserted by a recording `AIOKafkaProducer` subclass that fails in its constructor, per service (Orders, Projector, Notifications), each armed with a `localhost:9092` default.* | S4.5 |
| L21 | Server span exists because the app registers it | `HttpInstrumentation` in `tracing.ts`; its spec built its own provider (#8 D10, `http-instrumentation.spec.ts:30-38`) | `AddAspNetCoreInstrumentation()` | hand-built `TelemetryMiddleware`; FastAPI's native telemetry off (§4.6) | S3.9 (exported by the runtime's own provider), S3.3 |
| L22 | No double export / no hidden env reads | n/a | n/a | `auto_configure: False` in six apps (inline `telemetry={...}` in each `FastAPI(...)` call); explicit propagator, resource and sampler (§4.2). *S3 delivery notes:* the environment probe runs in a fresh interpreter with `OTEL_PROPAGATORS=baggage` (the task text said `b3`, which is not installed: the import itself raises, a failure for the wrong reason), and asserts the resource attributes equal exactly `{"service.name": "orders"}` (a first form that asserted only `service.name` let the `Resource.create` arm survive, because explicit attributes outrank the detectors) | S3.3, S3.2 |
| L23 | Fresh NATS headers per call | `natsHeaders()` per call (orchestrator L19) | new `NatsHeaders` per call; integration guards hollow until #8 D9 | a `dict` literal per call at the three outbound sites; the test **creates the overlap**: a connection wrapper holds call A inside `request` until call B has built its headers | S3.7 (×3 sites) |
| L24 | Continued, not merely present | case titles "not merely a header is present" | extract-and-compare (#8 L24, responders fixed in its round 1) | extract-and-compare through the production classes over real transports | S3.5 – S3.8 |
| L25 | Write-database hop | none (#8 L23) | `writemodel.transaction` activity (`EfCoreUnitOfWork.cs:46`) | `writemodel.transaction` span in each transaction factory. *S3 population, by search (`begin(` over `services/*/src`):* Orders `SqlAlchemyUnitOfWork.begin`, Fulfillment `SqlAlchemyStockTransactions.run` (one span per attempt), Billing `SqlAlchemyCreditTransactions.run`, Notifications `SqlAlchemyDeliveryLedger._begin` and `.forget`; not spanned on purpose: the outbox relay's claim transaction (a `PRODUCER` span per row instead), Orders' `SqlAlchemySagaCommandLedger` (saga bookkeeping, not an order write; its dispatch span is `OR10`), the read-side sessions (no transaction) | S3.8 (ordering by parent id) |
| L26 | Outbox carries the context | `outbox-recorder.ts:38` `activeTraceParent()` | `OutboxWriter.cs:70` `Activity.Current?.Id` | `writer.py` `current_traceparent()`; NULL with no span; relay restores and starts a `PRODUCER` child | S3.5 |
| L27 | Unique index admits many NULLs | MySQL `UNIQUE` (`orders.schema.ts:34-37`) | a filtered index (#8 L1) | PostgreSQL's default `NULLS DISTINCT` on the `0001` index | S2.1 (two NULL orders; armed `NULLS NOT DISTINCT`) |
| L28 | Collision caught where the transaction is usable | caught inside, committed (`place-order.handler.ts:159-163`) | caught outside `ExecuteAsync` by choice (#8 L2) | caught outside **by necessity**: PostgreSQL aborts the transaction on any error | S2.4 (one outbox row) |
| L29 | Which unique key collided | `ER_DUP_ENTRY` + `sqlMessage` substring (`place-order-request-id.ts:14-40`) | error 2601/2627 + message substring | asyncpg `UniqueViolationError.constraint_name`, the chain captured from a real container first | S2.3, S2.5 |
| L30 | `requestId` → `causationId` | `UniqueId.from(requestId)` (`place-order.handler.ts:205-211`) | `RI5` | `UniqueId(request_id)`; both directions asserted | S2.6 |
| L31 | Readiness probe cannot hang | one probe unbounded, disclosed by #7's implementer (#8 L26) | `CancelAfter` everywhere + an enumeration (`HealthProbeTimeoutTests`) | `asyncio.timeout` per check AND per probe + `flush(timeout=)` / `connect_args`; AST enumeration (`test_health_probe_bounds.py`), armed | S6.2, S6.6 (delivered S6) |
| L32 | A cancelled probe does not poison a pool | mysql2 destroys the connection on timeout (`mysql-health-check.ts:3, 20`) | `Pooling = false` after a found defect (`MsSqlHealthCheck.cs:21-33`) | `NullPool` probe engine (`postgres_probe.py`) | S6.7 (a write through the service's own pool succeeds after the unpause; delivered S6). **Armed in S7.7**: with `poolclass=NullPool` removed from Fulfillment's `postgres_probe.py` the `[writeModel]` case of `test_fulfillment_health_probes.py` fails (`not within 7.5 s: readiness never reported writeModel down while its container was paused (after 0 reads, last [])`): a pooled probe's cancellation does not return, it blocks on the paused connection. S6's "cannot be armed" was wrong: the mutation target is the claim that the probe engine is unpooled |
| L33 | Streams end at shutdown | the response's `close` event (`stream.controller.ts:80-83`); shutdown with an open stream not measured | request abort → `OperationCanceledException` caught as a normal end (`StreamEndpoints.cs:144-150`) | `GatewayServer.handle_exit` → `hub.end_all` | S7.5 |
| L34 | uvicorn shutdown lines | n/a | n/a | uvicorn logs ERROR on graceful-timeout cancellation (`uvicorn/server.py:299-307`); removed at the source by L33, not filtered | S7.5 |
| L35 | Envelope bytes stored exactly | MySQL `json` normalised (orchestrator L21) | `nvarchar(max)` | `bytea` | S4.11 (byte-equal round trip; armed by storing `to_wire_json(envelope)`) |
| L36 | First park at most once | guarded `UPDATE` | one `ExecuteUpdateAsync`, affected-row count (#8 L16) | one `UPDATE … RETURNING` | S4.12 (16 concurrent claims, one winner). *Round 1 (N3): the `status = 'parked'` predicate has its own case, `test_or3_claim_first_park_answers_none_and_leaves_the_marker_null_for_a_row_that_is_not_parked` (a `rejected` and a `sent` row), armed by removing the predicate.* |
| L37 | Typing gaps | TypeScript types | C# types | SDK and structlog `py.typed`; `ReadableSpan.context` measured `Any`, read through one typed test helper; no new `[[tool.mypy.overrides]]` | S0.3 (`mypy --strict` with the packages) |
| L38 | Unit suffixes on series names | `unit: 'ms'` → `_milliseconds` (`metrics.ts:42-62`) | no unit (#8 id 109) | no unit; measured (§6.1) and guarded end to end | S5.8 |
| L39 | A swept command's trace | none: each claimed row is dispatched with no restored context (`apps/orders/src/infrastructure/saga/saga-command-sweeper.service.ts:93-101`) | none: `SagaCommandSweeper.cs` and `SagaCommandSweeperBackgroundService.cs` contain no `Activity`/`Trace` reference (`grep -n 'Activity\|Trace'` → 0); only the fast-path worker restores a captured parent (`SagaCommandDispatchWorker.cs:65-79, 114-116`) | `saga_commands.trace_parent` restored as parent (`OR10`, gate G3) | S4.21 |
| L40 | DeprecationWarnings are errors | n/a | n/a | each new package imported under `-W error` in the probe venv: clean; the suite's filter is unchanged. *S8a: executable guard `tests/architecture/test_telemetry_wiring.py::test_l40_the_telemetry_packages_import_without_a_deprecation_warning` (+ its sentinel, armed by dropping the `-W` flag).* | S0.3, S8a |
| L41 | A shutdown does not wait out a retry back-off | an uninterruptible `setTimeout` (`apps/notifications/src/infrastructure/messaging/fact-retry-dispatcher.ts:55`, used at `:140`); a shutdown waited for it | the stop token on the delay (`src/Orders/Infrastructure/Messaging/FactRetryDispatcher.cs:112`, `DelayAsync(..., cancellationToken)`), the cancellation rethrown unconditionally (`:87-92`, #8 ledger L13) | hand-built: `stop_aware_sleep(stop)` (`asyncio.timeout(seconds)` around `stop.wait()`) raises `FactRetryStopped` when the stop signal ends the wait, which `FactRetry.process` does not catch (the back-off sits in the `except Exception` handler) and each subscriber names (`except FactRetryStopped` before `except Exception`: INFO line, no commit, no seek, no failure count); a `CancelledError` is not converted. *Verified 2026-10-12 by reading the three lines of each checkout.* | S4.24 (unit; and per consumer a real-lifespan test: a stop during a 30 s back-off returns in under 10 s, the committed offset read from the broker is unchanged, no record on the `.dlq`, and the restarted consumer dead-letters it once) |
| L42 | A blank dotenv credential is "unset" | `isConfigured` trims and treats blank as unset (`../order-to-cash-nestjs/apps/notifications/src/infrastructure/notification/smtp.config.ts:42-48`, used at 54-55); `replace_me` deliberately not ported (not a #9 value) | a transport that never authenticates (`../order-to-cash-dotnet/src/Notifications/Infrastructure/Notification/MailKitSmtpTransport.cs:9-12`, the class header: "deliberately never calls `AuthenticateAsync`") | `SmtpSettings._a_blank_credential_is_unset`, a `field_validator("user", "password", mode="before")` mapping a blank (whitespace-only) string to `None` at the settings boundary, so the pair rule and the sender agree (`services/notifications/src/otc_notifications/infrastructure/settings.py`); the defect (feature 23's, found live in S8b F8) was blank `SMTP_USER=` / `SMTP_PASSWORD=` read as `''`, which `smtp_sender.py` handed to aiosmtplib, which attempted AUTH | S8c: `test_a_blank_or_whitespace_smtp_credential_is_none_and_a_real_pair_is_kept` (unit) and `test_blank_smtp_credentials_deliver_one_message_to_a_real_mailpit` (real Mailpit, real aiosmtplib). Armed in S8c (validator retargeted to a nonexistent field: `SMTPException: The SMTP AUTH extension is not supported by this server`; `AssertionError: ''`) and again in review round 1 (`not value.strip()` to `not value`: `'   '` kept) |

**Where to spend review time.** L4 (a wrong key is invisible to every test that does not read real lines), L14 (an in-process retry makes the old SO9 assertions pass for the wrong reason, #8 id 94), L23 (a hoisted header dict passes any test that does not create the overlap itself, #8 D9), and L21 (a span that exists because the test made it, #8 D10).

---

## 12. Ported guards — #8's tests for these mechanisms, by content

**Population (a search result).** Every test method attributed `[Fact]`/`[Theory]` added by #8's feature-27 commit and by the four follow-up commits that changed these mechanisms:

```
cd ../order-to-cash-dotnet
for c in d8d71c7 e58ea63 6c35084 55b21f7 ad00f79; do git show $c -- 'tests/*.cs'; done | python3 -c '<the [Fact]/[Theory] → public method extractor used in this spec pass>'
```

`d8d71c7` → **198 cases in 73 files**; `e58ea63` → 3; `6c35084` → 2; `55b21f7` → 1; `ad00f79` → 19 (9 of them the Kafka group-teardown guard). **223 cases.** The classification below is by **case group** where every case in the group asserts the same claim (the count is the unit); task S8.2 expanded it (delivered 2026-10-13) to one line per case in `progress/impl_observability_reliability.md` section S8a with the delivered #9 test name (the count reconciles as 219 cases ADDED by the five commits plus 4 existing cases they MODIFIED = 223), and a group whose cases turn out to assert different claims is split there, never folded.

| #8 cases (count) | Claim | Classification for #9 |
|---|---|---|
| `FactRetryDispatcherTests` (8 + 1 from `55b21f7`) | max-attempts/backoff/dead-letter/return; retry-then-succeed; first-attempt success; latency exact on success and on DLQ path; cancellation; `x-attempts` from the loop; first-failed-at is the first failure; equals failed-at with one attempt | **Ported** → `services/orders/tests/unit/test_fact_retry.py` (S4.3, S5.2) |
| `FactRetryDispatcherParityTests` (3) | copy byte-identity; required from every consumer and no other; canonical names no service | **Ported, widened** to the publisher (S4.7) |
| `KafkaDeadLetterPublisherTests` ×3 services (9) | traceparent with a span; none without; every header value rendered | **Ported once** (the copies are one family) → `test_dead_letter_publisher.py` (S4.6), plus every value asserted in each service's integration case (S4.17 – S4.19) |
| `SagaDeadLetterTests`, `ProjectorDeadLetterTests`, `NotificationDeadLetterTests` (6) | poison retried, dead-lettered with headers, committed offset read from the broker moves, next fact processes; consume span continues the inbound trace into the DLQ | **Ported** (S4.17 – S4.19), with #9's poison shape (valid envelope, invalid payload; a non-UUID `correlationId` is refused by the envelope guard here, as #8 L9) |
| `SagaFactsConsumerTests` (3), `ProjectorFactsConsumerTests` (1 + 1 non-test `DelayAsync`) | raw bytes threaded; dispatch goes through the wrapper; unwrapped branches never invoke it; unknown type swallowed inside | **Ported** (S4.8, S4.11); `DelayAsync` is a helper the extractor matched, **not a case** |
| `SagaCommandDispatcherFirstParkTests` (2), `SagaFirstParkDeadLetterHandlerTests` (4), `SagaFirstParkDeadLetterTests` (1), `SagaCommandDeadLetterTests` (1), `OrderSagaFailureTests` (3) | hook once on a transition; not on no transition; no fact/DLQ when the claim loses; topic from the row; envelope-less claim appends without DLQ; concurrent claims one winner; full first-park chain; domain method mutates nothing else; mapper verbatim | **Ported** (S4.12 – S4.14) |
| `SagaCommandStoreTests` (9) | `EnqueueAsync` stores bytes and topic (1); duplicate enqueue keeps the first envelope (1); `FindOperatorCancelNoteAsync` ×7 | 2 **ported** (S4.11); 7 **not applicable**: #9 reads the note from `operator_note` (feature 41, `command_queue.py:64-81`), not from an envelope |
| `OrdersCancelAcceptanceTests` (4), `CancelOrderCommandHandlerTests` (1), `OperatorCancelRequestedEnvelopeTests` (1) | the note reaches the cancelled fact (3, feature 41's, already ported there); the operator park dead-letters the synthetic envelope (1); synthetic envelope omits the note key (1); topic constant (1) | 3 **not applicable** (feature 41, done); 3 **ported inverted** per G1 (S4.15 – S4.16) |
| `TraceContextCarrierTests` (14) | inject/extract/restore/no-span cases | **Ported** → `test_trace_context.py` (S3.4); the kafkajs encoding half never existed in #8 |
| `TraceContextPropagationTests` (4), `*ResponderTraceContinuationTests` (5), `ResponderTraceSubjectCoverageTests` (1) | NATS stand-in (1); Kafka write → relay chain; no span → no header; DB hop ordering; real responders continue; outbox stamped from the continued span with and without a header; 15 subjects through one site per class | Stand-in case **deliberately not ported** (#8 D1: it re-implemented extraction); the rest **ported** through production classes (S3.5 – S3.8) |
| `NatsSagaCommandsAdapterTests` (1), `NatsStockAvailabilityCheckerTests` (1), `NatsRpcClientIntegrationTests` (2) | two concurrent calls each carry their own trace; the Gateway client injects | **Ported**, with the overlap created by the test (S3.7; #8 D9) |
| `TelemetryWiringTests` (4) | one OTel version; every source registered; no Prometheus exporter; no Prometheus package | version and no-exporter **ported** (S0.3, S3.3); "every `ActivitySource` registered" **not applicable** (Python tracers are not opt-in by name; L21/L9 cover the real hazard) |
| `LogCorrelationTests` ×6 services (9), `ProblemJsonCorrelationTests` (1) | records of one unit carry correlation and trace ids; malformed envelope carries the inbound trace; omit when no span; server span + failure line; problem body and log line share the id | **Ported** per service through the real process (S1.6, S1.7) |
| `MetricsExposureTests` (4), `RealInfraMetricsProvenanceTests` (2), `OutboxRelayTests` (1), `SagaFactHandlerTests` metric cases (5), `RequestLatencyMiddlewareTests` (2) | lag aged then 0; DLQ depth from the broker, missing topic 0, topics independent; latency from a real fact; completion from real instants; gauge called once per cycle; completion one per close, nothing on non-closing or ignored; request latency on success and error | **Ported** (S5.2 – S5.7); #8's DLQ *sum* becomes per-topic (R59) |
| `SagaFactHandlerTests` non-metric cases (9) | raw bytes threaded (1, ported S4.11); operator-note and superseding cases (8, feature 41) | 1 ported; 8 **not applicable** (feature 41, done) |
| `HealthCheckAggregationTests` ×6 (18), `HealthProbesTests` ×6 (7), `HealthProbeTimeoutTests` (1), `HealthProbeCopyParityTests` (8), `MsSqlHealthCheckPoolingTests` (1), `KafkaHealthCheckLongRunningTests` ×3 (3) | aggregation; paused-container readiness; bounds enumerated; probe copy parity; no pooled probe connection; blocking metadata call off-thread | **Ported**, except the 3 long-running cases: **not applicable** (aiokafka's admin call is a coroutine; there is no blocking call to move off the loop — the S6.3 probe still runs under a bound) |
| `*ProgramConfigurationTests` fact-retry cases (6) and health-port cases (10) | defaults and substitution-safe reads | retry: **ported** to each consuming service's settings test (S4.2); health ports: **not applicable** (#9 serves health on each service's own app and `--port`, no `*_HEALTH_PORT` family) |
| `OrdersCreateIdempotentReplayTests` (5), `PlaceOrderRequestIdReplayTests` (7), `OrdersCreateAcceptanceTests` (1) | RI1 – RI5, no-tracking re-read, SQL 1205 lock inversion, first-time request on the wire | **Ported**, except the no-tracking case and the 1205 case: **not applicable** (no change tracker; PostgreSQL deadlock surfaces as `40P01` and the order-number lock order is the same, recorded in S2.4) |
| `DeadLetterBootstrapServersFallbackTests` (3) | the dead-letter producer uses the service's Kafka brokers | **Ported by construction + a test** (S4.5): there is no second setting, and the test asserts the producer's bootstrap equals `KafkaSettings.brokers` through the real composition |
| `KafkaFactStreamSubscriberConfigTests` (2) | earliest; group and commit-after-handler | **Already ported** by feature 16/24 (`test_kafka_fact_subscriber_options.py`), re-run in S4.17 |
| `KafkaGroupTeardownGuardTests` ×3 (9) | the clearance wait is structural; a failing test with a failing teardown reports its own failure | **Ported in kind** (S4.1): #9's harnesses delete and recreate the group per test (`saga/conftest.py:835-857`) or use a unique group; S4.1 enumerates every host-starting teardown and asserts it goes through the harness |
| `ProjectorConsumesOnlyTests` (1), `DocsAndAnonymousRouteHttpTests` (1), `HostInotifyReloadGuardTests` (1), `OperatorCancelRacesSagaForwardProgressTests` (4), `OperatorCancelRowLockConcurrencyTests` (1), `OperatorNoteReachesTimelineEndToEndTests` (1), `OrdersSagaDispatchValidationTests` (2), `TestRunSettingsDeliveryTests` (3), `SeedIntegrationTests` (1 in the extractor's output, unrelated) | projector consumes only; anonymous routes; reload disabled; cancel races; note end to end; dispatch degree; run settings | reload → **ported in kind** (S7.1, item 7); the rest **not applicable** (features 24, 25, 41, 16 and #8's build tooling; each already has #9 guards in its own feature) |

---

## 13. #8's backlog, classified

Regex over each entry's **subject** (`name` + `title`) of `../order-to-cash-dotnet/feature_list.json`, case-insensitive: `retry|retries|dlq|dead[ _-]?letter|trace|traceparent|span\b|spans\b|\blog\b|logs\b|logging|correlation|metric|readiness|health|idempotent[ _-]?replay|request[ _-]?id|requestid|reload`. **23 hits.**

| Id | Subject | Classification |
|---|---|---|
| 5 | messaging topology, `.dlq` companions | applies: the compose creates them (`docker-compose.infra.yml:197`); the test broker does not, so tests create private ones (S4.1) |
| 27 | this feature | — |
| 35 | dashboards | owned by #9 feature 35; the names it queries are guarded here (S5.8) |
| 36 | full compose | owned by #9 feature 36 |
| 38 | final checkpoint | owned by #9 feature 38 |
| 42 | terminal `RpcError` | done in #9 (feature 42); its deferred surfacing is item 9 (S7.3) |
| 58 | notification envelope copied by hand | not applicable: #9 parses the whole envelope with the generated model (`notification_facts_consumer.py`) |
| 63 | unpaced readiness loops | applies: every new poll loop is paced (250 ms) and bounded by `asyncio.timeout`; #9's `test_wait_helper_pacing.py` precedent |
| 69 | Gateway readiness pacing unguarded | applies to S6's poll helper: its pacing is armed by a change of kind (a fast-failing probe) in S6.6 |
| 71 | operator note, envelope bytes | bytes: S4.11; note: feature 41 (done, `operator_note`); synthetic envelope: G1 |
| 73 | degrading sender | done in #9 (`degrading_sender.py`); its interaction with the wrapper is guarded (S4.19: a permanent failure never dead-letters) |
| 74 | DLQ tests select by content; shared captures | applies: every DLQ read selects by the test's own `eventId`/`correlationId` on private topics; every capture over a shared sink (in-memory exporter, metric reader, caplog) is scoped to what the test produced (S4.17 – S4.19, S5.2 – S5.6) — armed with a decoy |
| 75 | `x-first-failed-at` semantics | applies: S4.3 with three distinct instants (entry ≠ first failure ≠ final failure). **Avoided on `FactRetry`, RECURRED on the first-park path (found in review round 1, B1):** `first_park.py` stamped `first_failed_at = failed_at = now` with `x-attempts` 3, and `test_saga_first_park_dead_letter.py` asserted the equality. Fixed: `saga_commands.first_failed_at` (§5.6), the integration test brackets the header by the first and second request arrivals the test itself observed |
| 77 | test hosts watch config for reload | applies in kind: item 7 (S7.1) |
| 81 | concurrent-trace test on a fixed 2 s budget | applies: S3.7's overlap is created by the test and its RPC budget comes from settings, not a literal 2 s |
| 86 | delegation guard anchors a call shape | applies: health wiring is proven behaviourally through the real lifespan (S6.7), never by matching the composition's syntax |
| 87 | relay deadlock victim | not this feature: #9's `test_outbox_relay_deadlock.py`; the relay changes here re-run it (S5.4) |
| 90 | dispatch degree clamp | not applicable: #9 has no degree (orchestrator G1) |
| 94 | SO9 arm satisfied by an in-process retry | applies: items 8 and 11 (§5.8) |
| 98 | web session expiry | not applicable (web) |
| 104 | dead-letter producer defaults to localhost | applies: S4.5 |
| 109 | instruments declare no unit | applies: §6.1, S5.8 |
| 110 | reply decode unguarded | done in #9 feature 16 (orchestrator L17) |
| 111 | relay poison payload loop | not this feature (#9's `wire.py` OI18 poison handling); unchanged by the trace header |

---

## 14. The defect classes of #8's three rejections → guards here

| #8 finding | Class | #9 guard or reason |
|---|---|---|
| D1 (round 1) | a guard re-implements the production code (stand-in responder) | §4.5; S3.6 drives the three production responder classes |
| D2 | a setting in six hosts guarded in two | S1.6 is a literal set of six real processes |
| D3, D5 | a ported-guard table reconciled by **file** not by **case**; three named test classes never existed | §12 is by case group with counts; S8.2 is per case, with the delivered name checked to exist (`pytest --collect-only -q` output) |
| D4 | unticked boxes | done gate item 1; S8.6 |
| D6 | instants asserted to parse, never to be right | S4.3 and S4.6 assert exact values from injected clocks, three distinct instants. **Recurred in kind at the first-park test (review round 1, B1):** it asserted `x-first-failed-at == x-failed-at`, an equality SA-3 forbids for `x-attempts` 3. Now: `test_r29_the_first_park_…` asserts `arrival_1 <= x-first-failed-at < arrival_2` from the instants the test observed, and `x-first-failed-at < x-failed-at`; `test_sa3_the_first_failed_attempts_instant_is_recorded_once_…` (distinct fixture instants) guards the `COALESCE`; the dispatcher unit cases `test_r29_sa3_…` guard what is handed to the ledger |
| D7 | a parity case that cannot fail when the bound is removed | S6.6 arms by **removing** the bound in each probe kind |
| D8 | a value guarded by `>= 0` | S5.2 exact values; `>=`/`>` comparisons on a measured value forbidden in this feature's tests unless the record says why |
| D9 | the overlap lived in the mutation, not the test | S3.7's connection wrapper creates it; armed by the plain hoist with no delay |
| D10 | the test's own instrumentation made the span | S3.9: no test-owned listener; the runtime's provider exports it |
| D11 | a retired sentence survives in production comments | S8.5: every retired wording (e.g. "`trace_parent` stays NULL until feature 27", "dead-lettered by feature 27", "feature 27 wraps") enumerated in `services/*/src` and rewritten; the search re-run to zero |
| Round-4 mechanism 2 | shared consumer group across tests | S4.1 (#8 id 74's teardown bullet, in kind) |

---

## 15. Testing approach

- **Levels.** Pure unit over fakes and in-memory readers/exporters; integration with testcontainers (`testcontainers.community.*`) and real PostgreSQL, Kafka, NATS, MongoDB; real processes for the log contract and shutdown. Never a mocked broker. Spans and metrics against the SDK's `InMemorySpanExporter` (`SimpleSpanProcessor`, so a span is visible when it ends) and `InMemoryMetricReader`, injected through the composition root's test seam.
- **Loop scopes.** Function-scoped by default; a module-scoped private container for the pause tests is written next to its fixture with its loop scope, and is unpaused in a `finally`.
- **Waits.** Every wait is `asyncio.timeout(...)` with a message naming the claim, synchronised on terminal or monotonic evidence (the dead letter arrived, the committed offset advanced), paced explicitly; never a bare sleep standing in for an outcome.
- **Fixtures do not satisfy the relation by accident.** Header instants differ (entry ≠ first failure ≠ final failure ≠ `occurredAt`); two request ids differ in every hex digit position the comparison could truncate; decoy records on the same topic precede the real one (#8 id 74).
- **Suites pass with the developer infrastructure down.** Every Kafka/NATS/PostgreSQL/MongoDB address comes from a container fixture; `OTEL_EXPORTER_OTLP_ENDPOINT` is blank for the session.
- **Coverage.** The existing gates (≥ 80 % domain, ≥ 60 % overall) apply; the domain addition is one method.

---

## 16. Live walkthrough (task S8.3, stated in advance)

Against the developer stack, restarted with `docker compose -p otcpy -f docker-compose.infra.yml start postgres mongodb kafka nats otel-collector jaeger prometheus`, Kafka healthy before any host starts, the developer `.env` carrying the three new keys (S8.4), `alembic upgrade head` for `otc_orders` (`0002` → `0003`):

1. Place one order through the Gateway with an `Idempotency-Key` (a UUID: the Gateway refuses any other value — leader note after S8b, finding F10), repeat it, and show the same `orderId` both times.
2. Show **one trace** in Jaeger for that order containing the Gateway server span, the `orders.create` request and responder spans, a `writemodel.transaction`, an `outbox.publish`, and at least one consumer span in another service.
3. Query Prometheus for the five series of §6.1 and show each non-empty with its `exported_job`.
4. Publish one poison fact (valid envelope, invalid payload) to a fact topic and show its dead letter on `<topic>.dlq` with every header, from the broker console or `kafka-console-consumer`.
5. Pause one dependency of one service and show `/health/ready` `503` naming it while `/health/live` stays `200`.

**Live data, read first** (`progress/current.md` "Live dev data"): the `notifications` group has unconsumed lag and **will send the lagged orders' emails** when it starts; `ORD-000007` projects a status Orders does not hold (do not use it); the three fact topics hold 24 redelivered copies of 8 events (the Projector and the saga deduplicate them; the walkthrough records whether any reaches a `.dlq`); parked `saga_commands` rows that predate `0003` will append one `order.saga_failed.v1` each on their next park (§5.6) — the implementer counts them before starting Orders and records the expected number.

---

## 17. Out of scope, restated

The composed-stack `R56` observation (feature 28); dashboards (35); any change to `SO1` – `SO17`, the step table or the sweeper's schedule beyond the first-park hook and `OR10`'s parent; a redrive consumer; `infra/` and compose; `specs/shared/` beyond the Status cells of `R16`, `R29`, `R56` – `R60`, `R62`.
