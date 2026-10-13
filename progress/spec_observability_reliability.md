# Spec pass — `observability_reliability` (id 27, phase 14) — gate record

## Status

The triple-doc is written: `specs/observability_reliability/{requirements,design,tasks}.md`. **Not done by this pass:** `feature_list.json` (the leader sets `spec_ready`), any file under `services/`, `packages/`, `tests/`, `apps/web/`, `infra/`, `.env.example`, any byte of `specs/shared/` (`git status --porcelain specs/shared` → empty), any git write.

**What needs a decision: four rows (§3).** G1 reverses the mechanism of acceptance item 12, so it is the one that needs the maintainer; G2 is a recorded decision the shared spec makes; G3 adds a column and a behaviour neither predecessor has; G4 picks between #7 and #8 where they differ. **No `SA-10` is proposed** (§4).

**Gate ruling (maintainer, 2026-10-12, verbatim): "approved"** — G1 – G4 as recommended: G1 (no dead letter for a parked operator-cancel release; acceptance item 12's synthetic-envelope mechanism is superseded by this spec), G2 (a terminal `rejected` command surfaces only its row and a structured ERROR line), G3 (`saga_commands.trace_parent`, restored by the sweeper), G4 (#8's order: commit, then publish). F2 (#7 and #8 dead-letter a payload `asyncapi.yaml` refuses) is recorded in the history only; the completed builds are not changed.

**Stages** (`tasks.md`, each ends green with its arms done): **S0** preparation (packages, census) → **S1** log contract → **S2** `R62` → **S3** tracing → **S4** retry / DLQ / first park / migration `0003` (items 8, 10, 11, 12) → **S5** metrics → **S6** readiness → **S7** items 7, 9, 13 → **S8** close-out (ledger walk, per-case ported-guard walk, live walkthrough, `quality.sh`).

---

## 1. Inherited — #7 and #8 agree, Python forces no difference (adopted, not gate questions)

| Decision | Citation |
|---|---|
| Retry policy 3 attempts, 500 ms doubling, `FACT_RETRY_MAX_ATTEMPTS` / `FACT_RETRY_BACKOFF_MS` | #7 `apps/orders/src/infrastructure/messaging/fact-retry-dispatcher.ts:37-50`; #8 `requirements.md` `OR1` |
| One canonical retry module copied per consuming service, parity-guarded | #7 OI12 parity spec; #8 `OR2`, `FactRetryDispatcherParityTests` |
| Envelope failures log-and-acknowledge, outside the wrapper; processing failures inside | orchestrator `design.md` L23 (`:118`); #8 `design.md` §3.1 |
| Projector's unknown type swallowed inside the wrapped callable | #7 `projector-facts.controller.spec`; #8 L11 |
| First park → one `order.saga_failed.v1` + DLQ copy, at most once per row, `SO5` unchanged; one guarded `UPDATE` | #7 `saga-command-dead-letter.integration.spec`; #8 `OR3`, L16 |
| `traceparent` through the outbox: stored at write, restored by the relay under a `PRODUCER` child span; no header without a span | #7 `outbox-recorder.ts:38`, `trace-context.spec`; #8 `OutboxWriter.cs:70`, `OutboxRelay.cs:211-219` |
| A `writemodel.transaction` span per write transaction | #8 L23 (`EfCoreUnitOfWork.cs:46`), stronger than #7 |
| OTLP push to the collector, no scrape endpoint, `service.name` per service; `infra/` untouched | #7 open point 5; #8 `OR5`; `infra/prometheus/prometheus.yml:1-21` |
| Metric names `otc_*` (#7's), **no unit** (#8's, its id 109) | #7 `apps/orders/src/infrastructure/observability/metrics.ts:27-39`; #8 `progress/impl_otel_instruments_never_declare_a_unit.md`; measured, §2 below |
| Readiness dependency table (Fulfillment/Billing without `factStream`) | #7 `apps/*/src/infrastructure/health/*-health-check.ts` names; #8 `design.md` §8.2 |
| Every probe bounded; dedicated Kafka client for the probe | #7 `kafka-health-check.ts:22`, `nats-health-check.ts:7-16`; #8 L26, L27 |
| `requestId` replay: fast path, unique index as the correctness mechanism, loser re-reads the winner, `requestId` → `causationId` | #7 `place-order.handler.ts:143, 159-163, 205-211`; #8 `RI1` – `RI5` |
| `R56`'s composed-stack observation is feature 28's | `test-matrix.md` R56 row (level *composed-stack*); #9 `feature_list.json` id 28 acceptance item 4 |
| Terminal `rejected` surfaces nothing but the row and an ERROR line | #7 `saga-command-dispatcher.ts:180-193`; #8 `SagaCommandDispatcher.cs:109-130` — and the shared spec (G2) |

## 2. Decided here because Python or `specs/shared/` forces a difference (with the evidence)

| Decision | Why it differs from #7 / #8 | Evidence (command or file) |
|---|---|---|
| structlog renders through `ProcessorFormatter`; the 36 stdlib call sites stay | keeps every `caplog` guard meaningful; #8's equivalent was host settings | `grep -rl 'import logging' services/*/src packages/*/src` → 36 |
| Logging installed at module level in each `main.py` | uvicorn configures its handlers before importing the app and logs `Started server process` after (`uvicorn/config.py:303`, `uvicorn/server.py:96-103`) | read in `.venv` this session |
| **FastAPI's native telemetry switched off in all six apps** | FastAPI 0.142.2 depends on `opentelemetry-api`, creates spans/metrics whenever a global provider exists, and auto-adds OTLP exporters from `OTEL_*` at lifespan start — a double-export hazard neither predecessor had | `uv.lock` (`fastapi → opentelemetry-api`); `.venv/.../fastapi/telemetry/_runtime.py:76-197`, `applications.py:1033-1045` |
| Per-runtime providers, never the global ones; explicit propagator, resource, sampler | globals are set-once per process (`opentelemetry/trace/__init__.py:552`); `opentelemetry.propagate` reads `OTEL_PROPAGATORS` at import (`propagate/__init__.py:108, 157`) | probe venv this session |
| OTLP/HTTP (4318), not gRPC (#8: 4317) | avoids `grpcio 1.84.0`; the collector accepts both (`otel-collector-config.yaml:9-13`) | `uv pip compile` this session |
| Hand-built Gateway server span (`TelemetryMiddleware`) | the framework's own spans are tied to the global provider (above); no contrib package wanted (`0.66b0`, monkey-patching) | as above |
| No migration for `R62` | PostgreSQL unique indexes are `NULLS DISTINCT` by default and `uq_orders_request_id` exists since `0001` | `0001_initial_orders_schema.py:101, 126` |
| Collision caught outside the transaction **by necessity** | PostgreSQL aborts a transaction on any error (orchestrator L10) | — |
| `triggering_event_envelope` is `bytea` | byte-exact by type (#7's `json` normalised, orchestrator L21) | — |
| Dead-letter key = the original record key (#7), not the event type (#8) | `asyncapi.yaml` `DeadLetterRecord` key is `UniqueId` | `KafkaDeadLetterPublisher.cs:72` vs `kafka-dlq-publisher.ts:65` |
| `otc_dlq_depth` per topic (#7), not summed (#8) | `R59` says "dead-letter depth per topic" | `KafkaDlqDepthGauge.cs:57-66` vs `outbox-relay.ts:241-242` |
| Header instants through `format_instant` | #8 rendered `ToString("O")`; one instant format on the wire (CLAUDE.md) | `KafkaDeadLetterPublisher.cs:56-57` |
| Synchronous gauges only | observable callbacks run on the reader's thread; asyncpg/aiokafka are loop-bound | — |
| SSE streams end on the exit signal (item 13), not a log classification | #8 ends them through the framework's abort (`StreamEndpoints.cs:144-150`); classifying uvicorn's text is defeat row 11 | §8.3 of the design |
| One literal key `correlationId` at every binding site | #8 bound `order_id` (`SagaCommandDispatcher.cs:84`) and `correlation_id` (`OutboxRelay.cs:151`) | read this session |

**Measured this session (throwaway, removed):** the series names (design §6.1) — a collector built from `infra/otel-collector/` and a `prom/prometheus:v3.14.0` with the reused `prometheus.yml` on a private network; the Python SDK with no unit stores `otc_*_bucket`, a `unit="ms"` stores `_milliseconds_bucket`, `unit="1"` `_ratio`, a counter `_total`; every series carries `exported_job` = `service.name`; the dashboard's p95 query returned both services. Containers, network and image removed (`docker ps -a | grep -c otc9-measure` → 0). The emitting-logger population (design §2.3) from two real Orders host tests at DEBUG. The new packages' import under `-W error` and `mypy --strict` in an isolated scratch venv.

---

## 3. Gate rows

### G1 — Item 12: a parked operator-cancel compensation publishes **no** dead letter (`OR12`) — **needs a decision**

**Recommendation: store no triggering envelope for an operator-cancel command; its first park appends `order.saga_failed.v1` and publishes nothing to a `.dlq`.** This reverses the mechanism acceptance item 12 names (store a synthetic `orders.cancel.requested` envelope and port #8's DLQ-copy guard).

**Evidence.** `asyncapi.yaml`'s dead-letter channel carries "Facts from `otc.orders.facts.v1` that a consumer failed to process N times" (`:187`), its payload is an `Envelope` (`DeadLetterRecord`, `:1553-1565`), and `Envelope.eventType` must match `^[a-z]+\.[a-z_]+\.v[0-9]+$` (`:2171`). `orders.cancel.requested` does not (`python3 -c "import re;print(bool(re.match(r'^[a-z]+\.[a-z_]+\.v[0-9]+$','orders.cancel.requested')))"` → `False`). #7 (`apps/orders/src/application/operator-cancel-envelope.ts:27`, built at `cancel-order.handler.ts:237`) and #8 (`src/Orders/Application/Commands/OperatorCancelRequestedEnvelope.cs:39`, guard `tests/Orders.IntegrationTests/OrdersCancelAcceptanceTests.cs:549`) both publish it, so both put a record on a fact `.dlq` that violates the channel's payload schema and that a "byte-for-byte republish onto the source topic" (`:198-200`) would turn into a malformed envelope on the facts topic. `R29` routes "the triggering **fact**"; an operator request has none — #8's own comment says so (*"R29 does not require this envelope (an operator cancel has no triggering fact in R29's sense); it is #7's own named convention, ported for parity"*, `OperatorCancelRequestedEnvelope.cs:7-23`). The envelope's other purpose — carrying the operator's note — is already served in #9 by `saga_commands.operator_note` (migration `0002`; `command_queue.py:64-81`). So the shared spec decides the behaviour, #7 and #8 deviate from it, and conforming needs no amendment.

**If overruled toward parity:** tasks S4.15 – S4.16 build #7's envelope and port #8's guard verbatim; nothing else moves. Parity would then rest on a payload the contract refuses, so it should come with an `SA-10` that admits it; I do not recommend that amendment.

**For the leader, outside this feature:** #7's and #8's publication is a finding against `specs/shared/` conformance in completed builds; filing it there is the maintainer's call.

### G2 — Item 9: a terminal `rejected` command surfaces nothing but its row and one structured ERROR line (`OR11`) — **recorded decision, confirm**

**Recommendation: no `order.saga_failed.v1`, no dead letter; build the absence guard and the structured ERROR line.** The shared spec decides it: `domain-model.md:475` defines `order.saga_failed.v1` as a command that "exhausted its in-line retries and parked"; `R29` triggers on "times out or returns a transport error" (`requirements.md:227-233`); `saga.md:237-240` names a terminal refusal (`PRECONDITION_FAILED` on `despatch.create` after a lost race) "the expected end of a lost race, not a saga failure: no retry, no dead-letter, no `order.saga_failed.v1`". #7 and #8 finally shipped exactly that (citations in §1). An amendment that surfaced every terminal rejection would contradict `saga.md` §6 for the race case; one that surfaced only "unexpected" codes would need a classification the spec does not have. Command: `grep -n -i 'saga_failed\|dead-letter' specs/shared/saga.md specs/shared/domain-model.md`.

### G3 — Sweeper-resumed commands continue the trace recorded at enqueue (`OR10`) — **needs a decision**

**Recommendation: add `saga_commands.trace_parent` (in migration `0003`) and restore it as the parent when the sweeper dispatches a row.** Neither predecessor does: #7's sweeper dispatches with no restored context (`saga-command-sweeper.service.ts:93-101`); #8's sweeper has no `Activity`/`Trace` reference (`grep -n 'Activity\|Trace' src/Orders/Infrastructure/Saga/SagaCommandSweeper*.cs` → 0). `R56` says "every RPC command" under one trace; the fast path already satisfies it through `contextvars` (orchestrator L7), and the sweeper is the only command path that loses it — which is exactly the path of a command that was parked, the one an operator investigates. Cost: one nullable column in a migration this feature writes anyway, one restore, two tests (S4.21). The orchestrator's design left this to feature 27 (`specs/order_saga_orchestrator/design.md` §11: *"feature 27 decides whether a resumed command starts a linked trace"*). If rejected: drop the column and S4.21; the sweeper starts a fresh root and `OR10` is struck.

### G4 — First park: commit the timeline entry, then publish the dead letter — **#7 and #8 differ; recommend #8's order**

**Recommendation: claim + `order.saga_failed.v1` in one transaction, then publish the `.dlq` copy; a failed publish is logged at ERROR naming the row, and the bytes stay in `triggering_event_envelope` for a manual republish.** #7 published first and stated the window; #8 committed first (#8 `design.md` §4.4, L17). #8's order guarantees the half `R29` makes user-visible (the timeline entry) and loses only a diagnostic copy that the row still holds; #7's order would keep re-publishing on every park while the database write fails, and its window loses the timeline entry instead. Guarded in S4.14 (publish failing → outbox row and `dead_lettered_at` still committed; armed by moving the publish inside the transaction).

---

## 4. `SA-10`

**None proposed, as a checked conclusion.** Item 9 is decided by `specs/shared/` (G2). Item 12's recommended realisation conforms to `specs/shared/` (G1); only the overruled branch would need an amendment, and I recommend against it. The remaining choices (§2) are realisations the shared spec leaves to each assessment. #8 closed the `x-first-failed-at` semantics with `SA-3` (`asyncapi.yaml:2227-2232`, registry `README.md:35`), which this feature follows.

---

## 5. Inherited #8 findings — owned here, and the rest of the backlog

| Id | Disposition in #9 | Where |
|---|---|---|
| 71 | triggering envelope bytes stored (`bytea`), byte-equal guard; the note half already done by feature 41; the synthetic envelope per G1 | S4.11, S4.15 |
| 74 | every DLQ read by content after a decoy; every shared-sink capture scoped | standing rule; S4.17 – S4.19, S5 |
| 75 | three distinct instants; first failure read in the first `except` | S4.3 |
| 94 | SO9 arms re-run through a genuine redelivery (a dead letter that is not durable); 3.8 retired by `R16` | S4.20, S4.22 |
| 104 | no second bootstrap setting; guard through the real composition | S4.5 |

The other 18 of the 23 backlog entries the subject regex selects are classified one by one in `design.md` §13 (regex and count there). The eleven blocking defects of #8's three rejected review rounds are mapped to guards in `design.md` §14.

---

## 6. Findings this pass surfaced (for the leader)

- **F1** — FastAPI 0.142.2's native OpenTelemetry (above). Not a defect today; a double-export and a hidden-environment-read hazard the moment any provider is configured. Guarded by S3.3.
- **F2** — #7 and #8 dead-letter a payload `asyncapi.yaml` refuses (G1).
- **F3** — #8's two `correlationId` binding sites with other keys (`SagaCommandDispatcher.cs:84`, `OutboxRelay.cs:151`), so its saga-dispatch and relay lines carry no `correlationId` key; #8's DLQ key is the event type, not the `UniqueId` the contract declares (`KafkaDeadLetterPublisher.cs:72`); #8's `otc_dlq_depth` loses `R59`'s "per topic". Recorded for the trilogy record; not this feature's to fix.
- **F4** — Acceptance item 2 says "`correlationId` in every log line"; `R58` scopes it to lines "produced while handling a request, a command or a fact". `OR7` follows `R58` (and #8's `OR7`): boot lines and library background lines are JSON with no `correlationId`, never a fabricated one. Stated so the item is read against the requirement.
- **F5** — Pre-existing parked `saga_commands` rows in the developer database will append one `order.saga_failed.v1` each on their next park after `0003` (they have no envelope, so no dead letter). The walkthrough counts them first (design §16).

---

## 7. `specs/shared/` stack-term grep (the standing instruction), classified

`git status --porcelain specs/shared` → empty: this pass changed nothing there. Command: a case-insensitive search for `nest|drizzle|nuxt|mysql|typescript|dotnet|efcore|mssql|csharp|python|fastapi|sqlalchemy|postgres|angular` over `specs/shared/*`, one line per match: **16 matches**.

| File:line | Match | Classification |
|---|---|---|
| `n8n-workflows.md:30, 149, 397` | *honest*, *honesty* | false positive |
| `openapi.yaml:34, 456`; `requirements.md:470, 477`; `test-matrix.md:22, 223` | *honestly*, *honest* | false positive |
| `openapi.yaml:447, 521, 1669` | `TimelineStreamEntry` | false positive |
| `test-matrix.md:179` (×2) | *nested* | false positive (inside the `R53` row's Status cell) |
| `test-matrix.md:180` | *PostgreSQL* | legitimate: the `R54` row's **Status** cell (column 5, each assessment's realisation record) |
| `test-matrix.md:202` | `python -m otc_gateway` | legitimate: the `R63` row's **Status** cell |

Every stack term this pass introduced lives in `specs/observability_reliability/design.md` and `tasks.md`.
