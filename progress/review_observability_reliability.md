# Review — feature 27 `observability_reliability` (phase 14, `sdd: true`, full group)

**Reviewer:** Opus, 2026-10-13. Brief: `progress/brief_review_observability_reliability.md`. Premise check: `progress/premise_review_observability_reliability.md`.

**Verdict:** REJECTED — 1 blocking finding (B1: the first-park dead letter's `x-first-failed-at` contradicts SA-3, and the test asserts it), 7 non-blocking (N1 – N7). Details §18 – §19.

## 0. Method

- Read: `specs/observability_reliability/{requirements,design,tasks}.md`, `progress/spec_observability_reliability.md` (gate G1 – G4), `progress/impl_observability_reliability.md`, `progress/current.md` ("Decisions taken this session"), `feature_list.json` id 27, `CHECKPOINTS.md`.
- **No full-suite re-run.** The claim "5 216 passed" is the implementer's `quality.sh` and the leader's per-stage JUnit artefacts (premise-checked). Instead: a workspace collection to resolve every name the matrix cites, the specific tests behind each question, and my own mutations (backups in `.arm/r27-review/` with `sha256`, restored by `cp` + `cmp`).
- Every test run under `setsid --wait timeout -k 10 <s> uv run pytest … --junitxml=.arm/r27-review/<name>.xml`; counts from the JUnit root.

## 1. Baseline facts I produced

- `uv run pytest --collect-only -q` (workspace): **5 218 collected** = the implementer's S8.6 `quality.sh` 5 216 + the two S8c tests (`test_a_blank_or_whitespace_smtp_credential_is_none_and_a_real_pair_is_kept`, `test_blank_smtp_credentials_deliver_one_message_to_a_real_mailpit`). Reconciles.
- `./init.sh` exit 0 (`.arm/r27-review/init.log`); `uv run lint-imports`: `Contracts: 13 kept, 0 broken.`
- `git diff --stat HEAD -- specs/shared`: only `test-matrix.md`, 12 +/12 −; `git diff -U0` read: 8 Status cells (R16, R29, R56 – R60, R62) and 4 summary-table lines. No other byte.
- **Every test name the eight changed matrix rows cite resolves to a collected test**: script `.arm/r27-review/names.py` over the `+|` lines of the diff → `79 names; 0 missing` (a `<svc>` placeholder matched as a pattern).
- The same script over `specs/observability_reliability/requirements.md` §4 → `24 req names; 1 missing` (`test_or1_a_cancellation_is_neither_an_attempt_nor_a_dead_letter`, delivered as two tests `…_during_work_…` / `…_during_the_backoff_…`) and one missing file (`services/orders/tests/integration/test_metrics_exposure.py`, delivered as the three `*_metrics_wiring.py` + `test_prometheus_series_names.py`). The §4 Status column still reads `TODO` on every row. → **N1**.

## 2. Q1 — One trace (item 1, R56 mechanism, R57)

- **Mutation 1a** (mine): `relay.py:134` `restored = context_from_traceparent(row.trace_parent)` → `restored = None` (backup `.arm/r27-review/relay.py.bak`, sha256 `b73929cd…`, restored, `sha256sum -c` OK). `test_trace_propagation.py`: **2 failed, 2 passed**. `test_r56_the_relayed_record_carries_a_child_of_the_writers_span_through_the_producer_span` fails at `(raw,) = header_values(record.headers, "traceparent")` and `test_r56_one_orders_create_yields_server_span_then_transaction_span_then_producer_span_by_parent_id` at `(producer,) = support.by_name(infos, "outbox.publish")`, both `ValueError: not enough values to unpack (expected 1, got 0)`. The hop is named by the failing source line, **not by an assertion message** (CLAUDE.md: "its message must name the claim"). → **N2**.
- **Mutation 1b** (mine): Gateway `nats_rpc_client.py:69` `inject_nats(headers)` → `pass`. `test_gateway_nats_headers_per_call.py` fails with `AssertionError: a call's request arrived carrying another call's trace` / `{'test.headers.a': 0} != {…: 2954…}` — the message names the *sharing* claim, not the *absence* (the diff shows trace id 0); `test_gateway_server_span.py` fails `assert (0, 0) == (176335…, …)` with no message. `test_gateway_log_contract.py` (2) passes — correct, its subject is the Gateway's own lines. Red for the right reason, message weak → part of **N2**.
- The consumer span in another service continuing the trace: per hop only — `KafkaFactSubscriber` ×3 opens the CONSUMER span under `extract_kafka(record.headers)` (read), guarded by `test_saga_trace.py` and the Projector/Notifications `test_r57_the_consume_span_continues_the_inbound_trace_and_the_dead_letter_carries_it`. The composed observation is routed, not narrated: `feature_list.json` id 28 acceptance item 4 ("R56: one trace id spans every request, command, transaction and fact for one order across the real services"), status `pending`. The S8.3 walkthrough's 46-span trace is a recorded live observation, not a guard.
- FastAPI native telemetry: `for f in services/*/src/*/presentation/app.py` → all six `FastAPI(...)` calls carry `telemetry={"tracing":False,"metrics":False,"logs":False,"operation_spans":False,"auto_configure":False}`; no other `FastAPI(`/`Starlette(` construction under `services/*/src` (grep). The guard `test_fastapi_native_telemetry_is_off_in_every_app` was re-armed in S8a (`s8a-3.3-billing-native-telemetry-on`). **Answer: yes.**

## 3. Q3 — Retry and dead letter (item 3, R16, SA-3, #8 ids 74, 75, 104)

- Read `fact_retry.py` (canonical): `first_failed_at` is taken inside the first `except`, `failed_at` inside the final `except`; the policy is read once; `CancelledError` is never caught; the publish propagates. `dead_letter_publisher.py`: `acks="all"`, `enable_idempotence=True`, `send_and_wait`, key and value the original, nine headers through `format_instant`.
- `test_orders_dead_letter.py` (read): a decoy is produced on the private `.dlq` **before** the runtime starts; dead letters are selected by `eventId` (`letters_of`); `x-error` is compared with an independently computed validation string; the committed offset is read from the broker (`committed_offsets_of`); topics are the harness's `private_topics`. Projector and Notifications follow the same shape (read).
- Bootstrap: `KafkaDeadLetterPublisher(settings.kafka, …)` and `KafkaFactSubscriber(settings.kafka, …)` in the Orders and Notifications compositions, and both from the same `settings` in the Projector's (`composition.py:225,229`): one source, no second default.
- **Mutation 3a** (mine, corrupt a field): `ERROR_LIMIT = 1000` → `1001` in Orders' `dead_letter_publisher.py`: `test_dead_letter_publisher.py` **1 failed** (`assert 1001 == 1000`). Restored, `sha256sum -c` OK.
- **Mutation 3b — S4.24** (mine, a different arm from the implementer's): in Orders' subscriber, the `except FactRetryStopped:` branch's `continue` → `pass`, so the stop falls through to the commit. Real-lifespan `test_f1_a_stop_during_a_long_backoff_…` **failed** `AssertionError: the committed offset (read from the broker) is unchanged by the stop / assert 2 == (0 + 1)`; the unit `test_f1_a_retry_interrupted_by_shutdown_is_not_committed_not_sought_and_not_a_handler_failure` **failed** `AssertionError: the record is NOT committed`. The `CancelledError` half: `test_f1_an_external_cancellation_of_the_stop_aware_sleep_propagates_as_cancelled_error` exists (read). Restored, OK.
- **Mutation 3c — S4.25** (mine): the worst-case sum `backoff * ((1 << (attempts - 1)) - 1)` → `backoff * ((1 << attempts) - 1)` in Orders' `settings.py`: `test_orders_settings_env.py` **3 failed**, each message naming both variables and the 300 000 ms bound (e.g. `FACT_RETRY_MAX_ATTEMPTS=10 with FACT_RETRY_BACKOFF_MS=587 waits 600501 ms …`). Restored, OK. Observation, not a finding: the bound counts back-off only, not the attempts' own run time nor the dead letter's 10 s `request_timeout_ms`; at the boundary (299 999 ms of back-off) the consumer would still be evicted. The leader's F2 decision words it as "worst-case total back-off", which is what was built.
- **The first-park dead letter breaks SA-3** → **B1** (below, §4).

## 4. Q4 — First park (R29 dead-letter clause, OR3, G1, G2, G4)

- `first_park.py` (read): lock order → one `UPDATE … WHERE id AND status='parked' AND dead_lettered_at IS NULL RETURNING` → event saved in the same transaction → publish after the commit, failure logged (G4). `test_or3_concurrent_claims_of_one_row_have_exactly_one_winner` (16 sessions behind a barrier) carries "exactly one" at the claim, and the event and the dead letter both hang off the one returned claim. G1: `test_or12_a_parked_operator_release_appends_one_saga_failed_and_publishes_no_dead_letter` reads the private and the real `.dlq` after a decoy. G2: `test_or11_…` (read). Agreed.
- **Mutation 4a** (mine): the `SagaCommand.status == "parked"` predicate removed from `claim_first_park` alone. `test_saga_first_park_dead_letter.py`, `test_saga_command_terminal_rejection.py`, `test_operator_cancel_park.py`, `test_saga_command_ledger.py`: **21 passed** — the predicate survives every test, as the dispatcher-routing mutation survived in S7.3. The behaviour (OR11) is guarded only by the compound mutation. **Decision on "is a single-defence guard owed":** the behaviour is guarded, so this is not blocking; but `claim_first_park` is a port method whose contract is "claims only a parked, unclaimed row", and both its predicates are mutable while only one (`IS NULL`) is armed. → **N3** (one direct case: `claim_first_park` on a `rejected` row returns `None` and leaves `dead_lettered_at` NULL; cheap, light).
- **B1 — the first-park dead letter's `x-first-failed-at` contradicts SA-3.** `services/orders/src/otc_orders/infrastructure/saga/first_park.py:80-81` sets `first_failed_at=now, failed_at=now` while `x-attempts` is the row's accumulated attempts (`row.attempts + max_attempts`, `infrastructure/saga/command_dispatcher.py:168`: 3 with the default in-line policy, so the two instants may be equal only if an operator configures one in-line attempt). `asyncapi.yaml` `DeadLetterHeaders` (SA-3): *"`x-first-failed-at` is the instant the FIRST processing attempt failed … it equals `x-failed-at` only when a single attempt was made."* So every first-park dead letter states `x-attempts: 3` and two equal instants — exactly what SA-3 says cannot co-occur, and the first failure (several seconds earlier: three 5 s in-line attempts) is lost. The test enshrines it: `services/orders/tests/integration/saga/test_saga_first_park_dead_letter.py:208` asserts `x-attempts == b"3"` and `:211` asserts `x-first-failed-at == x-failed-at`. Design §5.6 item 2 ("both instants the clock's at the claim") and delivery note (5) say so, so the implementation is faithful to the design — the design is what is wrong against `specs/shared/`.
  - **Provenance (read on disk):** #7 `apps/orders/src/infrastructure/saga/saga-first-park-dead-letter-handler.ts:50` `firstFailedAt: now`; #8 `src/Orders/Infrastructure/Saga/SagaFirstParkDeadLetterHandler.cs:113-121` passes `occurredAt, occurredAt`. A shape ported from both predecessors without asking whether `specs/shared/` decides it (CLAUDE.md, "evidence, not authority") — it does. It is **#8 id 75's class (`x-first-failed-at` semantics) recurring on the second dead-letter path**; design §13's row for id 75 ("applies: S4.3 with three distinct instants") covers `FactRetry` only.
  - **Why blocking:** acceptance item 3 says "with SA-3 header semantics"; the brief's Q3 asks for exactly this property; it is a wire-contract header value on a full-group feature; and a test asserts the contradiction, so no later run would ever flag it.
  - **What must change:** record the first failure's instant durably and send it. The dispatcher's in-line loop (`command_dispatcher.py:130-166`) already observes the first failure of the dispatch that parks; to be exact also when `row.attempts > 0` (an earlier, interrupted dispatch), persist it — migration `0003` is uncommitted, so a fifth nullable column (e.g. `saga_commands.first_failed_at timestamptz(3)`, set `COALESCE(first_failed_at, :now)` wherever the ledger records a failed attempt) costs one column; `claim_first_park` returns it; `first_park.py` sends it as `x-first-failed-at` and the park instant as `x-failed-at`. Replace the `:211` assertion by `x-first-failed-at < x-failed-at` against the instant the test observed for the first failure, with fixture instants pairwise distinct (tasks.md standing rule), and arm it (both instants = the claim's → red). A row parked before `0003` (no first-failure instant) is the only case where SA-3 cannot be met; state what is sent then (e.g. no dead letter is owed for it already, per OR3 (b) "WHERE the row stores the envelope" — a pre-`0003` row has no envelope, so the case does not arise). Update design §5.6, ledger, §13's id-75 row ("recurred, found in review").
  - **Routing for #7 and #8:** the same defect ships in both completed predecessors. This is not rooted in `specs/shared/` (the contract is clear), so no `SA-n`; it is a finding against #7/#8's code, which CLAUDE.md lets the maintainer decide on. The leader should file a numbered backlog entry (id 201+) recording "#7 and #8 first-park dead letters stamp `x-first-failed-at = x-failed-at` with `x-attempts ≥ 3` (SA-3)", attached to the trilogy README rows, for the maintainer's disposition — not a sentence in this review.

## 5. Q5 — Re-runs, not re-reads (items 8 and 11, #8 id 94)

- **SO9 arm re-run (mine): 4.20c**, the `consumer.seek(partition, record.offset)` removed from Orders' subscriber, ONE test `test_so9_a_failed_record_is_never_committed_past_while_its_dead_letter_is_not_durable`: **failed** `AssertionError: only 1 refused dead letters in 60 s (3 attempts)` — the implementer's verbatim message reproduced. Why this is a Kafka redelivery and not the in-process retry: the three in-process attempts did happen (`3 attempts`) and produced exactly one refused dead letter; the second and third rounds require the broker to hand the same offset out again (the seek), and without it they never come. Restored, `sha256sum -c` OK.
- **Projector `I4-commit-before-handler` re-run (mine):** a `consumer.commit({partition: record.offset + 1})` inserted before the CONSUMER span in the Projector's subscriber; `test_pr38_a_raising_handler_leaves_the_committed_offset_unchanged_read_from_the_broker` **failed** `AssertionError: an offset was committed although the handler raised / {('offset-contract-2aa17786', 0): 1}`, and `test_projector_dead_letter.py::test_or8_…` **failed** `AssertionError: the committed offset (read from the broker) is unchanged: the poison is not committed / assert 2 == (0 + 1)`. Both reds come from the group's committed offset as the broker reports it. Restored, OK.
- The first SO9 case (read) passes only if lifespan 2's NEW consumer redelivers (`attempts == attempts_before_the_restart + 1`, the failure cleared only after lifespan 1 ended). **Answer: yes, genuine redelivery; agreed.**

## 6. Q6 — Metrics (item 6, R59)

- Recording sites by search (`grep -rn 'request_latency\|fact_processing_latency\|saga_completion\|outbox_lag\|dlq_depth' services/*/src`, factories excluded): Gateway `presentation/asgi.py:127` (`TelemetryMiddleware`); `FactLatencyHistogram(fact_processing_latency(...))` in the Orders, Projector, Notifications compositions; `SagaCompletionHistogram` in Orders `composition.py:519`; `outbox_lag(...)` handed to the relay in Orders, Fulfillment, Billing; `dlq_depth(...)` in Orders `composition.py:598`. Each is the path design §6.2 names. Agreed.
- `tests/observability/test_prometheus_series_names.py` run by me against the real collector and Prometheus: **2 passed** (21.7 s). **Mutation 6a** (mine, sibling substitution): the Gateway copy's `REQUEST_LATENCY = "otc_request_latency_ms"` → `"otc_fact_processing_latency_ms"`: **failed** `AssertionError: the dashboards query series Prometheus does not store: ['otc_request_latency_ms_bucket']; it stores [...]`. Restored, OK. Note: in that test the attribute keys are supplied by the test itself (`{"endpoint": "GET /orders"}` …), so its attribute-key assertion compares a literal with a literal (defeat row 8); the production keys are carried by the unit tests (`test_request_latency.py`, `test_fact_processing_latency.py`, the `test_r59_*` cases of `test_fact_handler.py`, `test_dlq_depth.py`), which I read. No finding.
- **S5.5's weak arm, re-judged — agree.** `fact_handler.py:146-151`: a `DUPLICATE` returns before `self._metrics.closed(...)`, and a duplicate never runs `work`, so `closed` stays `None`: "record before the dedup check" is an equivalent mutant. The mutant that matters (recording inside `work`, before the commit) is carried by `test_r59_a_closing_step_whose_transaction_fails_records_nothing`.

## 7. Q7 — Readiness (item 4, R60)

- `tests/observability/health_support.py:52-61` `paused`: pause, `yield`, unpause in `finally` after a `reload()`. `docker ps --filter status=paused` empty after my runs.
- **Mutation 7a** (mine, sibling substitution): Billing `build_health_checks` with the two probes swapped (`writeModel` ← the NATS probe, `rpcTransport` ← the Postgres probe). `test_billing_health_probes.py` + `test_billing_readiness.py`: **4 failed**, e.g. `AssertionError: R60: readiness must name ONLY writeModel; it named {'rpcTransport': 'no answer within 2.0 s'}`. Restored, OK.
- **L32 re-armed in a second service** (mine): `poolclass=NullPool` removed from **Billing**'s `postgres_probe.py` (S7.7 used Fulfillment): `test_billing_health_probes.py` **1 failed, 1 passed** — `AssertionError: not within 7.5 s: readiness never reported writeModel down while its container was paused (after 0 reads, last [])`, the S7.7 message verbatim. L32 is armed; S6's "cannot be armed" was wrong, as the leader ruled. Restored, OK.

## 8. Q8 — R62

- `test_ri2_a_repeated_request_id_replays_the_original_reply_and_writes_nothing_more` asserts `second == first` (the whole reply dict) plus the three money fields, one stock check, one `orders` row, one outbox row. The reply is `_result_of(order)` over immutable fields (`place_order.py:111-121`), so a replay after the order progressed still answers the original reply. Concurrent race: `joint_releases == ROUNDS` (the barrier observable), `translated_per_round == [1] * ROUNDS`, one row and one `order.placed.v1` per round. Omitted id: `test_ri4_no_request_id_performs_no_lookup` (the lookup fake raises). Agreed.
- **Fast path after the order-discount refusal — accept the behaviour, reject the wording.** `place_order.py:129-132` refuses `orderDiscount != 0` before the replay lookup (#7's order). A reused key with a different body being refused is the defensible reading of an idempotency key. But **RI2 is a reused #8 id** ("reusing an id is a claim that the #9 realisation satisfies the same requirement", requirements.md preamble) and its text is unconditional ("WHEN `orders.create` carries a `requestId` for which a committed order exists, THE SYSTEM SHALL … return that order's original reply"); #8 satisfies it literally (lookup first, `PlaceOrderCommandHandler.cs:39-50` per the leader's S2 note), #9 does not for `requestId` known + `orderDiscount ≠ 0`. → **N4**.

## 9. Q9 — No reload (item 7)

- Stopping rule (written before the sweep): one probe file with the shell-string forms I could think of in five minutes; stop at the first form that is not caught.
- **Probe 9a** (mine, defeat row 11): an untracked `services/orders/tests/integration/test_review_probe_reload.py` holding `subprocess.run("python -m uvicorn otc_orders.main:app --port 0 --reload", shell=True)` and `os.system("uvicorn otc_orders.main:app --reload")`. `tests/architecture/test_no_reload_servers.py`: **16 passed** — neither the population (a string argv is neither `"uvicorn"` as an element nor an opaque `Popen`; `os.system` is not a listed call) nor the violation search (`FORBIDDEN_STRING` is anchored at `^--reload`) sees it. File removed; `git status` clean.
- The property itself holds today, by a second instrument: `grep -rn -i 'reload\|watchfiles\|os\.system\|create_subprocess_shell\|shell=True' services/*/tests packages/*/tests tests conftest.py --include=*.py` (guard file excluded) → 15 hits, every one classified: 13 are aggregate/row "reload" in prose or variable names (`test_invoice_repository.py:5,199,213`, `test_invoice_mapper.py:125`, `test_despatch_store.py:373,405,408,412`, `test_order_repository.py:175-178,182,183`), 1 the word in a docstring (`test_fact_retry.py:204`), 2 Docker's `container.reload()` (`health_support.py:59,66`). No shell spawn exists. → **N5** (the guard's blind spot, not a present violation).

## 10. Q10 — Copy-parity families

- `test_observability_copy_parity.py`: `SERVICES` is a six-entry literal (`:41`), `NOT_RUNTIME = {"seed"}`, families `OBSERVABILITY_MODULES` (logging, metrics, telemetry, trace_context), `MESSAGING_MODULES` (fact_retry, dead_letter_publisher) over the literal `FACT_CONSUMERS` checked against `asyncapi.yaml`, and the health family incl. the Gateway's `health_checks.py`. The outbox family stays in `test_outbox_copy_parity.py`.
- **Mutation 10a** (mine): `CHECK_TIMEOUT_SECONDS = 2.0` → `3.0` in the Gateway's `health_checks.py` (a one-character drift in the family's odd member) **and** a real seventh package `services/zzprobe/src/otc_zzprobe/__init__.py`, run with `.venv/bin/python -m pytest` (uv refuses a workspace member without `pyproject.toml`, itself a second guard): failures `'unlisted service package: zzprobe:otc_zzprobe'` and `'gateway/health_checks.py: differs from the canonical after the docstring'`. Restored (`sha256sum -c` OK), directory removed, `git status` clean. Agreed: the population is a literal, a seventh package fails, a one-character drift fails. The other families' one-character and deleted-copy cases are kept sentinels on temporary trees (`test_sentinel_*`, read), and the S1.5/S4.7 real-tree arms are in the record.

## 11. Q2 — Log contract (item 2, R58, OR7)

- `tests/observability/log_contract_support.py:156-201` `check_contract` (read): every non-blank stderr line one JSON object with non-empty `level`/`logger`/`event`/`timestamp` in the wire format; no empty value; `traceId`/`spanId` hex; uvicorn's `Started server process` line is JSON; lifecycle lines carry no `correlationId` (never fabricated); the provoked lines carry the unit's id; with `trace_id` given, lines with the trace ⇔ lines with the `correlationId`. Production handler: `logging.StreamHandler(sys.stderr)` on the root (`logging.py:100`), synchronous, so L7 holds by construction and the six real-process tests would lose `traceId` under a queue handler.
- **L2 (Gateway by-hand path) — agree.** `python -m otc_gateway` (README.md:192, the documented way) passes `log_config=None`, so nothing needs re-propagating; `uv run uvicorn otc_gateway.main:app` (README.md:204, documented as an alternative) does need the loop, and the Gateway's `logging.py` must equal the canonical after the docstring (`test_observability_copy_parity.py`, my 10a shows the instrument bites), whose loop is executed by the five `python -m uvicorn` log-contract tests. The by-hand path also loses OR13's `end_all` — stated in `__main__.py`'s docstring.
- **L4 (explicit `extra` masks three bindings) — agree.** The rendered value is identical either way; what a deleted binding would lose is the id on lines OTHER modules write inside the unit (SQLAlchemy, aiokafka), and the census (`test_correlation_binding_sites.py`, armed in S1.4 by deleting a site) is the guard that the binding exists at exactly those sites. S1 finding 1 promised rendered-line cases at the relay and dispatcher in S3.5/S4.14 that were never written; the S8a acceptance supersedes the promise — record that in the effort entry so it is not lost with `current.md`.
- **Item 13 — agree, and armed again.** The test starts a real `python -m otc_gateway`, opens two SSE streams over raw sockets (reads `stream.ready` from each), sends SIGTERM, and judges EOF ≤ 2 s per stream, exit before the graceful bound, no ERROR line, every line JSON. **Mutation 11a** (mine, partial deletion): `StreamHub.end_all` ends only the first subscription → **failed** `OR13: the streams ended after [5.149…, 0.041…] s; each must end within 2.0 s … the process exited 5.2 s after the signal … shutdown logged errors: [… 'Cancel 1 running task(s), timeout graceful shutdown exceeded' …]`. Restored, OK.

## 12. Q11 — Ledger spot-check (design §11, 41 rows by `sed -n '/^## 11/,/^## 12/p' design.md | grep -c '^| L'` → 41)

Stopping rule: twelve rows, the six the brief names plus six on paths my mutations already touched; stop there.

| Row | Guard | Does it execute the row's subject? | My evidence |
|---|---|---|---|
| L2 | six log contracts + copy parity | yes for five services; the Gateway by copy | §11 |
| L4 | binding census | yes (AST over `services/*/src`) | §11 |
| L7 | six real-process log contracts | yes: production `StreamHandler` is synchronous (`logging.py:100`) | read |
| L10 | `test_or1_a_cancellation_during_work_is_neither_an_attempt_nor_a_dead_letter` | yes | **mutation (mine)** `except Exception` → `except BaseException` in `fact_retry.py:140`: `Failed: DID NOT RAISE CancelledError`, 1 failed / 16 passed |
| L13 | `test_or8_the_runtime_starts_and_stops_in_two_successive_event_loops` | yes: two `asyncio.run` over `start_runtime`; a producer from loop 1 fails at `start()` in loop 2 (it never publishes in loop 2, which the module-cache arm does not need) | read |
| L20 | composition bootstrap | yes: one `settings.kafka` for both | read (§3) |
| L23 | NATS per-call headers | yes | mutation 1b |
| L26 | relayed record carries the writer's trace via the producer span | yes | mutation 1a |
| L32 | paused `writeModel` case | yes | **re-armed in Billing** (§7) |
| L36 | first park at most once | yes for `IS NULL`; **no single-defence guard for `status='parked'`** | mutation 4a → N3 |
| L38 | Prometheus series | yes, real collector + Prometheus | mutation 6a |
| L41 | stop during back-off | yes, real lifespan, broker offsets | mutation 3b |
| S8c SMTP row | `test_a_blank_or_whitespace_smtp_credential_is_none_and_a_real_pair_is_kept`; real-Mailpit test | yes | **mutation (mine)** `not value.strip()` → `not value`: `AssertionError: '   ' / assert ('   ', '   ') == (None, None)`. Citations checked on disk: #7 `smtp.config.ts:42-48` `isConfigured` trims; #8 `MailKitSmtpTransport.cs:9-12` "deliberately never calls `AuthenticateAsync`". **But the row lives only in `progress/impl_observability_reliability.md` S8c, not in `design.md` §11** (CLAUDE.md: "The ledger lives in `design.md` for `sdd: true` features") → N6 |

## 13. Q12 — Test names are claims

Stopping rule: fifteen names, read through `.arm/r27-review/body.py` (prints every `assert`/`waits` of the function) or in full; stop at fifteen unless one fails.

| # | Test | Name holds? |
|---|---|---|
| 1 | `test_r16_a_poison_fact_is_retried_then_dead_lettered_byte_for_byte_with_every_header_and_the_committed_offset_read_from_the_broker_moves_past_it` | yes (attempts 3, bytes equal, eight headers, broker offset + 1, next fact) |
| 2 | `test_or8_an_unacknowledged_dead_letter_leaves_the_offset_uncommitted_and_a_restarted_consumer_redelivers` | yes |
| 3 | `test_f1_a_stop_during_a_long_backoff_returns_within_a_small_bound_with_the_offset_unchanged_and_nothing_on_the_dlq_and_the_record_is_redelivered_after_the_restart` | yes (< 10 s, broker offset, `letters_of == []`, no failure line, restart dead-letters) |
| 4 | `test_r29_the_first_park_appends_one_order_saga_failed_and_dead_letters_the_triggering_envelope_once_and_a_second_park_emits_neither` | yes as named — **but it asserts SA-3's contradiction at :211 (B1)** |
| 5 | `test_or3_concurrent_claims_of_one_row_have_exactly_one_winner` | yes (`len(winners) == 1` over 16) |
| 6 | `test_or12_a_parked_operator_release_appends_one_saga_failed_and_publishes_no_dead_letter` | yes (decoy seen, none mentioning or keyed by the order, one `order.saga_failed.v1`) |
| 7 | `test_or11_a_rejected_command_appends_no_saga_failed_publishes_no_dead_letter_and_logs_one_structured_error` | yes (`[line] = error_lines()` is the "one") |
| 8 | `test_or13_an_exit_signal_ends_every_open_stream_before_the_bound_and_logs_no_error` | yes ("every" = the two it opens) |
| 9 | `test_r60_readiness_reports_the_paused_dependency_down_within_its_bound_while_liveness_answers_throughout_and_recovers` | yes (`health_support.observe_pause`: liveness read during and after, bound, recovery) |
| 10 | `test_r59_the_gauge_is_the_age_of_the_older_of_two_unpublished_rows_then_zero_after_the_drain` | yes (7123.0 exact, then 0.0) |
| 11 | `test_r59_each_dead_letter_topic_reports_the_count_the_broker_holds_and_a_missing_topic_reports_zero_without_starving_the_others` | yes |
| 12 | `test_r56_the_three_responder_classes_serve_exactly_fifteen_subjects` | yes |
| 13 | `test_r59_a_successful_fact_records_exactly_240_5_ms_once_under_its_consumer_token` | yes (sum 240.5, count 1, attributes) |
| 14 | `test_r56_two_concurrent_saga_commands_each_carry_their_own_commands_trace_id` | yes |
| 15 | `test_r58_a_problem_and_its_log_line_carry_the_request_correlation_id` | yes |
| 16 | `test_or2_the_population_equals_the_spec_consumers_and_no_other_service_holds_a_copy` | yes |

No name over-claims. (#4's problem is the assertion, not the name.)

## 14. Q13 — Avoided / recurred

| Item | Verdict | Evidence |
|---|---|---|
| #8 id 71 | **avoided** | bytes: S4.11 real-Kafka byte equality, re-armed in S8a; note: feature 41; synthetic envelope: G1 inverted, `test_or12_…` |
| #8 id 74 | **avoided** | decoy-first, by-content reads (`test_orders_dead_letter.py`, read); private topics; teardown enumeration (S4.1) |
| #8 id 75 | **avoided on `FactRetry`, RECURRED on the first-park path** | B1 |
| #8 id 94 | **avoided** | my 5a / 5b re-runs (§5) |
| #8 id 104 | **avoided** | composition reads one `settings.kafka` (§3); S4.5 arms ×3 |
| design §14 D6 ("instants asserted to parse, never to be right") | **recurred in kind** | `test_saga_first_park_dead_letter.py:211` asserts an equality SA-3 forbids for `x-attempts = 3` |
| design §14, other rows | agree as written | — |
| S8.2 per-case table | **agree** | re-ran `.arm/r27/s8a/check_s8_2.py` against my own collection: `cases extracted: 223 … delivered-name references: 183 | resolved: 183 … missing: [] ambiguous: []` |
| F4 (#8 case 201, not ported) | **agree** | the saga harness resets `orders.saga` at setup (`history="skip"` deletes then commits to the end) and every other consumer-starting module uses a test-unique group or private topics (S4.1 table, read); a leaked group cannot poison the next test. The re-open trigger is fine as written |

## 15. Q14 — The other accepted dispositions (`progress/current.md`)

| Disposition | Verdict |
|---|---|
| S1 F1 (explicit `extra` masks bindings) / S8a F2 (L4) | agree (§11) |
| S1 F3 (importing `main` configures the root logger in pytest) | agree; suite green, recorded |
| S2: `test_order_construction_sites.py` literal `handle` → `_place` | agree: `git diff` shows the one literal moved, still exactly one site |
| S2: RI2 fast path after the order-discount refusal | behaviour agreed; wording not (N4) |
| S3 F1 (traced-components guard), F2 (routed to S4.19, done), F3 (ERROR spans for replay / terminal rejection) | agree |
| S4a F1 → S4.24, F2 → S4.25 | agree; both re-armed by me (3b, 3c) |
| S4a F3 (no guard forbids a poison on a real topic; trigger "a test publishing to a real fact-topic constant") | agree, with N7 |
| S4b (a) `requirements.md:581` "all thirteen payloads", accepted with evidence, no `SA-10` | agree on substance: `specs/shared/requirements.md` §10 is headed "Left to Pass B" and describes what Pass B was to write (`sed -n 572,586p`). The disposition and its re-open trigger are recorded **only in `progress/current.md`**, which resets at session close → N7 |
| S4b (b) `.mypy_cache` in two populations → S5.10 | agree: `git diff` of `test_money_guard.py` adds `service_directories` (listing-time exclusion) and a sentinel; no assertion removed |
| S5 F1 (S5.5 arm), F2 (`otc_dlq_depth` stale while the broker is down) | agree (§6; readiness `factStream` goes down in that state) |
| S6 findings 2 – 8 | agree as recorded |
| S6 "L32 cannot be armed" → S7.7 | agree with the leader; re-armed by me in Billing |
| S7.3 plain arm survived (two defences) | agree it is not blocking; N3 for the unguarded predicate |
| S7 findings 2 – 4 | agree |
| S8a F1 (L2), F3 (L6), F4, F5, F6, F7, F8 | agree |
| S8b F8 → S8c fix, F9 → S8c recount, F10 noted | agree; F8 re-armed by me (§12); F9: my `names.py` resolves every cited name, and the table's 55 / 1 / 7 equals the implementer's script output, which the leader re-summed |
| Out-of-Bounds edits (`test_cqrs_registration_explicit.py` + `field_validator`, `test_write_path_population.py` + three classified `postgres_probe.py` entries and the claim's `update`, `test_import_contract_coverage.py`, `test_money_guard.py`) | agree: every hunk is additive classification or listing-time exclusion with a sentinel; no assertion was removed or loosened (`git diff HEAD -- tests/architecture/`, 278 +/8 −; the 8 removed lines are the replaced literals) |

## 16. `R<n>` → test mapping verified

| Id | Tests (resolved in my collection) | How I verified beyond the name |
|---|---|---|
| R16 | `test_orders_dead_letter.py`, `test_projector_dead_letter.py`, `test_notifications_dead_letter.py` (r16 / r57 / or8 / f1), `test_fact_retry.py`, `test_dead_letter_publisher.py` | read; mutations 3a, 3b, 3c, L10, 5b |
| R29 (dead-letter case) | `test_saga_first_park_dead_letter.py` ×3, `test_operator_cancel_park.py`, `test_saga_command_ledger.py` (r29 byte-equal), `test_order_saga_failure.py` | read; mutation 4a — **and B1** |
| R56 (mechanism) | `test_trace_propagation.py` ×3, three `test_*_responder_trace.py`, `test_responder_trace_subjects.py`, `test_gateway_server_span.py`, `test_saga_trace.py`; composed leg → feature 28 item 4 | mutations 1a, 1b |
| R57 | the above + three `*_nats_headers_per_call.py` | mutation 1b |
| R58 | six `test_<svc>_log_contract.py`, `test_saga_malformed_envelope_log.py` ×2, `test_log_rendering.py`, `test_correlation_binding_sites.py` | read the checker; mutation 11a (the Gateway's process is the same harness) |
| R59 | `test_metric_instruments.py`, `test_fact_processing_latency.py`, `test_request_latency.py`, `test_outbox_relay_lag.py`, `test_fact_handler.py` r59 cases, `test_dlq_depth.py`, `test_orders_host_lifespan.py` r59, `test_prometheus_series_names.py`, three `*_metrics_wiring.py` | ran the Prometheus test; mutation 6a |
| R60 | five `test_<svc>_readiness.py`, `test_health_probes.py`, `test_mongo_probe.py`, `test_health_probe_bounds.py`, six `test_<svc>_health_probes.py` | mutations 7a, L32 |
| R62 | `test_place_order_request_id.py` ×6, `test_orders_create_idempotent_replay.py` ×6 | read (§8) |

All 79 names in the eight changed Status cells resolve (`names.py`: `79 names; 0 missing`).

## 17. `CHECKPOINTS.md`

**C1** — [x] the five harness files exist (`ls`) · [x] `progress/current.md`, `progress/history.md` · [x] seven agents in `.claude/agents/` · [x] each declares a model or states it inherits (leader, reviewer, spec_author: "Deliberately has NO pinned model") · [x] `./init.sh` exit 0.
**C2** — [x] one feature `in_review`, none `in_progress` (Counter: 47 done, 11 pending, 1 in_review) · [x] all statuses valid · [x] done features' tests pass (implementer's `quality.sh`, leader's S8c run; not re-run by me in full) · [x] `current.md` describes this session · [x] no `blocked` feature.
**C3** — [x] `lint-imports`: 13 kept, 0 broken · [x] no cross-service DB access or import (independence contract kept; probes reach only their own service's DSN) · [x] shared runtime code unchanged (`packages/shared_kernel`, `packages/cqrs` not touched) · [x] no `domain` imports `otc_cqrs` (contract) · [x] `dependencies = []` unchanged · [x] no `float`/`Decimal`/`/` in the two changed domain files (`domain/events.py`, `domain/order.py`: grep empty) · [x] every new interaction classifies: dead letters and DLQ depth are Kafka (`DeadLetterRecord` channels), readiness probes are reachability calls, traceparent rides existing NATS/Kafka headers · [x] no TODO / `print(` / `breakpoint(` in the 146 changed source files (grep empty).
**C4** — [x] `quality.sh` exit 0, 5 216 passed (implementer S8.6; leader per-stage JUnit; **not re-run in full by me** — I ran the specific tests and 16 mutations or probes listed above) · [x] domain test pure (`test_order_saga_failure.py` imports: stdlib, pytest, `otc_orders.domain`, `otc_shared_kernel`) · [x] integration tests on testcontainers with the stack down (only `otcpy-n8n` running throughout my runs) · [x] coverage 96.38 % / domain 98 % (implementer's log) · [x] no Jest/Karma/Jasmine.
**C5** — [x] no stray files (my probe file and `services/zzprobe` removed, `git status` clean of them) · [ ] history entry with effort record — **not written: REJECTED** · [x] `feature_list.json` set to `in_progress` by this review · [ ] manual-test handover — leader's, after approval · [x] Claude did not commit.
**C6** — [x] `specs/observability_reliability/` has the three files · [x] EARS, 18 local ids (OR1 – OR13, RI1 – RI5) · [x] 86 of 86 tasks ticked (but see B1: S4.14's box is ticked over an assertion that contradicts SA-3) · [x] every `R<n>` this feature owns names collected tests · [ ] spec commit precedes implementation commit — not yet committed (wrap-up).
**C7** — [x] `specs/shared/` identical to #7/#8 except Status cells and the summary table (`init.sh` §5d green; my `git diff`) · [x] no new deviation, no `SA-10` · [x] the R ids are #7's · n/a n8n, API script (features 31/33) · [ ] every inherited #8 finding accounted for — **id 75 recurred (B1)**, to be recorded as such · [ ] effort record — on approval.

## 18. Findings

### Blocking

**B1 — The first-park dead letter states `x-attempts ≥ 2` with `x-first-failed-at == x-failed-at`, which SA-3 says cannot co-occur; the test asserts it.** `services/orders/src/otc_orders/infrastructure/saga/first_park.py:80-81`; `services/orders/tests/integration/saga/test_saga_first_park_dead_letter.py:208,211`; `specs/observability_reliability/design.md` §5.6 item 2 and delivery note (5). Full analysis, provenance (#7 `saga-first-park-dead-letter-handler.ts:50`, #8 `SagaFirstParkDeadLetterHandler.cs:113-121`) and the fix in §4. #8 id 75's class, recurred on R29's path.

### Non-blocking (each with a proposed disposition; all are cheap, so "fix now" per the Phase 7 ruling unless the leader decides otherwise)

- **N1 — `requirements.md` §4 is stale.** Two planned names never delivered (`test_or1_a_cancellation_is_neither_an_attempt_nor_a_dead_letter`; file `services/orders/tests/integration/test_metrics_exposure.py`) and every Status cell still `TODO`, against the file's own rule ("a delivered name that differs is reworded on its `tasks.md` box and here"). Evidence: `.arm/r27-review/names.py` output (§1). *Fix (light):* reword the two rows to the delivered names and write the Status cells.
- **N2 — Three trace-hop failures do not name the hop.** Mutation 1a fails with `ValueError: not enough values to unpack` at `test_trace_propagation.py` (`(raw,) = header_values(...)`, `(producer,) = support.by_name(...)`); 1b fails with "a call's request arrived carrying another call's trace" (the sharing claim, while the actual break is an absent header) and `test_gateway_server_span.py`'s bare `assert (0, 0) == …`. CLAUDE.md arming protocol: "its message must name the claim". *Fix (light):* assert presence with a message (`assert len(values) == 1, "the relayed record carries no traceparent: the relay did not restore trace_parent"`, likewise the `outbox.publish` span and the injected header), re-arm 1a and 1b.
- **N3 — `claim_first_park`'s `status = 'parked'` predicate survives every test** (mutation 4a: 21 passed). *Fix (light):* one integration case calling `claim_first_park` on a `rejected` (and on a `sent`) row: `None` returned, `dead_lettered_at` still NULL; arm by removing the predicate. The OR11 compound arm stays as is.
- **N4 — RI2's text is unconditional; #9's order is not.** `specs/observability_reliability/requirements.md:38` vs `place_order.py:129-132`. RI2 is a reused #8 id, so the reuse claims #8's behaviour (lookup first). *Fix (light, spec-local):* reword RI2 to "WHEN a valid `orders.create` (one the handler does not refuse before reference data: a non-zero `orderDiscount`) carries …", cite #7's order (`place-order.handler.ts:68-77`) and #8's divergence, or give it a new id `OR14`; add a unit case for "known `requestId` + non-zero `orderDiscount` → refused, no replay" so the accepted order is a guarded claim, not an accident.
- **N5 — The no-reload census is blind to shell-string spawns** (probe 9a: `subprocess.run("python -m uvicorn … --reload", shell=True)` and `os.system("uvicorn … --reload")` pass all 16 tests). The property holds today (second instrument, §9). *Fix (light):* count every `shell=True` call, `os.system`, `os.popen` and `create_subprocess_shell` as an opaque spawn in the population (so a new one fails the literal), search string constants for a `--reload` / `--watch` **token** (`(^|\s)--(reload|watch)`), add both forms as sentinels.
- **N6 — The S8c ported-idiom row is not in the ledger.** It sits in `progress/impl_observability_reliability.md` S8c only; CLAUDE.md puts the ledger of an `sdd: true` feature in `design.md`. *Fix:* add it to `design.md` §11 as L42 (or to feature 23's design ledger, whose idiom it is), with its guard names.
- **N7 — Dispositions that exist only in `progress/current.md`.** `current.md` resets at session close; the accepted-with-trigger dispositions (S4b (a) `requirements.md:581`; S4a F3; S8a F4; S1 finding 1's unkept promise superseded by S8a F2) must move into the feature's `progress/history.md` effort entry with their re-open triggers when the feature closes. *Leader action at close.*

### Routed, not narrated

- B1's twin in **#7 and #8** (complete repositories): not a `specs/shared/` defect (SA-3 is clear), so no `SA-n`. **The leader should file a numbered backlog entry (next free id ≥ 201)** — e.g. "#7 `saga-first-park-dead-letter-handler.ts:50` and #8 `SagaFirstParkDeadLetterHandler.cs:113-121` stamp `x-first-failed-at = x-failed-at` on a first-park dead letter with `x-attempts ≥ 3`, contradicting SA-3 (`asyncapi.yaml` `DeadLetterHeaders`)" — attached to the trilogy README benchmark rows / the maintainer's next touch of #7 and #8, for the maintainer's disposition. I do not write `feature_list.json` entries.

## 19. Verdict

**REJECTED — 1 blocking finding (B1), 7 non-blocking (N1 – N7).**

Everything else the brief asked about holds under my own mutations: one trace per hop (1a, 1b), the log contract and item 13 (11a), retry and dead letter with SA-3 instants on the consumer path, S4.24 and S4.25 (3a – 3c), the first-park claim, G1, G2, G4 (4a aside), genuine Kafka redelivery for items 8 and 11 (5a, 5b), the five series in a real Prometheus (6a), readiness against paused containers and L32 (7a, Billing L32), R62, the copy-parity families (10a). The one defect is a wire-contract header value on the dead-letter path R29 adds, guarded by a test that asserts the wrong value.

### What must change before re-review

1. **B1:** carry the first failure's instant into the first-park dead letter (§4 has one design), send the park instant as `x-failed-at`; replace `test_saga_first_park_dead_letter.py:211` with an assertion against the instant the test observed for the first failure (distinct fixture instants), armed (both instants = the claim's → red, message naming SA-3); update design §5.6, ledger (§11), §13 id 75 ("recurred on the first-park path, found in review") and §14 D6.
2. **N1 – N6** fixed as proposed (or each given a written disposition by the leader), N3 and N5 and N2 armed.
3. Re-run `test_saga_first_park_dead_letter.py`, `test_operator_cancel_park.py`, `test_saga_command_terminal_rejection.py`, `test_trace_propagation.py`, `test_gateway_nats_headers_per_call.py`, `test_gateway_server_span.py`, `tests/architecture/test_no_reload_servers.py`, the Orders migration tests if a column is added, `test_orders_models_match_migration`, and `./quality.sh` (the change touches a migration).
4. The leader files the backlog entry for #7/#8 named above.

Re-review scope: B1's change and the N-items only; the rest of this review stands unless those changes touch it.

### Effort note for the record (not the history entry)

This review: one session, 2026-10-13, about 70 minutes wall clock; 16 mutations or probes, each restored by `cp` and checked by `sha256sum -c` (backups in `.arm/r27-review/`), no full-suite re-run.

---

# Round 2 (2026-10-13) — scope: B1 and N1 – N6

**Verdict: APPROVED — 0 blocking findings.**

Inputs: `progress/impl_observability_reliability.md` "Review round 1 fixes"; the leader's `quality.sh` (exit 0, `5226 passed in 830.58s`, `.arm/r27-round2/quality.log`). No full-suite re-run by me; my collection: `5226 tests collected` (= 5 218 + the 8 new tests the record lists). Correction to round 1: I named a non-existent `test_orders_models_match_migration`; the models-vs-migration checks are `test_orders_schema_types.py` and `test_orders_migration_lifecycle.py`, as the leader notes.

## B1 — closed

- **Built (read):** migration `0003` gains `saga_commands.first_failed_at timestamptz(3)`; `SqlAlchemySagaCommandLedger.park` and `.reject` write `COALESCE(first_failed_at, :given)` (`command_ledger.py:168,194`); the dispatcher stamps the first `SagaCommandError` of its in-line loop (`command_dispatcher.py:157-158`) and hands it to `park`/`reject`; `claim_first_park` returns it; `first_park.py:81-82` sends it as `x-first-failed-at` and the park instant as `x-failed-at`. The old `:211` equality is gone; the test now brackets `x-first-failed-at` between the first and second request arrivals the stand-in observed and requires it `< x-failed-at` and equal to the stored column.
- **The `claim.first_failed_at or now` fallback — argument accepted.** By search, the only statement that writes `status="parked"` is `park` (`command_ledger.py:193`; `grep -rn "'parked'\|\"parked\"\|PARKED" services/orders/src`: the other hits are reads/filters or an enum), and `park`'s `first_failed_at` parameter is a non-optional `datetime` (`saga_command_store.py:114`), so `COALESCE(NULL, :given)` is never NULL for a parked row; the claim requires `status = 'parked'` (now armed, N3). The dispatcher's own `first_failed_at or self._clock.now()` at `park` is unreachable too (`park` follows ≥ 1 failed attempt). A pre-`0003` parked row has no envelope, so OR3 (b) owes no dead letter for it. The fallback can therefore never put two equal instants beside `x-attempts ≥ 2`; it is a type-narrowing default, stated as unreachable in design §5.6. A `CHECK (status <> 'parked' OR first_failed_at IS NOT NULL)` would make it structural, but would refuse the migration on any database holding pre-`0003` parked rows — not worth it. No finding.
- **Mutation R2-a** (mine; the implementer did not arm the dispatcher side): `command_dispatcher.py:157` `if first_failed_at is None:` → `if True:` (restamp on every failure). `test_command_dispatcher.py` + `test_saga_first_park_dead_letter.py`: **2 failed of 28** — `test_r29_sa3_the_park_carries_the_instant_of_the_first_failed_attempt_not_the_last` (`AssertionError: SA-3: the first failed attempt's instant is kept; the later attempts did not restamp it`, 12:00:03.5 vs 12:00:01.5) and the integration `test_r29_the_first_park_…` (`AssertionError: SA-3: x-first-failed-at is the first attempt's failure; observed arrivals [...]`). Restored, `sha256sum -c` OK.
- **Mutation R2-b** (mine, transposition): `first_park.py` `first_failed_at=now, failed_at=claim.first_failed_at or now`. `test_saga_first_park_dead_letter.py`: **1 failed of 4** (`assert b'2026-10-13T02:09:40.446Z' == b'2026-10-13T02:09:41.322Z'`, the `x-failed-at == fact["failedAt"]` line, message-less but red). Restored, OK.
- The implementer's B1-a (both instants the claim's → `SA-3: …`) and B1-b (`COALESCE` removed → `the second park overwrote it`) are recorded verbatim with backup hashes. **#8 id 75: recurred on the first-park path in round 1, closed in round 2** — the effort entry should say exactly that. B1's twin in #7/#8 goes to the history per the leader (F2 precedent); not re-opened.

## N1 – N6 — closed

| Item | My check |
|---|---|
| N1 | `.arm/r27-review/names.py` on a fresh collection: `79 names; 0 missing` / `26 req names; 0 missing`, no missing file |
| N2 | **re-ran mutation 1a** myself: now `AssertionError: R56 hop outbox row -> Kafka record: the relayed record carries no traceparent (the relay did not restore the row's trace_parent as the producer span's parent): []` and `R56 hop outbox row -> relay producer span: 0 spans named 'outbox.publish', expected exactly 1` (2 failed, 2 passed). Restored, OK. 1b's new messages are in the record (`… a request arrived with NO traceparent (trace id 0) …`) |
| N3 | `test_or3_claim_first_park_answers_none_and_leaves_the_marker_null_for_a_row_that_is_not_parked` collected; the implementer's arm (predicate deleted → `a rejected row is not parked: nothing to claim`) is the mutation 4a that survived in round 1 |
| N4 | `requirements.md:38` RI2 now conditions on a valid request and cites #7 `place-order.handler.ts:68-77` and #8's divergence; `test_ri2_a_known_request_id_with_a_non_zero_order_discount_is_refused_and_not_replayed` collected and armed (replay moved before the refusal → `Failed: RI2: …`) |
| N5 | **re-ran my probe 9a** (same untracked file, removed afterwards, `git status` clean): now caught twice — `… test_review_probe_reload.py:7: the string 'python -m uvicorn otc_orders.main:app --port 0 --reload' asks for reload` and the population literal (`'services/orders/tests/integration/test_review_probe_reload.py': 2`) |
| N6 | `design.md:479` holds L42 (blank dotenv credential), with #7/#8 citations and the guard names |
| N7 | the leader's at close (not in scope) |

`git diff --stat HEAD -- specs/shared`: unchanged from round 1 (`test-matrix.md` only, 12/12). All my round-2 mutations restored (`r2_dispatcher.sha`, `r2_first_park.sha`, `relay.sha`: OK; `grep -rl REVIEW-MUTATION services tests`: nothing). The round-1 `command_queue.sha` no longer matches **by design**: the implementer's round-2 fix edited `command_queue.py` (the claim now returns `first_failed_at`); the file holds no mutation marker and keeps its `status == "parked"` predicate (`:76`), so the old backup must not be restored.

## CHECKPOINTS delta

C5 "history entry with effort record" and C7 "every inherited #8 finding accounted for" / "effort records": **owed by the leader** — under this round's rules I may write only the status line, so I have not appended to `progress/history.md`. The entry must carry: both review rounds (round 1 REJECTED on B1, round 2 APPROVED), #8 ids 71, 74, 94, 104 avoided and **75 recurred then closed**, design §14 D6 recurred in kind then closed, N1 – N6 fixed, and N7's dispositions moved out of `current.md` (S4b (a) `requirements.md:581` with its trigger, S4a F3, S8a F4, S1 finding 1 superseded by S8a F2). The feature is not closeable until that entry exists. Every other box stands as walked in round 1.

**Status:** feature 27 → `done` (single-line edit; `git diff -U0` read, JSON parses). `./init.sh` now exits 1 with one failure, `progress/current.md claims a feature while none is active`: expected once the feature is `done`, and cleared when the leader resets `current.md` at close.
