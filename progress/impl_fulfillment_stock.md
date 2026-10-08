# Implementation report — feature 17 `fulfillment_stock` (phase 9, full group)

Status: **`in_review`** (set by L6). Every task of `specs/fulfillment_stock/tasks.md` is ticked. `./quality.sh` exits **0** (final run after the last edit: 315 s, 2686 passed; `init.sh` exit 0). Nothing was committed or pushed.

## 1. What was built

The Fulfillment service's first runtime: the `StockItem` aggregate with its `Reservation` child entity and the order-scoped pure operations (`reserve_order`, `release_order`); five NATS responders (`fulfillment.stock.check / reserve / release / list / replenish`) as one asyncio task; the lock protocol (stock rows first, one `SELECT … FOR UPDATE` each in code-point order, then the order's reservations) at a pinned `READ COMMITTED`, with the `40P01` re-run; Fulfillment's copy of the outbox writer, relay and Kafka publisher with a parity guard; the composition root, lifespan, readiness and single-relay guard; the SA-4 lock as two methods feature 18 reuses; and the live walkthrough of the parked `ORD-000007`.

Files (all under the task list's "may touch" set, except the notes in § 12):

- Domain `services/fulfillment/src/otc_fulfillment/domain/{errors,events,order_stock_reservation,reservation,snapshot,stock_item}.py`.
- Application `application/{handlers,messages,scope,stock_replenishment,stock_reservation}.py`, `application/ports/{__init__,clock,ids,stock_store}.py`.
- Infrastructure `infrastructure/{clock,ids}.py`, `infrastructure/settings.py` (five classes added), `infrastructure/persistence/{stock_mapper,stock_reads,stock_repository,stock_transactions}.py`, `infrastructure/outbox/{__init__,errors,publisher,kafka_publisher,relay,relay_task,wire,writer}.py` (copies) + `{topic,payloads}.py`, `infrastructure/messaging/{__init__,subjects}.py`.
- Presentation `presentation/{stock_headers,stock_responder,stock_rpc_errors,stock_wire}.py`, `presentation/app.py` (Orders' readiness shape); `composition.py`, `main.py`.
- Tests: 12 integration + 17 unit files under `services/fulfillment/tests/` (+ `unit/domain/conftest.py`, the `integration/conftest.py` host fixture), `tests/architecture/test_outbox_copy_parity.py`, `test_fulfillment_rpc_error_retryability.py` (new) and the edits of `test_composition_env_reads.py`, `test_registration_behaviour.py`, `test_write_path_population.py`, `test_kafka_client_confinement.py`.
- Root `conftest.py` (`NatsServer` / `nats_server` moved), `services/orders/tests/integration/conftest.py` (its copy deleted), `.env.example` (two variables), `services/fulfillment/pyproject.toml` + `uv.lock`, `specs/shared/test-matrix.md` (column 5 of R30 – R35, R61's domain half, the counts), `specs/fulfillment_stock/requirements.md` § 3 statuses, `specs/fulfillment_stock/tasks.md` (ticks).

Packages installed: **none** (`aiokafka` and `nats-py>=2.16.0` were already in `uv.lock`; `git diff uv.lock` adds only the two workspace-metadata entries per dependency list, no package version).

## 2. A1 — the design's premises against the repository as committed

Commands: reading the cited files at the cited lines. **Substance: every claim is true. Line numbers: several of the design's citations are stale** (the Orders files are shorter than the lines cited). This is a documentation error in `design.md` / `requirements.md`, not a false premise; I went on and report it here instead of stopping, because no decision depends on a line number. Corrected citations:

| Item | Cited | Actual (this checkout) | Substance |
|---|---|---|---|
| `models.py` columns (`stock`, `reservations`, `outbox`, `processed_events`, `despatches`) | 60 – 138 | 59 – 150 (`Stock` 59, `Reservation` 72, `Despatch` 87, `Outbox` 117, `ProcessedEvent` 137) | every column of the §1 table exists; unique `(company_code, product_code)` at 61, `ix_reservations_order_reference_status` at 74, `despatches.order_reference` unique at 94 |
| `QUANTITY_COLUMNS` | 148 – 158 | 151 – 157 | the five guarded columns are there |
| `orders_create_responder.py` task per request / `_drain` / `_log_fault` / no-reply drop | 98-102, 69-108, 130-132, 111-113 | 98-102 ✔, 105-108 (`_drain`), 130-132 ✔, 111-113 ✔ | ✔ |
| `composition.py` | 134 – 499, 213 – 261, 363 – 369 | the file is **464** lines: `start_runtime` 314 – 464, `assert_single_outbox_relay` 185, `_claim_relay_slot` 214 – 229, engine/NATS creation 329 – 334 | ✔ |
| `unit_of_work.py` | 87 – 96, 34 – 69, 92 | 88 – 96 (`begin`), `READ COMMITTED` pin at 92 ✔, clear-after-commit 94 – 96 | ✔ |
| `relay.py` | 46 – 48, 83 – 88, 137 – 150 | 46 – 48 ✔, 83 – 88 ✔, 137 – 150 ✔ | ✔ |
| `nats_saga_commands.py` | 197 – 209 (terminal set), 276 – 279 (headers) | **the file has 181 lines**: `TERMINAL_RPC_ERROR_CODES` at 65 – 75, the fresh header dict at 143 – 146 | nine terminal codes, `CONFLICT` among them ✔ |
| `reference_catalog.py` | 24 – 53 | 24 – 52 | exact `==` / `in_` ✔ |
| `nats_stock_availability.py` | 58 – 62, 72 – 90 | 57 – 62, `_decode` ≈ 72 – 90 | `success \| RpcError`, no headers sent ✔ |
| `writer.py` (design §3 L9, "243 – 258") | 243 – 258 | **the file has 72 lines**: `session.add` 57, `await session.flush()` 72 (one per row) | ✔ |
| `test_saga_command_headers.py::test_so14…` | cited in `requirements.md` FS2 | exists (feature 16) | ✔ |

## 3. A2 baseline and J4 result (developer stack down; only `otcpy-n8n` ran)

| | exit | duration | pytest | coverage |
|---|---|---|---|---|
| A2, before any change | 0 | 268 s | **2387 passed** (Orders 992) | overall 99 %, domain 98 % |
| A4, Orders' integration suite after the `NatsServer` move | — | 160 s | **992 passed** = A2's Orders share, no Orders test changed behaviour | — |
| J4, after the feature | **0** | 309 s | **2686 passed** | overall 98 %, domain **99 %** (`otc_fulfillment.domain`: 99 %, 2 lines missed) |

Delta **+299** = 297 tests in the 31 new test files (integration 64 + unit 218 + architecture 15) + 1 in `test_registration_behaviour.py` (the `fulfillment` parameter) + 1 in `test_kafka_client_confinement.py` (a sentinel). Per-file counts: integration `test_fulfillment_host_lifespan` 21, `test_fulfillment_outbox_relay` 1, `test_stock_check` 3, `test_stock_deadlock_retry` 1, `test_stock_list` 2, `test_stock_release_idempotency` 7, `test_stock_replenish` 3, `test_stock_repository` 5, `test_stock_reserve` 10, `test_stock_reserve_race` 3, `test_stock_responder_concurrency` 1, `test_stock_wire` 7; unit/domain `test_domain_tests_are_pure` 2, `test_reservation` 14, `test_reservation_release` 2, `test_stock_item` 6, `test_stock_replenishment` 1; unit `test_fact_topic` 1, `test_fulfillment_settings_env` 24, `test_outbox_payloads` 6, `test_stock_lock_order` 2, `test_stock_mapper` 2, `test_stock_replenishment_service` 2, `test_stock_requests` 90, `test_stock_reservation_service` 9, `test_stock_responder` 28, `test_stock_rpc_errors` 13, `test_stock_subjects` 2, `test_stock_transactions` 14; architecture `test_outbox_copy_parity` 13, `test_fulfillment_rpc_error_retryability` 2.

`uv run lint-imports` (J2): 11 contracts kept, 0 broken; `otc_fulfillment` is in `domain-purity`, `fact-producer-confinement`, `layers-fulfillment` and `service-independence` (output in `.arm/impl17/j2_lint_imports.txt`). J3: `services/orders/tests/unit/test_idempotent_consumer_parity.py` 19 passed, file unedited (`git diff --stat` empty), case 3's literal `{"otc_orders"}` still holds.

## 4. The ported-idiom ledger, as realised (`design.md` § 3, L1 – L26)

Each row: where #9 supplies the property, the guard, and its arm result (ids refer to § 8).

| # | Realised by | Guard → arm result |
|---|---|---|
| L1 | `SqlAlchemyStockRepository._lock_stock_rows` / `_lock_reservations_of`, stock rows first then the order's reservations, `READ COMMITTED` pinned by `run()` | D5 `test_fs19_the_reservation_read_made_after_the_stock_lock…` → **D5a** (swap the two reads) RED: `assert [] == [UUID(...)]`. **Round 2:** the same construction for `lock_order_items` (the method `stock.release` and feature 18 use): `test_stock_repository.py::test_fs25_the_release_lock_reads_…` → **R1** (swap lines 101 – 102) RED: `the lock read the order's reservations BEFORE the stock lock was granted …` |
| L2 | `lock_for_reserve` reads ALL of the order's reservations (any status, any product) | D6 `test_the_reserve_lock_returns_every_reservation_of_the_order_including_products_outside_the_request` → **D6** (scope to locked ids) RED; H5 `…_for_a_reissue_naming_a_different_product` → **H5b** RED. The concurrent-disjoint residual (G1) is accepted by the gate and **not** guarded |
| L3 | one `SELECT … FOR UPDATE` per key in `distinct_stock_keys` order | E3 (unit) → **E3a** RED; I3 (held-two-rows, WARNING count) → **I3** RED: `no transaction was a deadlock victim: ['stock transaction was a deadlock victim (SQLSTATE 40P01); re-running it from the start']` |
| L4 | exact `==`, plain `sorted()`; no `lower()` / `upper()` anywhere in Fulfillment | E3 `test_codes_differing_only_in_letter_case_are_two_keys` → **E3b** RED; H12 → **H12b** RED (case-insensitive end to end) |
| L5 | Python `int` is exact; the column width is enforced where `stock_mapper` assigns | H10 `test_fs20…` → **H10b** (`update(Stock).values`) RED: reply becomes `INTERNAL_ERROR`; D8 unit → **D8** RED |
| L6 | no upsert, no check-then-insert, no `ON CONFLICT` | D9 write-path census → **D9a**, **D9b** RED |
| L7 | `asyncio.Semaphore(FULFILLMENT_MAX_CONCURRENT_REQUESTS)` inside the request task before the unit of work; `pool_size = bound + 1`, `max_overflow = 0` | F6 → **F6a**, **F6b** RED; H9 → **H9** RED; G4 (`engine.pool.size() == 8`, recorded `pool_size/max_overflow`) → **G4b** RED |
| L8 | closed mapping in `stock_rpc_errors.py`; `CONFLICT` produced by no input | F4 + `tests/architecture/test_fulfillment_rpc_error_retryability.py` (imports Orders' `TERMINAL_RPC_ERROR_CODES`) → **F4a, F4a2, F4b, F4c** RED |
| L9 | Orders' writer copied (one `session.flush()` per row) | C3 parity → **C3b** RED: `writer.py: differs from the canonical … '-            await session.flush()'` |
| L10 | `Msg.data` bytes in, `Msg.respond(bytes)` out | H8 → **H8** RED (`{"response": …}` wrapper) |
| L11 | generated pydantic models through `from_wire_json` | F2 (42 constraint cases, each at the decoder and through the responder with nothing dispatched; 90 tests) → **F2a, F2b** RED; two edge checks: headers (F3 → **F3a, F3b**), `orderReference ≤ 20` (**F2c**) |
| L12 | `StockTransactions.run` = one session + one transaction per attempt | D7 `test_a_failure_after_save_inside_run…` → **D7b** RED (orphan outbox row) |
| L13 | `READ COMMITTED` pinned per transaction | D5 `…_runs_at_read_committed` → **D5b/D5c** RED (`'repeatable read' == 'read committed'`; the first test surfaces the 40001) ; D4 `…pinned_before_the_first_statement` → **D4g** RED |
| L14 | `run()` re-runs `40P01` at most 3 attempts, 0.2 s before each | D4 → **D4a, D4b2, D4c, D4d, D4e, D4f, D4g, D4h** RED; I4 (a real `40P01`) → **I4** RED |
| L15 | `new_id` required at four sites | B7 `test_fs24…` → **B7a – B7d**, one site each, failing at test lines **400, 403, 411, 434** |
| L16 | Orders' `run` / `_drain` / `_log_fault`, ported | F7 → **F7** RED |
| L17 | `await connection.flush()` after the last `subscribe` | F8 → **F8a, F8b** RED |
| L18 | engine, NATS and producer created in `start_runtime`, closed in the lifespan's loop; no aiokafka object built in `__init__` (the publisher copy) | the host fixture is function-scoped; `PytestUnraisableExceptionWarning` is an error; G7's boot-failure tests |
| L19 | `except Exception` only; cancellation propagates | F9 → **F9** RED; D4 → **D4e** RED |
| L20 | `mypy --strict` over the whole workspace (nats-py is typed; aiokafka only behind the copied publisher) | `quality.sh` step 3 green |
| L21 | `to_wire_json` for every reply, `RpcError` and outbox payload; `RawJson` column | H8, C3 |
| L22 | `orderReference` > 20 → `VALIDATION_FAILED` | F2 `test_fs28_a_reference_longer_than_the_column_is_refused_as_validation_failed` → **F2c** RED |
| L23 | the reference stays a `str` end to end | H5 `test_fs28_reserves_for_ord_000000…` → **H5c** RED |
| L24 | no idempotent-consumer copy, no `AIOKafkaConsumer` | J3 green unedited; J1 → **J1a** RED |
| L25 | relay-family copies identical after the docstring (modulo the map **and the formatter's reflow**, § 11) | C3 + sentinels (13 tests) → **C3a, C3b, C6c** RED |
| L26 | no `/` in this feature's code except `OutboxRelaySettings` ms → s (the settings boundary, as Orders'); paging offset is `(page - 1) * page_size` | `tests/architecture/test_money_guard.py` over `otc_fulfillment.domain` green |

## 5. Branch enumerations

### 5.1 `StockTransactions.run` (D3) — every branch and the test that drives it

| Branch | Test |
|---|---|
| commit; result returned; events cleared **after** the commit | `unit/test_stock_transactions.py::test_events_are_cleared_only_after_the_commit_returns` (arm D4f) |
| events kept after a rollback | same test, second half (`work` raises → no `clear_events`) |
| isolation pinned before the first statement | `…::test_the_isolation_is_pinned_before_the_first_statement` (arm D4g); real level `integration/test_stock_repository.py::test_fs19_every_stock_transaction_runs_at_read_committed` (arm D5c) |
| `40P01` with attempts left → warn, sleep 0.2, re-run (new session) | `…::test_fs23_a_deadlock_victim_is_rerun_at_most_three_times…` (survivor half), `…::test_each_attempt_gets_its_own_session_and_transaction`; real: `integration/test_stock_deadlock_retry.py` |
| `40P01` exhausted → `StoreUnavailableError("40P01")`, nothing committed | `…::test_fs23_a_deadlock_victim_is_rerun_at_most_three_times…` (arms D4a, D4b2) |
| non-`40P01` transient SQLSTATE, each of the literal set (`40001`, `55P03`, `57014`, `53300`) and class `08` (`08006`, `08001`) → one call, `StoreUnavailableError` | `…::test_fs23_no_other_store_failure_is_rerun[…]` (6 parameters; arm D4c) |
| non-transient `DBAPIError` (`23505`) → one call, re-raised unchanged (identity) | `…::test_fs23_a_non_transient_database_error_is_reraised_unchanged_and_not_rerun` |
| `DBAPIError` with no `sqlstate`, and a domain error → one call, not mapped | `…::test_fs23_an_error_carrying_no_sqlstate_and_a_domain_error_are_not_rerun` |
| pool timeout (`sqlalchemy.exc.TimeoutError`), `OSError` from `work` or from opening the session → `StoreUnavailableError` | `…::test_a_pool_timeout_and_a_refused_connection_are_store_unavailable` (arm D4h) |
| cancellation during the back-off → propagates, no further attempt | `…::test_a_cancellation_during_the_backoff_propagates_and_runs_no_further_attempt` (arm D4e) |
| the 200 ms pacing | the recorded `sleep` calls `[0.2, 0.2]` (arm D4d: zero recorded sleeps) |

### 5.2 `StockResponder` (F5) — every branch of `start`, `run`, `_serve`, `_drain`

| Branch | Test (`unit/test_stock_responder.py` unless noted) |
|---|---|
| subscribe ×5 with the queue group, then flush | `test_fs27_start_flushes_after_the_last_subscription` (arms F8a, F8b) |
| `run` before `start` | `test_run_before_start_is_refused` |
| no reply subject → warn, drop, loop survives | `test_a_request_without_a_reply_subject_is_dropped_and_the_loop_survives` |
| empty body | `test_an_empty_body_is_answered_validation_failed` |
| header refusal (reserve / release, 7 faults each) | `test_fs3_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_or_malformed` (arms F3a, F3b) and the control `test_fs3_check_list_and_replenish_succeed_with_no_header_at_all` |
| decode refusal (every schema constraint) | `unit/test_stock_requests.py` (90 cases; arms F2a, F2b) |
| each mapped error / unmapped → `INTERNAL_ERROR` without the exception's text | `test_a_mapped_error_is_answered_with_its_code_and_an_unmapped_one_as_internal_error`; the table in `unit/test_stock_rpc_errors.py` |
| the `RpcError` carries `x-correlation-id` | `test_the_rpc_error_carries_the_correlation_id_of_the_request_when_present` |
| reply sent | every happy-path test (`test_fs3_the_command_carries_the_correlation_and_request_ids_from_the_headers`) |
| reply raises → logged, drain not abandoned | `test_fs26_shutdown_with_one_faulted_and_one_healthy_request_in_flight_completes_and_waits` (arm F7) |
| stop with queued messages (a request delivered while the subscriptions close is served) | `test_a_request_that_arrives_while_the_subscriptions_are_closing_is_still_served` |
| stop with in-flight requests (drain waits for every one) | `test_fs26_…` |
| cancellation of `run` → request tasks cancelled, re-raised | `test_cancelling_the_task_propagates_and_cancels_its_requests` (arm F9) |
| the bound saturated; a slot freed | `test_fs18_at_most_the_configured_number_of_requests_are_handled_at_once_and_the_next_starts_when_one_ends` (arm F6a) |
| one scope per request | `test_fs18_each_request_gets_its_own_unit_of_work` (arm F6b) |
| concurrent service of a slow and a quick request | `test_requests_are_served_concurrently_a_slow_one_does_not_hold_the_next`; real: `integration/test_stock_responder_concurrency.py` (arm H9) |

### 5.3 The relay copy — each branch of the canonical, and the Orders test that drives it

C3's parity guard makes every one of these tests binding on the copy (the copy is the canonical's text): publish then stamp only after acknowledgement `integration/test_outbox_relay.py::test_r14_stamps_a_record_only_after_the_broker_acknowledgement…`; a rejected batch stays unstamped `…::test_oi8_leaves_every_record_of_a_rejected_batch_unstamped…`; timeout `…::test_oi14_abandons_a_publish_that_exceeds_the_timeout…`; poison row, stop-on-failure `…::test_oi18_a_poison_row_blocks_at_itself…`, `…::test_oi18_a_poison_row_at_the_head…`; `send` raises and stops the batch `unit/test_kafka_fact_publisher.py::test_a_send_that_raises_stops_the_batch_and_names_that_fact_and_every_later_one`; deadlock re-run `integration/test_outbox_relay_deadlock.py::test_oi17_run_once_survives_a_constructed_deadlock_victim_and_retries_the_cycle`; the task loop `unit/test_outbox_relay_task.py` (survives a failed cycle, propagates cancellation, stop waits for the in-flight cycle, disabled returns). Fulfillment's own wiring of the copy is `integration/test_fulfillment_outbox_relay.py` (FS16) and the host's relay tests (§ 3 of the host lifespan file).

## 6. Defeat-list rows that applied

Row 1 (delete): H3a, H7b, E4c, H4a, D4d, F8a. Row 2 (corrupt a supplied field): H3b, H4b, B8c, C4a/b, H7a, G4a. Row 3 (sibling identifier): C5, F1, C6b, F8b, E3b, H4c, G3, F4c, D5b/c. Row 4 – 6 (comment, dead region, triple-quoted string): C3's sentinels (`test_sentinel_a_change_that_only_a_comment_holds_fails`, `…dead_region…`, `…hidden_in_a_triple_quoted_string…`), G5 (a read hidden in `if False:`). Row 7 (drop an optional element): C4c – e, H3c (`retailerCode`). Row 8 (literal to literal): every expected value is a test-supplied literal; B7 asserts **equality** with supplied ids, never "is a UniqueId"; the reason in B8/H7 is `order_cancelled` / `credit_rejected`, the opposite of the mutation's constant. Row 9 (stale premise): the lock waits are observed ungranted in `pg_stat_activity` (`Db.wait_for_lock_waiters`), never inferred from an earlier row. Row 10/11 do not apply beyond C3/G8. Row 12 (a path the population never drives): the release pre-read (E4b, H7), the no-carrier branch (E4c, H6), the exhausted re-run (D4a, I4), the cancellation in the back-off (D4e).

## 7. Inherited findings (`design.md` § 17)

| Finding | Disposition | Evidence |
|---|---|---|
| #8 id 49 and its follow-on (1 of 4 sites guarded) | **avoided** | B7: four arms, one per domain site, each failing at its own assertion line (400 / 403 / 411 / 434). **Round 2 (D2):** the two application sites that hand the id port to the domain (`stock_reservation.py:115` reserve, `:170` release) were unguarded (M1 survived); now `test_fs24_the_reserve_uses_the_id_port_…` and `test_fs24_the_release_uses_the_id_port_…`, arms M1a and M1b RED, so six of six sites are guarded |
| #8 id 50 (shutdown rethrew a faulted reply) | **avoided** | F7, arm F7 |
| #8 id 51 (hand-retyped payload keys / `RpcError` enum) | **avoided** | generated models; `test_fulfillment_rpc_error_retryability.py` imports Orders' set |
| #8 id 54 (un-hinted re-read correct only under a statement snapshot) | **avoided** | D5 isolation test, arms D5b/D5c |
| #8 id 79 (SA-4's one lock) | **split as designed**: release half built and guarded (FS25, arm I5), despatch half → feature 18 | I5. **Round 2 (D1, D3, D6):** the lock's existence was guarded (I5) but not the order of its two reads (R1 survived, `ConcurrentReservationChangeError` untested, M9 survived); now `test_stock_repository.py::test_fs25_the_release_lock_reads_the_orders_reservations_only_after_the_stock_lock_…` (R1 RED) and `…::test_the_release_lock_raises_concurrent_reservation_change_…` (M9 RED); I5's failure now names the claim |
| #8 id 95 (cold connection lost a reply) | **avoided** | F8 (flush), arms F8a/b |
| #8 id 101 (stock page repeats the product code) | **assigned to feature 29**, already carried: `feature_list.json` feature 29's acceptance item "inherited criteria: #8 ids 98, 100, 101, 102, 103, 106" | no edit made |
| #8 id 46, 63 | already avoided / not applicable | as the design says |
| #8 feature 17 D1 (rejected path's row never observed), D2 (released `reason` never opened) | **avoided** | H4 opens the rejected row field by field (arms H4a/b/c); H7 opens the released row and its `credit_rejected` variant (arm H7a) |
| #8 feature 17 A6 (a claim that an instrument reads the spec when it does not) | **avoided** | C5 and F1 read `asyncapi.yaml` with pyyaml; their arms substitute the sibling address |
| #7 feature 17 rejection (FS5's "any status" untested at one level) | **avoided** | E4 (unit) **and** H5 (integration), both armed by the status filter (E4a, H5a), both parametrised cases red at the unit level |
| #8 G6 (lock-order arm stayed green) | **avoided** | the per-row loop; I3's arm I3 is red |
| #8 id 56 (settings → adapter reach, recurred three times in Phase 8) | **avoided** | G4 written with the root; arms G4a/b red |

Not recurred: no inherited finding recurred. One new class appeared (§ 11, the formatter vs. the parity map).

## 8. Every `[ARM]` row

**51 of the 52 `[ARM]` rows were armed and seen red** (B2, B4, B6, B7, B8, B9, C3, C4, C5, C6, D4 – D9, E3 – E5, F1, F2, F3, F4, F6 – F9, G3 – G8, H1 – H12, I1 – I5, J1). The 52nd, **K3**, is a live-data query whose arm is its own control (§ 10): no mutation on a live database. Two rows need a statement:

- **H10** has two arms: `H10b` (units written through `update(Stock).values`) is RED; `H10a` (replenish the known lines before checking the unknown one) **stays green at the integration level, by construction**: the unknown product raises inside the transaction, so the rollback undoes whatever was applied, and the integration test cannot tell. That arm is red at the unit level, **E5** (`test_an_unknown_product_on_any_line_raises_before_anything_is_replenished`, fake repository). Recorded as an equivalent mutant at the integration level, not as a pass.
- Four arms were **superseded** because they died at an earlier assertion than the claim they were meant to arm (the rule "one mutation per claim"): B4e → B4e2, D4b → D4b2, G7a → G7a2, H1b → H1b2. Both are in the list; the superseded ones say so.

Procedure for every arm: `cp -p` of the file into the git-ignored `.arm/impl17/bak/<id>__<path with / as __>` with its `sha256` recorded below; exactly one mutation; the one named test run in its own process group (killed whole on a timeout); restore **from the backup**, `cmp` identical, `__pycache__` under `services/fulfillment/src` and `.mypy_cache` removed, the same test re-run green. 119 arm runs; 118 red, 1 (`H10a`) green as explained. The whole set was **re-run after the last code change** (L1; none followed J4) and every result below is from that re-run. The first round's results are kept in `.arm/impl17/arm_log_round1.md`. The helper is `.arm/impl17/armlib.py`; the scripts `.arm/impl17/arm_*.py`; the master runner `.arm/impl17/runall.sh`; its output `.arm/impl17/l1_run.out`.

Additional arms recorded beyond the task text: B2c/B2d (the two claims of the R35 test separately: allow exactly `released → consumed`; raise after mutating), B4e2 (R30's "changes no stock item"), C3's three sentinels per defeat row 4 – 6, C4 per event, D4 per claim, E4d/E4e (reply only after `run`; rollback not swallowed), F4a2, F6, G6b, G7a2, H3c, H5b, H7c, I1 – I5 with the construction described in the design, J1b (an `aiokafka` import in `application/stock_reservation.py`), and **J1c** (the same edit judged by `lint-imports`: `Contracts: 10 kept, 1 broken`, `otc_fulfillment.application.stock_reservation -> aiokafka (l.14)` and the chain from `otc_fulfillment.presentation.stock_rpc_errors`; backup `.arm/impl17/bak/J1c__stock_reservation.py` sha256 `feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d`, restored with `cmp`, `lint-imports` green again).

### 8.1 The arm list

The arm list is § 16 below (re-run results; backups follow the naming above); the round-2 arms are in the "Round 2" section at the end. This heading was empty in round 1 (review D7a).


## 9. Hand-over to feature 18 (`design.md` § 15) and the id 101 attachment

Delivered for feature 18: `StockItem.consume` / `Reservation.consume` (FS11, R35's `reserved → consumed` edge, tested at the domain level; **no caller exists yet**); the SA-4 lock as exactly two methods, `StockReads.stock_keys_of_order(order_reference)` (own short session, outside any transaction) and `StockRepository.lock_order_items(order_reference, keys)` (inside `run()`: the stock rows each `FOR UPDATE` in `distinct_stock_keys` order, then the order's reservations `FOR UPDATE ORDER BY id`, `ConcurrentReservationChangeError` for a reservation on an unlocked row) — `stock.release` uses exactly these two and FS25 guards the release half (arm I5); `distinct_stock_keys` in `application/ports/stock_store.py` for the despatch's own lock order; the mapper already persists a status and both counters (`apply_reservation`, `apply_item`); `PRECONDITION_FAILED` for a terminal reservation; the responder's subject table `ROUTES` (one entry adds `fulfillment.despatch.create`); `StockResponder.start()` flushes after the last subscription; `payloads.py`'s `assert_never` makes a fourth event class (`OrderDespatched`) a type error until it is mapped; the outbox writer/relay/publisher copies, parity-guarded. The pinned `READ COMMITTED` (D5's isolation arm) is what makes feature 18's in-lock re-read current (#8 id 54).

Remains for 18, as designed: the `DespatchAdvice` aggregate (F6, F7), the `DES-` allocator over `sequences.py`, the sixth subject, `NoReservedStockForDespatchError`, F8's layers, the release-versus-despatch race in both outcomes and the despatch half of FS25's lock test, the `order.despatched.v1` mapping, the R36 row. **Two small things 18 will meet:** `FulfillmentRuntime`/`composition.register_handlers` take one statement per message (the behavioural registration guard now covers Fulfillment: `tests/architecture/test_registration_behaviour.py` `TABLES["fulfillment"]` must gain the new command), and `test_composition_env_reads.py` needs no edit unless a settings class is added.

**id 101 (stock page repeats the product code)**: the attachment is **already in place**: `feature_list.json` feature 29's acceptance item "inherited criteria: #8 ids 98, 100, 101, 102, 103, 106". Nothing edited.

## 10. Live boot (FS17) — K1 – K5, also the manual test script

Preconditions: `docker compose -p otcpy -f docker-compose.infra.yml start postgres nats kafka` (the compose stack was down; only `otcpy-n8n` ran; `docker ps` before: `otcpy-n8n Up`; after the walkthrough and `stop kafka nats postgres`: `otcpy-n8n Up`, recorded in `.arm/impl17/docker_before.txt` / `docker_after.txt`). `psql` is not on the host: the queries run as `docker exec -e PGPASSWORD=… otcpy-postgres psql -U $POSTGRES_APP_USER -d <db>`. Hosts: `uv run uvicorn otc_fulfillment.main:app --port 8102` started first, then `uv run uvicorn otc_orders.main:app --port 8101`; both `/health/ready` → `{"status":"ready"}` 200.

**K1 (2026-10-08 04:45 UTC, before any host ran).** `otc_orders`: `ORD-000007`, status `placed`, one `saga_commands` row: `stock.reserve`, status `parked`, attempts 6, `next_attempt_at 2026-10-07 09:52:01.092+00`, `last_error "fulfillment.stock.reserve: no responder is subscribed to fulfillment.stock.reserve."`, payload `{"orderReference":"ORD-000007","retailerCode":"CarrefourEs","companyCode":"IBERFOODS","lines":[{"productCode":"PRD-0002","units":3},{"productCode":"PRD-0001","units":2}]}`. Precondition **met**: `otc_fulfillment.stock` holds `(IBERFOODS, PRD-0001)` units 500 / reserved 0 and `(IBERFOODS, PRD-0002)` units 495 / reserved 0. Before: 11 reservations and 12 outbox rows in `otc_fulfillment` (the seed's).

**K2 (Orders started at about 04:45:20; the sweeper re-issued the parked row at once: its `next_attempt_at` was in the past).** At 04:45:55 UTC: reservations `PRD-0001` ×2 `e0ac4713-60c7-40b7-986f-55d47c613447` and `PRD-0002` ×3 `1a1748cc-9daf-427d-871f-24dbe937a52f`, both `reserved`, `created_at 04:45:26.436`; `stock.reserved_units` PRD-0001 = 2, PRD-0002 = 3; `otc_fulfillment.outbox` seq 13 `stock.reserved.v1`, `occurred_at 04:45:26.424`, **`published_at 04:45:26.659`**, payload `{"orderReference":"ORD-000007","companyCode":"IBERFOODS","retailerCode":"CarrefourEs","reservations":[…PRD-0002 ×3, PRD-0001 ×2…]}` (line order); the `stock.reserve` row `sent`; `ORD-000007` **`stock_reserved`**; a new `credit.hold` row **`parked`** (3 attempts, `billing.credit.hold: no responder is subscribed`), as designed (Billing does not exist yet). Output in `.arm/impl17/k2_after.txt`.

**K3 (both databases).** `otc_fulfillment.outbox.correlation_id = 223c1406-1fd8-45c8-99c5-88a738720414 = otc_orders.orders.id`; `outbox.causation_id = bccaadb5-0354-4f91-b2bd-482a8ef26edb = otc_orders.saga_commands.id` of the `stock.reserve` row — digit for digit (compared in the shell, `.arm/impl17/k3.txt`). F2 on live data: the query "stock rows whose `reserved_units` ≠ the sum of their `reserved` reservations" over the two touched items returned **0 rows**; **control**: the same query with a deliberately wrong expectation (`<> 1 + coalesce(…)`) returned both rows (PRD-0001 2/2, PRD-0002 3/3), so it can report. No mutation arm on a live database (K3's arm is that control).

**K4.** A raw NATS request `orders.create` (`CarrefourEs` / `IBERFOODS`, PRD-0001 × 4) at 04:46:11 → reply `{"orderId":"b7117514-…","orderReference":"ORD-000008","status":"placed","totalAmount":99996,…}`: the first acceptance answered by a **real** `stock.check` responder in #9. Eight seconds later `ORD-000008` was `stock_reserved` with one `reserved` reservation (PRD-0001 × 4), its `stock.reserve` row `sent` and a `credit.hold` row `parked`.

**K5.** A raw `fulfillment.stock.reserve` for the throwaway `ORD-000999` **without headers** → `{"code":"VALIDATION_FAILED","message":"the x-correlation-id header is required","occurredAt":"2026-10-08T04:46:25.623Z"}`; `0` reservations for it. Both hosts were stopped by PID (`kill -TERM` of the two server processes 271327 and 271877; both logged `Application shutdown complete`); afterwards `pgrep -af "uvicorn otc_"` → none and no listener on 8101/8102 (`ss -ltn`).

**Side effect to know about:** the developer databases were changed by this walkthrough, as FS17 intends: `ORD-000007` is now `stock_reserved` (no longer parked) with 2 reservations and a published `stock.reserved.v1`; `ORD-000008` exists (`stock_reserved`); PRD-0001 has `reserved_units` 6 and PRD-0002 3. Re-running K1 – K2 on this database finds no parked row; recreate the dev database (`docker compose … down -v` and the seed) to repeat it.

## 11. Deviations from the design (argued, never silent)

1. **The parity guard also forgives the formatter's reflow (`design.md` § 10.2 names the token map alone).** `FULFILLMENT_FACTS_TOPIC` is 4 characters longer than `ORDERS_FACTS_TOPIC`; in `kafka_publisher.py` the mapped call line is 104 columns, and `ruff format --check` (a `quality.sh` gate) explodes it. A byte-identity check after the map alone would have to be failed by the formatter or defeated by a `# fmt: off`. The guard therefore compares the copy with **`ruff format` applied (with the repository's `pyproject.toml`) to the mapped canonical**, byte for byte: comments, strings, every token. A one-character edit, a comment edit, a dead `if False:` region and a triple-quoted copy of the canonical are all differences (sentinels, defeat rows 4 – 6); `test_the_reflow_the_longer_topic_name_forces_is_real_and_is_what_the_copy_holds` fails if the premise ever goes stale. The map direction is canonical → copy (the design wrote copy → canonical). Alternative considered and refused: editing Orders' canonical (`services/orders/src/**` is a must-not-touch).
2. **`ReservationSnapshot` carries `product_code`** (the design's § 5.1 lists no snapshot fields). FS5's reply names the product of every EXISTING reservation, including one on a product outside the request (D6), and the order's reservations are loaded without their item; `StockItem.rehydrate` also refuses a reservation of another product.
3. **`NoKnownStockItemError` lives in `application/stock_reservation.py` and `UnknownStockItemError` in `application/stock_replenishment.py`; `distinct_stock_keys` in `application/ports/stock_store.py`** (the design says "application" and names no module for them).
4. **`FulfillmentRuntime` exposes `engine` and `responder`** (G4 asserts `engine.pool.size()` as the task requires; the design's `FulfillmentRuntime` listed no attributes).
5. **`host_environment` depends on `kafka_server`**: `kafka_server` is a sync session fixture that calls `asyncio.run`, so it cannot be requested lazily from inside a running loop (measured: `RuntimeError: asyncio.run() cannot be called from a running event loop`). The container therefore starts once per session for any test that boots a host; with the relay off, `KAFKA_BROKERS` points at `127.0.0.1:1`, so Kafka being contacted would still fail the boot (G7 test).
6. **`services/orders/tests/integration/conftest.py` gained a `NatsServerShape` Protocol** and its three `NatsServer` annotations were renamed (a conftest module is not importable under `--import-mode=importlib`, so the moved class cannot be named there; `KafkaServerShape` is the precedent). The moved fixture's docstring sentence "it lives in this conftest, not the repository root one…" was reworded (it would otherwise be false in the root file); the body is unchanged. Orders' 992 tests passed before and after.
7. **`presentation/app.py` no longer defines a module-level `app`** (Orders' shape; `main.py` owns the app). The existing health test uses `create_app()`.
8. **`requirements.md` § 3**: besides the status cells, FS17's cell now points at `tasks.md` group **K** (it said group I; group K is the live walkthrough).
9. **H10's first arm is an equivalent mutant at the integration level** (§ 8): the claim is armed at E5 instead.
10. **The `already_released` reply for R34** (reservations exist, all `released`) is `outcome: already_released` with `released: []`, the same shape as FS9's: the asyncapi text says "success no-op"; both predecessors answer the same.

## 12. L5 — every modified and untracked path against the file list

Modified (all in the task's "may touch" list): `.env.example`; `conftest.py` (NatsServer moved); `services/fulfillment/pyproject.toml`; `uv.lock`; `services/fulfillment/src/otc_fulfillment/infrastructure/settings.py`; `…/presentation/app.py`; `services/fulfillment/tests/integration/conftest.py`; `services/orders/tests/integration/conftest.py` (the copy deleted; deviation 6); `specs/shared/test-matrix.md` (column 5 of R30 – R35, R61, the Feature-4 and Total rows only); `tests/architecture/test_{composition_env_reads,kafka_client_confinement,registration_behaviour,write_path_population}.py`. Modified before this task started, not touched by me: `feature_list.json` (now also feature 17's status line, L6), `progress/current.md`. Untracked and new, all in the list: everything under `services/fulfillment/src/otc_fulfillment/` and `services/fulfillment/tests/` named in § 1, `tests/architecture/test_outbox_copy_parity.py`, `tests/architecture/test_fulfillment_rpc_error_retryability.py`, `specs/fulfillment_stock/` (the approved spec; my edits: tick marks in `tasks.md`, § 3 status cells in `requirements.md`), and `progress/impl_fulfillment_stock.md`. Untracked and not mine: `progress/brief_*.md`, `progress/premise_*.md`. Package markers not named in the list but required by it: `application/ports/__init__.py`, `infrastructure/messaging/__init__.py`, `infrastructure/outbox/__init__.py`. Nothing under `services/orders/src`, `packages/`, other services, root `pyproject.toml`, `alembic/`, `models.py`, `range_guards.py`, `types.py`, `sequences.py` or `progress/current.md` was touched (`git status` lists none of them).

## 13. L2 — deadlock watch

`grep -n "40P01\|deadlock victim\|re-running" .arm/impl17/j4.log` → **no hits**, but pytest hides the logs of passing tests, so that grep proves nothing by itself. The instrument was therefore re-run with the log shown: `uv run pytest services/fulfillment -o log_cli=true -o log_cli_level=WARNING` (340 passed, 41 s; output `.arm/impl17/l2_full.log`) and searched. Hits and classification:

| line | record | classification |
|---|---|---|
| 68 | `deadlock victim (SQLSTATE 40P01); re-running it` after `test_fs23_a_real_40p01_on_a_reserve_is_rerun…` | **expected**: I4's real `40P01`, exactly one |
| 705, 706, 707 | the same warning ×3 under `test_fs23_a_deadlock_victim_is_rerun_at_most_three_times…` | **expected**: D4 (two re-runs of the exhausted run + one of the survivor) |
| 720 | the same warning under `test_a_cancellation_during_the_backoff…` | **expected**: D4 |
| 726 | the same warning under `test_each_attempt_gets_its_own_session_and_transaction` | **expected**: D4 |
| 667, 686 | `fulfillment.stock.replenish / reserve refused: UNAVAILABLE the stock store is temporarily unavailable (40P01)` | **not a deadlock**: the responder unit tests inject `StoreUnavailableError("40P01")` to prove the mapping |

No hit under I3 (`test_fs19_two_multi_line_reserves…`), which is the point: correct code produces zero re-run warnings; its arm I3 produces one. No hit anywhere else; in particular no real deadlock in any H or I test.

## 14. What surprised me

- **Stale line citations** in the spec (§ 2): two Orders files cited past their end.
- **asyncpg's `UUID` subclass** failed `UniqueId`'s `type(...) is uuid.UUID` on the first integration run (Orders' mapper already rebuilds a plain `UUID`; the Fulfillment mapper does the same).
- **Rows written in one `save()` share one timestamp**, so `ORDER BY created_at` is no order; the reply lists references in **line order** and an `already_reserved` reply in **id order** (FS5 asks for the existing rows, not an order); the tests compare accordingly.
- **A raise inside `run()` makes a "partial application" invisible to an integration test** (H10a): the transaction is the second line of defence, so the first (check before apply) needs the fake-repository unit test (E5).
- **`kafka_server` cannot be requested lazily** (deviation 5).
- **The sweeper re-issued the parked row within seconds of Orders starting**, so K2 needed no waiting for `next_attempt_at`.
- **aiokafka's `partitions_for_topic` right after `start()` can be empty**; the relay test reads partitions from the admin client, as Orders' `read_topic` does.

## 15. Not done / open

Nothing in `tasks.md` is unticked. Not done by design: R36 and R61's API half (features 18 and 31); the G1 residual (concurrent reserves for one order naming **disjoint** product sets) is accepted by the gate and has no guard.

### 15.1 Task rows without a `[ARM]` mark that nevertheless make a countable claim (armed, as the header requires)

C6's "`published_at` is set only after the run" is asserted in the test (null before `run_once()`, set after) but has no arm of its own: the stamp-after-acknowledgement ordering is the canonical relay's, proven once by Orders' `test_r14_stamps_a_record_only_after_the_broker_acknowledgement…` and made binding on the copy by C3's parity guard (arm C3a/C3b). I did not mutate the copy's relay for it, because any such edit is a parity failure first.

## 16. The arm list

Naming of the backups: `.arm/impl17/bak/<id>__<repo path with "/" replaced by "__">`; each id is a heading below. "failure" is verbatim from the re-run (assertion lines of the test, abbreviated to 170 columns; the full outputs are `.arm/impl17/logs/<id>.red.txt`).

- **B2a** — RED (exit 1); cmp identical; re-run green; sha256 f4f4b0093e02b4c277639f040653bedf6554f0bca1d6a4dddf61a9e055dd279e
  - mutation: `'if self._status is not ReservationStatus.RESERVED:\n            raise ReservationTerminalError(self._status.value, target.value)'` -> `'if self._status is ReservationStatus.CONSUMED:\n            ra
  - test: `…/unit/domain/test_reservation.py::test_r35_refuses_every_transition_out_of_released_and_out_of_consumed_and_changes_nothing`
  - failure: services/fulfillment/tests/unit/domain/test_reservation.py:92: in test_r35_refuses_every_transition_out_of_released_and_out_of_consumed_and_changes_nothing ⏎ E   Failed: DID NOT RAISE ReservationTerminalError
- **B2b** — RED (exit 1); cmp identical; re-run green; sha256 f4f4b0093e02b4c277639f040653bedf6554f0bca1d6a4dddf61a9e055dd279e
  - mutation: `'if type(token) is not str or token not in _BY_TOKEN:\n        raise UnknownReservationStatusError(token)\n    return _BY_TOKEN[token]'` -> `'if type(token) is not str or token.strip().lower() not in
  - test: `…/unit/domain/test_reservation.py::test_parse_reservation_status_is_exact_and_refuses_everything_outside_the_closed_set`
  - failure: services/fulfillment/tests/unit/domain/test_reservation.py:116: in test_parse_reservation_status_is_exact_and_refuses_everything_outside_the_closed_set ⏎ E   Failed: DID NOT RAISE UnknownReservationStatusError
- **B2c** — RED (exit 1); cmp identical; re-run green; sha256 f4f4b0093e02b4c277639f040653bedf6554f0bca1d6a4dddf61a9e055dd279e
  - mutation: `'def consume(self) -> None:\n        self._move_to(ReservationStatus.CONSUMED)'` -> `'def consume(self) -> None:\n        if self._status is ReservationStatus.RELEASED:\n            self._status = Re
  - test: `…/unit/domain/test_reservation.py::test_r35_refuses_every_transition_out_of_released_and_out_of_consumed_and_changes_nothing`
  - failure: services/fulfillment/tests/unit/domain/test_reservation.py:92: in test_r35_refuses_every_transition_out_of_released_and_out_of_consumed_and_changes_nothing ⏎ E   Failed: DID NOT RAISE ReservationTerminalError
- **B2d** — RED (exit 1); cmp identical; re-run green; sha256 f4f4b0093e02b4c277639f040653bedf6554f0bca1d6a4dddf61a9e055dd279e
  - mutation: `'if self._status is not ReservationStatus.RESERVED:\n            raise ReservationTerminalError(self._status.value, target.value)\n        self._status = target'` -> `'previous = self._status\n      
  - test: `…/unit/domain/test_reservation.py::test_r35_refuses_every_transition_out_of_released_and_out_of_consumed_and_changes_nothing`
  - failure: services/fulfillment/tests/unit/domain/test_reservation.py:96: in test_r35_refuses_every_transition_out_of_released_and_out_of_consumed_and_changes_nothing ⏎ E   AssertionError: a refused transition must change nothing ⏎ E   assert ReservationVi...: 'released'>) == ReservationVi...: 'consumed'>)
- **B4a-boundary** — RED (exit 1); cmp identical; re-run green; sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc
  - mutation: `'if units.value > self.available_units:'` -> `'if units.value >= self.available_units:'` 
  - test: `…/unit/domain/test_stock_item.py::test_r30_rejects_in_full_any_operation_that_would_push_reserved_units_above_units_and_changes_no_stock_item`
  - failure: services/fulfillment/tests/unit/domain/test_stock_item.py:53: in test_r30_rejects_in_full_any_operation_that_would_push_reserved_units_above_units_and_changes_no_stock_it ⏎ services/fulfillment/src/otc_fulfillment/domain/stock_item.py:156: in reserve ⏎ E   otc_fulfillment.domain.errors.InsufficientStockError: 6 unit(s) of 'PRD-A1' were requested but only 6 are available.
- **B4b-fs10-release-before-check** — RED (exit 1); cmp identical; re-run green; sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc
  - mutation: `'mine = [r for r in self._reservations if r.order_reference == order_reference]\n        if any(r.status is ReservationStatus.CONSUMED for r in mine):\n            raise ReservationTerminalError(\n  
  - test: `…/unit/domain/test_stock_item.py::test_fs10_refuses_to_release_a_consumed_reservation_and_changes_nothing`
  - failure: services/fulfillment/tests/unit/domain/test_stock_item.py:158: in test_fs10_refuses_to_release_a_consumed_reservation_and_changes_nothing ⏎ E   AssertionError: the `reserved` row must not have been released ⏎ E   assert StockItemSnap...'consumed'>))) == StockItemSnap...'consumed'>)))
- **B4c-consume-keeps-units** — RED (exit 1); cmp identical; re-run green; sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc
  - mutation: `'self._units = self._units - total\n        self._reserved_units = self._reserved_units - total\n        return tuple(moving)'` -> `'self._reserved_units = self._reserved_units - total\n        retur
  - test: `…/unit/domain/test_stock_item.py::test_fs11_consume_moves_the_orders_reservations_to_consumed_decreases_units_and_reserved_units_by_the_same_total_and_appends_no_event`
  - failure: services/fulfillment/tests/unit/domain/test_stock_item.py:180: in test_fs11_consume_moves_the_orders_reservations_to_consumed_decreases_units_and_reserved_units_by_the_sa ⏎ E   assert (20, 5) == (13, 5) ⏎ E     
- **B4d-release-forgets-to-subtract** — RED (exit 1); cmp identical; re-run green; sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc
  - mutation: `'self._reserved_units = self._reserved_units - total\n        return tuple(moving)\n\n    def consume'` -> `'return tuple(moving)\n\n    def consume'` 
  - test: `…/unit/domain/test_stock_item.py::test_fs12_rehydrates_and_keeps_reserved_units_equal_to_the_sum_of_reserved_reservations_after_reserve_release_and_consume`
  - failure: services/fulfillment/tests/unit/domain/test_stock_item.py:215: in test_fs12_rehydrates_and_keeps_reserved_units_equal_to_the_sum_of_reserved_reservations_after_reserve_re ⏎ E   assert 13 == 6 ⏎ E    +  where 13 = <otc_fulfillment.domain.stock_item.StockItem object at 0x73d33a1e4a00>.reserved_units
- **B4e2-r30-mutates-before-refusing** — RED (exit 1); cmp identical; re-run green; sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc
  - mutation: `'if units.value > self.available_units:\n            raise InsufficientStockError(self._product_code, units.value, self.available_units)\n        reservation = Reservation.create(\n            reserv
  - test: `…/unit/domain/test_stock_item.py::test_r30_rejects_in_full_any_operation_that_would_push_reserved_units_above_units_and_changes_no_stock_item`
  - failure: services/fulfillment/tests/unit/domain/test_stock_item.py:48: in test_r30_rejects_in_full_any_operation_that_would_push_reserved_units_above_units_and_changes_no_stock_it ⏎ E   AssertionError: assert StockItemSnap...reserved'>),)) == StockItemSnap...servations=()) ⏎ E     
- **B4e-r30-mutates-before-refusing** — RED (exit 1); cmp identical; re-run green (superseded by B4e2 (its error numbers died at an earlier assertion than the claim)); sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc
  - mutation: `'if units.value > self.available_units:\n            raise InsufficientStockError(self._product_code, units.value, self.available_units)\n        reservation = Reservation.create(\n            reserv
  - test: `…/unit/domain/test_stock_item.py::test_r30_rejects_in_full_any_operation_that_would_push_reserved_units_above_units_and_changes_no_stock_item`
  - failure: services/fulfillment/tests/unit/domain/test_stock_item.py:47: in test_r30_rejects_in_full_any_operation_that_would_push_reserved_units_above_units_and_changes_no_stock_it ⏎ E   assert (7, -1) == (7, 6) ⏎ E     
- **B6a-partial-reservation** — RED (exit 1); cmp identical; re-run green; sha256 2e52e55f047c876ecdde0d7163a325c53cd0ee4aeb144719fae2fea9976b954d
  - mutation: `"['    if shortages:\\n        reason =', '        elif units > item.available_units:\\n            shortages.append(', '    for line in request.lines:\\n        reservation = items[line.product_code
  - test: `…/unit/domain/test_reservation.py::test_r33_creates_no_reservation_at_all_and_emits_stock_rejected_v1_naming_requested_and_available_units_when_one_line_is_short`
  - failure: services/fulfillment/tests/unit/domain/test_reservation.py:187: in test_r33_creates_no_reservation_at_all_and_emits_stock_rejected_v1_naming_requested_and_available_units ⏎ E   AssertionError: assert Reserved(reservations=(ReservationRef(reservation_id=UniqueId(value=UUID('00000000-0000-4000-8000-000000000900')), pro...ationRef(reservation_i ⏎ E    +  where Rejected(shortages=(Shortage(product_code='PRD-C3', requested=7, available=5),), reason=<RejectionReason.INSUFFICIENT_STOCK: 'insufficient_stock'>) = Reject
- **B6b-reason-precedence** — RED (exit 1); cmp identical; re-run green; sha256 2e52e55f047c876ecdde0d7163a325c53cd0ee4aeb144719fae2fea9976b954d
  - mutation: `"['        reason = RejectionReason.UNKNOWN_PRODUCT if unknown else RejectionReason.INSUFFICIENT_STOCK', '    unknown = False\\n', '        elif units > item.available_units:\\n']"` -> `"['        re
  - test: `…/unit/domain/test_reservation.py::test_fs8_rejects_the_whole_order_with_reason_unknown_product_and_available_zero_when_any_line_names_an_unstocked_product`
  - failure: services/fulfillment/tests/unit/domain/test_reservation.py:267: in test_fs8_rejects_the_whole_order_with_reason_unknown_product_and_available_zero_when_any_line_names_an_ ⏎ E   AssertionError: assert <RejectionReason.INSUFFICIENT_STOCK: 'insufficient_stock'> is <RejectionReason.UNKNOWN_PRODUCT: 'unknown_product'> ⏎ E    +  where <RejectionReason.INSUFFICIENT_STOCK: 'insufficient_stock'> = Rejected(shortages=(Shortage(product_code='PRD-B2', requested=9, available=1), Shortage(product
- **B6c-carrier-last-known-line** — RED (exit 1); cmp identical; re-run green; sha256 2e52e55f047c876ecdde0d7163a325c53cd0ee4aeb144719fae2fea9976b954d
  - mutation: `'for ln in request.lines if ln.product_code in items)'` -> `'for ln in reversed(request.lines) if ln.product_code in items)'` (carrier = last known line)
  - test: `…/unit/domain/test_reservation.py::test_fs13_stamps_the_first_known_lines_item_on_reserved_and_rejected_and_the_first_released_reservations_item_on_released`
  - failure: services/fulfillment/tests/unit/domain/test_reservation.py:302: in test_fs13_stamps_the_first_known_lines_item_on_reserved_and_rejected_and_the_first_released_reservation ⏎ E   ValueError: not enough values to unpack (expected 1, got 0)
- **B6d-satisfiable-listed-too** — RED (exit 1); cmp identical; re-run green; sha256 2e52e55f047c876ecdde0d7163a325c53cd0ee4aeb144719fae2fea9976b954d
  - mutation: `'if shortages:\n        reason ='` -> `'if shortages:\n        shortages = [Shortage(product_code=p, requested=u, available=(items[p].available_units if p in items else 0)) for p, u in requested.item
  - test: `…/unit/domain/test_reservation.py::test_r33_creates_no_reservation_at_all_and_emits_stock_rejected_v1_naming_requested_and_available_units_when_one_line_is_short`
  - failure: services/fulfillment/tests/unit/domain/test_reservation.py:187: in test_r33_creates_no_reservation_at_all_and_emits_stock_rejected_v1_naming_requested_and_available_units ⏎ E   AssertionError: assert Rejected(shor...cient_stock'>) == Rejected(shor...cient_stock'>) ⏎ E     
- **B7a-reservation-id-site** — RED (exit 1); cmp identical; re-run green; sha256 2e52e55f047c876ecdde0d7163a325c53cd0ee4aeb144719fae2fea9976b954d
  - mutation: `'reservation_id=new_id(),'` -> `'reservation_id=UniqueId.new(),'` (site 1: reservation id)
  - test: `…/unit/domain/test_reservation.py::test_fs24_every_reservation_id_and_fact_event_id_is_the_one_the_id_source_supplied`
  - failure: services/fulfillment/tests/unit/domain/test_reservation.py:400: in test_fs24_every_reservation_id_and_fact_event_id_is_the_one_the_id_source_supplied ⏎ E   AssertionError: a reservation id was not the supplied one ⏎ E   assert [UniqueId(val...779279af80'))] == [UniqueId(val...0000006002'))]
- **B7b-reserved-fact-site** — RED (exit 1); cmp identical; re-run green; sha256 2e52e55f047c876ecdde0d7163a325c53cd0ee4aeb144719fae2fea9976b954d
  - mutation: `'event_id=new_id(),'` -> `'event_id=UniqueId.new(),'` (site 2: StockReserved, the second event_id=new_id() in the file)
  - test: `…/unit/domain/test_reservation.py::test_fs24_every_reservation_id_and_fact_event_id_is_the_one_the_id_source_supplied`
  - failure: services/fulfillment/tests/unit/domain/test_reservation.py:403: in test_fs24_every_reservation_id_and_fact_event_id_is_the_one_the_id_source_supplied ⏎ E   AssertionError: the reserved fact's event id was not the supplied one ⏎ E   assert UniqueId(valu...cadfd22695d')) == UniqueId(valu...00000006003'))
- **B7c-rejected-fact-site** — RED (exit 1); cmp identical; re-run green; sha256 2e52e55f047c876ecdde0d7163a325c53cd0ee4aeb144719fae2fea9976b954d
  - mutation: `'event_id=new_id(),'` -> `'event_id=UniqueId.new(),'` (site 3: StockRejected, the first)
  - test: `…/unit/domain/test_reservation.py::test_fs24_every_reservation_id_and_fact_event_id_is_the_one_the_id_source_supplied`
  - failure: services/fulfillment/tests/unit/domain/test_reservation.py:411: in test_fs24_every_reservation_id_and_fact_event_id_is_the_one_the_id_source_supplied ⏎ E   AssertionError: the rejected fact's event id was not the supplied one ⏎ E   assert UniqueId(valu...4d20990a84d')) == UniqueId(valu...00000006101'))
- **B7d-released-fact-site** — RED (exit 1); cmp identical; re-run green; sha256 2e52e55f047c876ecdde0d7163a325c53cd0ee4aeb144719fae2fea9976b954d
  - mutation: `'event_id=new_id(),'` -> `'event_id=UniqueId.new(),'` (site 4: StockReleased, the third)
  - test: `…/unit/domain/test_reservation.py::test_fs24_every_reservation_id_and_fact_event_id_is_the_one_the_id_source_supplied`
  - failure: services/fulfillment/tests/unit/domain/test_reservation.py:434: in test_fs24_every_reservation_id_and_fact_event_id_is_the_one_the_id_source_supplied ⏎ E   AssertionError: the released fact's event id was not the supplied one ⏎ E   assert UniqueId(valu...ae8d15740ba')) == UniqueId(valu...00000006201'))
- **B8a-f5-emits-on-all-released** — RED (exit 1); cmp identical; re-run green; sha256 2e52e55f047c876ecdde0d7163a325c53cd0ee4aeb144719fae2fea9976b954d
  - mutation: `'if carrier is None or retailer_code is None:\n        return AlreadyReleased()'` -> `'if carrier is None or retailer_code is None:\n        items[0].record_order_fact(\n            StockReleased(\n 
  - test: `…/unit/domain/test_reservation_release.py::test_f5_releasing_an_order_whose_reservations_are_all_released_changes_nothing_and_emits_nothing`
  - failure: services/fulfillment/tests/unit/domain/test_reservation_release.py:108: in test_f5_releasing_an_order_whose_reservations_are_all_released_changes_nothing_and_emits_nothin ⏎ E   AssertionError: assert (StockRelease..._rejected'>),) == () ⏎ E     
- **B8b-replenish-appends-event** — RED (exit 1); cmp identical; re-run green; sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc
  - mutation: `'self._units = self._units + quantity.value'` -> `"self._units = self._units + quantity.value\n        self._raise_event('replenished')"` (R61 suppression)
  - test: `…/unit/domain/test_stock_replenishment.py::test_r61_increases_units_by_the_requested_quantity_leaves_reserved_units_and_every_reservation_unchanged_and_appends_no_domain_event`
  - failure: services/fulfillment/tests/unit/domain/test_stock_replenishment.py:32: in test_r61_increases_units_by_the_requested_quantity_leaves_reserved_units_and_every_reservation_u ⏎ E   AssertionError: assert ('replenished',) == () ⏎ E     
- **B8c-reason-from-constant** — RED (exit 1); cmp identical; re-run green; sha256 2e52e55f047c876ecdde0d7163a325c53cd0ee4aeb144719fae2fea9976b954d
  - mutation: `'reason=request.reason,\n        )\n    )\n    return Released'` -> `'reason=ReleaseReason.CREDIT_REJECTED,\n        )\n    )\n    return Released'` (reason from a constant; the test's reason is orde
  - test: `…/unit/domain/test_reservation_release.py::test_r34_releases_the_reservations_decreases_reserved_units_and_emits_exactly_one_stock_released_v1`
  - failure: services/fulfillment/tests/unit/domain/test_reservation_release.py:76: in test_r34_releases_the_reservations_decreases_reserved_units_and_emits_exactly_one_stock_released ⏎ E   AssertionError: assert <ReleaseReason.CREDIT_REJECTED: 'credit_rejected'> is <ReleaseReason.ORDER_CANCELLED: 'order_cancelled'> ⏎ E    +  where <ReleaseReason.CREDIT_REJECTED: 'credit_rejected'> = StockReleased(event_id=UniqueId(value=UUID('00000000-0000-4000-8000-00000000005e')), aggregate_id=Uniqu
- **B9-sqlalchemy-in-a-domain-test** — RED (exit 1); cmp identical; re-run green; sha256 838592dcab25deb9ccdfdd92bbddfd39c9cc8407b2baa2dd91c44ad88949c06d
  - mutation: `'from collections.abc import Callable'` -> `'import sqlalchemy  # noqa: F401\nfrom collections.abc import Callable'` 
  - test: `…/unit/domain/test_domain_tests_are_pure.py::test_domain_unit_tests_import_only_pytest_the_standard_library_the_kernel_and_the_fulfillment_domain`
  - failure: services/fulfillment/tests/unit/domain/test_domain_tests_are_pure.py:45: in test_domain_unit_tests_import_only_pytest_the_standard_library_the_kernel_and_the_fulfillment_ ⏎ E   AssertionError: domain unit tests may not import: {'test_reservation_release.py': ['sqlalchemy']} ⏎ E   assert not {'test_reservation_release.py': ['sqlalchemy']}
- **C3a-deadlock-attempts** — RED (exit 1); cmp identical; re-run green; sha256 71ca0ad1c94c2842712412f2b00ae518b9669d0a38742d946ce6a588b1c76b64
  - mutation: `'DEADLOCK_ATTEMPTS = 3'` -> `'DEADLOCK_ATTEMPTS = 1'` (Fulfillment relay copy)
  - test: `tests/architecture/test_outbox_copy_parity.py::test_every_listed_module_is_a_faithful_copy_of_its_canonical`
  - failure: tests/architecture/test_outbox_copy_parity.py:154: in test_every_listed_module_is_a_faithful_copy_of_its_canonical ⏎ E   assert ["infrastruct...TEMPTS = 1']"] == [] ⏎ E     
- **C3b-writer-flush** — RED (exit 1); cmp identical; re-run green; sha256 11ee0947f1344faf8a2054f5dc1af6b041f7570c396adbbf277a7ccceef5eb8e
  - mutation: `'await session.flush()'` -> `''` (L9: the per-row flush deleted from the writer copy; the failure must name writer.py)
  - test: `tests/architecture/test_outbox_copy_parity.py::test_every_listed_module_is_a_faithful_copy_of_its_canonical`
  - failure: tests/architecture/test_outbox_copy_parity.py:154: in test_every_listed_module_is_a_faithful_copy_of_its_canonical ⏎ E   assert ["infrastruct...on.flush()']"] == [] ⏎ E     
- **C4a-rejected-reason-constant** — RED (exit 1); cmp identical; re-run green; sha256 f577efe4033f8c00afca1f10a647bc4bcc0ffda1a68191dc849b773f4b1a28d4
  - mutation: `'reason=asyncapi.Reason(event.reason.value),'` -> `'reason=asyncapi.Reason.unknown_product,'` (reason from a constant)
  - test: `…/unit/test_outbox_payloads.py::test_c4_stock_rejected_becomes_its_payload_with_every_field_equal_to_the_supplied_value`
  - failure: services/fulfillment/tests/unit/test_outbox_payloads.py:167: in test_c4_stock_rejected_becomes_its_payload_with_every_field_equal_to_the_supplied_value ⏎ E   AssertionError: assert {'orderRefere...le': 0}], ...} == {'orderRefere...le': 0}], ...} ⏎ E     
- **C4b-released-reason-constant** — RED (exit 1); cmp identical; re-run green; sha256 f577efe4033f8c00afca1f10a647bc4bcc0ffda1a68191dc849b773f4b1a28d4
  - mutation: `'reason=asyncapi.Reason1(event.reason.value),'` -> `'reason=asyncapi.Reason1.order_cancelled,'` (reason from a constant; the order_cancelled parameter passes, the credit_rejected one is the failing c
  - test: `…/unit/test_outbox_payloads.py::test_c4_stock_released_becomes_its_payload_with_every_field_equal_to_the_supplied_value`
  - failure: services/fulfillment/tests/unit/test_outbox_payloads.py:193: in test_c4_stock_released_becomes_its_payload_with_every_field_equal_to_the_supplied_value ⏎ E   AssertionError: assert {'orderRefere...ts': 5}], ...} == {'orderRefere...ts': 5}], ...} ⏎ E     
- **C4c-reserved-drops-retailer** — RED (exit 1); cmp identical; re-run green; sha256 f577efe4033f8c00afca1f10a647bc4bcc0ffda1a68191dc849b773f4b1a28d4
  - mutation: `'retailer_code=event.retailer_code,\n        reservations='` -> `'reservations='` (row 7)
  - test: `…/unit/test_outbox_payloads.py::test_c4_stock_reserved_becomes_its_payload_with_every_field_equal_to_the_supplied_value`
  - failure: services/fulfillment/tests/unit/test_outbox_payloads.py:144: in test_c4_stock_reserved_becomes_its_payload_with_every_field_equal_to_the_supplied_value ⏎ E   AssertionError: assert {'orderRefere... 'units': 5}]} == {'orderRefere... 'units': 5}]} ⏎ E     
- **C4d-rejected-drops-retailer** — RED (exit 1); cmp identical; re-run green; sha256 f577efe4033f8c00afca1f10a647bc4bcc0ffda1a68191dc849b773f4b1a28d4
  - mutation: `'retailer_code=event.retailer_code,\n        shortages='` -> `'shortages='` (row 7)
  - test: `…/unit/test_outbox_payloads.py::test_c4_stock_rejected_becomes_its_payload_with_every_field_equal_to_the_supplied_value`
  - failure: services/fulfillment/tests/unit/test_outbox_payloads.py:167: in test_c4_stock_rejected_becomes_its_payload_with_every_field_equal_to_the_supplied_value ⏎ E   AssertionError: assert {'orderRefere...nown_product'} == {'orderRefere...le': 0}], ...} ⏎ E     
- **C4e-released-drops-retailer** — RED (exit 1); cmp identical; re-run green; sha256 f577efe4033f8c00afca1f10a647bc4bcc0ffda1a68191dc849b773f4b1a28d4
  - mutation: `'retailer_code=event.retailer_code,\n        released='` -> `'released='` (row 7)
  - test: `…/unit/test_outbox_payloads.py::test_c4_stock_released_becomes_its_payload_with_every_field_equal_to_the_supplied_value`
  - failure: services/fulfillment/tests/unit/test_outbox_payloads.py:193: in test_c4_stock_released_becomes_its_payload_with_every_field_equal_to_the_supplied_value ⏎ E   AssertionError: assert {'orderRefere...er_cancelled'} == {'orderRefere...ts': 5}], ...} ⏎ E     
- **C5-topic-sibling-dlq** — RED (exit 1); cmp identical; re-run green; sha256 37878b84955469e02cf68cb1a36c0809b2a7a511737aa6314b14c78e9468335e
  - mutation: `'"otc.fulfillment.facts.v1"'` -> `'"otc.fulfillment.facts.v1.dlq"'` (sibling substitution: the DLQ topic)
  - test: `…/unit/test_fact_topic.py::test_c5_the_fulfillment_topic_is_the_kafka_binding_of_the_fulfillment_facts_channel`
  - failure: services/fulfillment/tests/unit/test_fact_topic.py:22: in test_c5_the_fulfillment_topic_is_the_kafka_binding_of_the_fulfillment_facts_channel ⏎ E   AssertionError: channel fulfillmentFacts: the topic the outbox publishes to is not the spec's ⏎ E   assert 'otc.fulfillment.facts.v1' == 'otc.fulfillment.facts.v1.dlq'
- **F1-release-subject-is-the-reserve-sibling** — RED (exit 1); cmp identical; re-run green; sha256 184201fda2b2f6a6b029a785345982eb67a1ea87dc4f3badf49b591042b20647
  - mutation: `'STOCK_RELEASE_SUBJECT = "fulfillment.stock.release"'` -> `'STOCK_RELEASE_SUBJECT = "fulfillment.stock.reserve"'` (sibling substitution; the failure must name the release channel)
  - test: `…/unit/test_stock_subjects.py::test_f1_each_of_the_five_subjects_is_the_address_of_its_asyncapi_channel`
  - failure: services/fulfillment/tests/unit/test_stock_subjects.py:43: in test_f1_each_of_the_five_subjects_is_the_address_of_its_asyncapi_channel ⏎ E   AssertionError: channel stockRelease: the subject Fulfillment answers is not the spec's address ⏎ E   assert 'fulfillment.stock.release' == 'fulfillment.stock.reserve'
- **D4a-one-attempt** — RED (exit 1); cmp identical; re-run green; sha256 34f9bd11c09570624aebf99de9f754f3baa2729e80db7cfad7b09688b70cf0b3
  - mutation: `"DEADLOCK_ATTEMPTS = 3  # total attempts, the relay's"` -> `"DEADLOCK_ATTEMPTS = 1  # total attempts, the relay's"` (DEADLOCK_ATTEMPTS = 1)
  - test: `…/unit/test_stock_transactions.py::test_fs23_a_deadlock_victim_is_rerun_at_most_three_times_paced_by_200_ms_then_unavailable`
  - failure: services/fulfillment/tests/unit/test_stock_transactions.py:125: in test_fs23_a_deadlock_victim_is_rerun_at_most_three_times_paced_by_200_ms_then_unavailable ⏎ E   AssertionError: three attempts in total ⏎ E   assert 1 == 3
- **D4b-four-attempts** — RED (exit 1); cmp identical; re-run green (superseded by D4b2 (it died at an IndexError of the fake, not at an assertion)); sha256 34f9bd11c09570624aebf99de9f754f3baa2729e80db7cfad7b09688b70cf0b3
  - mutation: `"DEADLOCK_ATTEMPTS = 3  # total attempts, the relay's"` -> `"DEADLOCK_ATTEMPTS = 4  # total attempts, the relay's"` (DEADLOCK_ATTEMPTS = 4: 'at most three')
  - test: `…/unit/test_stock_transactions.py::test_fs23_a_deadlock_victim_is_rerun_at_most_three_times_paced_by_200_ms_then_unavailable`
  - failure: services/fulfillment/tests/unit/test_stock_transactions.py:123: in test_fs23_a_deadlock_victim_is_rerun_at_most_three_times_paced_by_200_ms_then_unavailable ⏎ services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py:94: in run ⏎ services/fulfillment/tests/unit/test_stock_transactions.py:101: in work
- **D4c-rerun-on-40001** — RED (exit 1); cmp identical; re-run green; sha256 34f9bd11c09570624aebf99de9f754f3baa2729e80db7cfad7b09688b70cf0b3
  - mutation: `'if state == DEADLOCK_DETECTED and attempt < DEADLOCK_ATTEMPTS:'` -> `'if state in (DEADLOCK_DETECTED, "40001") and attempt < DEADLOCK_ATTEMPTS:'` (re-run on 40001)
  - test: `…/unit/test_stock_transactions.py::test_fs23_no_other_store_failure_is_rerun`
  - failure: services/fulfillment/tests/unit/test_stock_transactions.py:146: in test_fs23_no_other_store_failure_is_rerun ⏎ E   Failed: DID NOT RAISE StoreUnavailableError
- **D4d-no-sleep** — RED (exit 1); cmp identical; re-run green; sha256 34f9bd11c09570624aebf99de9f754f3baa2729e80db7cfad7b09688b70cf0b3
  - mutation: `'await self._sleep(DEADLOCK_BACKOFF_SECONDS)'` -> `''` (remove the sleep: zero recorded sleeps)
  - test: `…/unit/test_stock_transactions.py::test_fs23_a_deadlock_victim_is_rerun_at_most_three_times_paced_by_200_ms_then_unavailable`
  - failure: services/fulfillment/tests/unit/test_stock_transactions.py:127: in test_fs23_a_deadlock_victim_is_rerun_at_most_three_times_paced_by_200_ms_then_unavailable ⏎ E   assert [] == [0.2, 0.2] ⏎ E     
- **D4e-swallow-cancel-in-backoff** — RED (exit 1); cmp identical; re-run green; sha256 34f9bd11c09570624aebf99de9f754f3baa2729e80db7cfad7b09688b70cf0b3
  - mutation: `'await self._sleep(DEADLOCK_BACKOFF_SECONDS)'` -> `'try:\n                        await self._sleep(DEADLOCK_BACKOFF_SECONDS)\n                    except BaseException:\n                        pass'
  - test: `…/unit/test_stock_transactions.py::test_a_cancellation_during_the_backoff_propagates_and_runs_no_further_attempt`
  - failure: services/fulfillment/tests/unit/test_stock_transactions.py:213: in test_a_cancellation_during_the_backoff_propagates_and_runs_no_further_attempt ⏎ E   Failed: DID NOT RAISE CancelledError
- **D4f-clear-before-commit** — RED (exit 1); cmp identical; re-run green; sha256 34f9bd11c09570624aebf99de9f754f3baa2729e80db7cfad7b09688b70cf0b3
  - mutation: `'result = await work(SqlAlchemyStockTransaction(repository))\n                # the commit has returned: only now may the aggregates forget their events\n                repository.clear_saved_events
  - test: `…/unit/test_stock_transactions.py::test_events_are_cleared_only_after_the_commit_returns`
  - failure: services/fulfillment/tests/unit/test_stock_transactions.py:224: in test_events_are_cleared_only_after_the_commit_returns ⏎ E   AssertionError: assert 4 < 3 ⏎ E    +  where 4 = <built-in method index of list object at 0x7c6a5e2b9240>('commit')
- **D4g-isolation-after-work** — RED (exit 1); cmp identical; re-run green; sha256 34f9bd11c09570624aebf99de9f754f3baa2729e80db7cfad7b09688b70cf0b3
  - mutation: `'await session.connection(\n                        execution_options={"isolation_level": "READ COMMITTED"}\n                    )\n                    repository = self._repository_factory(session, 
  - test: `…/unit/test_stock_transactions.py::test_the_isolation_is_pinned_before_the_first_statement`
  - failure: services/fulfillment/tests/unit/test_stock_transactions.py:236: in test_the_isolation_is_pinned_before_the_first_statement ⏎ E   AssertionError: assert ['begin', 'wo... COMMITTED'})] == ['begin', ('c...ED'}), 'work'] ⏎ E     
- **D4h-nonDbapi-timeouts-unwrapped** — RED (exit 1); cmp identical; re-run green; sha256 34f9bd11c09570624aebf99de9f754f3baa2729e80db7cfad7b09688b70cf0b3
  - mutation: `'except (sqlalchemy.exc.TimeoutError, OSError) as error:'` -> `'except ZeroDivisionError as error:'` (pool timeout / OSError no longer mapped)
  - test: `…/unit/test_stock_transactions.py::test_a_pool_timeout_and_a_refused_connection_are_store_unavailable`
  - failure: services/fulfillment/tests/unit/test_stock_transactions.py:180: in test_a_pool_timeout_and_a_refused_connection_are_store_unavailable ⏎ services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py:94: in run ⏎ services/fulfillment/tests/unit/test_stock_transactions.py:106: in work
- **D4b2-four-attempts** — RED (exit 1); cmp identical; re-run green; sha256 34f9bd11c09570624aebf99de9f754f3baa2729e80db7cfad7b09688b70cf0b3
  - mutation: `"DEADLOCK_ATTEMPTS = 3  # total attempts, the relay's"` -> `"DEADLOCK_ATTEMPTS = 4  # total attempts, the relay's"` (DEADLOCK_ATTEMPTS = 4; supersedes D4b whose failure was an IndexError of the fake)
  - test: `…/unit/test_stock_transactions.py::test_fs23_a_deadlock_victim_is_rerun_at_most_three_times_paced_by_200_ms_then_unavailable`
  - failure: services/fulfillment/tests/unit/test_stock_transactions.py:123: in test_fs23_a_deadlock_victim_is_rerun_at_most_three_times_paced_by_200_ms_then_unavailable ⏎ services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py:94: in run ⏎ services/fulfillment/tests/unit/test_stock_transactions.py:101: in work
- **D8-mapper-writes-through-update-values** — RED (exit 1); cmp identical; re-run green; sha256 9028d00c4985f67cbc8cba2ebc76309b1b543a0d061a0092d02c8ec53ebafe20
  - mutation: `"['from collections.abc import Sequence\\n', '        row.units = item.units\\n', '        row.reserved_units = item.reserved_units\\n']"` -> `"['from collections.abc import Sequence\\n\\nfrom sqlalc
  - test: `…/unit/test_stock_mapper.py::test_a_unit_count_beyond_the_column_is_refused_when_the_mapper_assigns_it`
  - failure: services/fulfillment/tests/unit/test_stock_mapper.py:51: in test_a_unit_count_beyond_the_column_is_refused_when_the_mapper_assigns_it ⏎ E   Failed: DID NOT RAISE QuantityOutOfRangeError
- **E3a-lock-in-request-order** — RED (exit 1); cmp identical; re-run green; sha256 9ed9b9aa703c27b23983d1155b65ffe88cb279981e50022542511fbc734219db
  - mutation: `'return tuple(sorted(set(keys)))'` -> `'return tuple(dict.fromkeys(keys))'` (lock in request order)
  - test: `…/unit/test_stock_lock_order.py::test_fs19_orders_distinct_stock_keys_by_code_point_independently_of_request_order`
  - failure: services/fulfillment/tests/unit/test_stock_lock_order.py:14: in test_fs19_orders_distinct_stock_keys_by_code_point_independently_of_request_order ⏎ E   AssertionError: every request order of the same set locks in ONE order ⏎ E   assert {(('ACME-CO',...', 'PRD-A1'))} == {(('ACME-CO',...', 'PRD-C3'))}
- **E3b-uppercase-key** — RED (exit 1); cmp identical; re-run green; sha256 9ed9b9aa703c27b23983d1155b65ffe88cb279981e50022542511fbc734219db
  - mutation: `'return tuple(sorted(set(keys)))'` -> `'return tuple(sorted({(c, p.upper()) for c, p in keys}))'` (upper-case the key)
  - test: `…/unit/test_stock_lock_order.py::test_codes_differing_only_in_letter_case_are_two_keys`
  - failure: services/fulfillment/tests/unit/test_stock_lock_order.py:32: in test_codes_differing_only_in_letter_case_are_two_keys ⏎ E   AssertionError: assert (('ACME-CO', 'PRD-A1'),) == (('ACME-CO', ...O', 'prd-a1')) ⏎ E     
- **E5-replenish-then-raise** — RED (exit 1); cmp identical; re-run green; sha256 7a4a2eecab0a9fea00d2aeb9a530d9d019b1544aa4539cbd0f69f55bcdd8a57e
  - mutation: `'for product_code in totals:\n        if product_code not in items:\n            raise UnknownStockItemError(command.company_code, product_code)\n    for product_code, total in totals.items():\n     
  - test: `…/unit/test_stock_replenishment_service.py::test_an_unknown_product_on_any_line_raises_before_anything_is_replenished`
  - failure: services/fulfillment/tests/unit/test_stock_replenishment_service.py:83: in test_an_unknown_product_on_any_line_raises_before_anything_is_replenished ⏎ E   AssertionError: no line was replenished ⏎ E   assert 17 == 10
- **E4a-status-filter** — RED (exit 1); cmp identical; re-run green; sha256 feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d
  - mutation: `"['    if locked.reservations_of_order:\\n', 'from otc_fulfillment.domain.snapshot import ReservationSnapshot\\n']"` -> `"['    if any(r.status is ReservationStatus.RESERVED for r in locked.reservati
  - test: `['…/unit/test_stock_reservation_service.py::test_fs5_short_circuits_to_already_reserved_on_a_reservation_in_any_status_calling_no_domain_function_and_saving_nothing[ReservationStatus.RELEASED]', '…/unit/test_stock_reservation_service.py::test_fs5_short_circuits_to_already_reserved_on_a_reservation_in_any_status_calling_no_domain_function_and_saving_nothing[ReservationStatus.CONSUMED]']`
  - failure: services/fulfillment/tests/unit/test_stock_reservation_service.py:177: in test_fs5_short_circuits_to_already_reserved_on_a_reservation_in_any_status_calling_no_domain_fun ⏎ E   AssertionError: assert <ReserveOutcomeKind.ACCEPTED: 'accepted'> is <ReserveOutcomeKind.ALREADY_RESERVED: 'already_reserved'> ⏎ E    +  where <ReserveOutcomeKind.ACCEPTED: 'accepted'> = ReserveResult(outcome=<ReserveOutcomeKind.ACCEPTED: 'accepted'>, order_reference='ORD-000042', reservations=(Res
- **E4b-run-before-prereads-emptiness** — RED (exit 1); cmp identical; re-run green; sha256 feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d
  - mutation: `'if not keys:\n        return ReleaseResult('` -> `'await scope.transactions.run(\n        lambda tx: _release_work(\n            tx, command=command, keys=keys, now=scope.clock.now(), new_id=scope.i
  - test: `…/unit/test_stock_reservation_service.py::test_fs9_an_order_with_no_reservation_answers_already_released_without_calling_run`
  - failure: services/fulfillment/tests/unit/test_stock_reservation_service.py:239: in test_fs9_an_order_with_no_reservation_answers_already_released_without_calling_run ⏎ E   AssertionError: no transaction is opened ⏎ E   assert 1 == 0
- **E4c-save-on-no-carrier** — RED (exit 1); cmp identical; re-run green; sha256 feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d
  - mutation: `'case NoCarrier():\n            raise'` -> `'case NoCarrier():\n            await repository.save()\n            raise'` (call save() on the no-carrier path)
  - test: `…/unit/test_stock_reservation_service.py::test_no_carrier_raises_no_known_stock_item_and_saves_nothing`
  - failure: services/fulfillment/tests/unit/test_stock_reservation_service.py:294: in test_no_carrier_raises_no_known_stock_item_and_saves_nothing ⏎ E   assert 1 == 0 ⏎ E    +  where 1 = <services.fulfillment.tests.unit.test_stock_reservation_service.FakeRepository object at 0x786201e97770>.saves
- **E4d-reply-before-commit** — RED (exit 1); cmp identical; re-run green; sha256 feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d
  - mutation: `"['    return await scope.transactions.run(work)\\n\\n\\nasync def _release_work', 'from datetime import datetime\\n']"` -> `"['    holder: list[ReserveResult] = []\\n\\n    async def capture(tx: Sto
  - test: `…/unit/test_stock_reservation_service.py::test_the_reply_is_returned_only_after_run_returns`
  - failure: services/fulfillment/tests/unit/test_stock_reservation_service.py:201: in test_the_reply_is_returned_only_after_run_returns ⏎ E   AssertionError: but there is no reply while the commit is pending ⏎ E   assert not True
- **E4e-rollback-swallowed** — RED (exit 1); cmp identical; re-run green; sha256 feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d
  - mutation: `"['    return await scope.transactions.run(work)\\n\\n\\nasync def _release_work', 'from datetime import datetime\\n']"` -> `"['    holder: list[ReserveResult] = []\\n\\n    async def capture(tx: Sto
  - test: `…/unit/test_stock_reservation_service.py::test_a_rollback_propagates_and_produces_no_reply`
  - failure: services/fulfillment/tests/unit/test_stock_reservation_service.py:215: in test_a_rollback_propagates_and_produces_no_reply ⏎ E   Failed: DID NOT RAISE ConnectionError
- **F2a-model-construct-bypass** — RED (exit 1); cmp identical; re-run green; sha256 a81152d2a69e66b24c259e39c8b07b7b3720a2a986c876ee2cf1bcb65069976c
  - mutation: `"['        return from_wire_json(model, body)\\n']"` -> `'["        return model.model_construct(**__import__(\'json\').loads(body))\\n"]'` (decode with model_construct: validation bypassed, the viol
  - test: `…/unit/test_stock_requests.py::test_f2_each_constraint_violation_is_refused_by_the_decoder`
  - failure: services/fulfillment/tests/unit/test_stock_requests.py:123: in test_f2_each_constraint_violation_is_refused_by_the_decoder ⏎ services/fulfillment/src/otc_fulfillment/presentation/stock_wire.py:65: in decode_check ⏎ .venv/lib/python3.14/site-packages/pydantic/main.py:1042: in __getattr__
- **F2b-model-construct-bypass-nothing-dispatched** — RED (exit 1); cmp identical; re-run green; sha256 a81152d2a69e66b24c259e39c8b07b7b3720a2a986c876ee2cf1bcb65069976c
  - mutation: `'return from_wire_json(model, body)'` -> `"return model.model_construct(**__import__('json').loads(body))"` (same mutation at the responder level)
  - test: `…/unit/test_stock_requests.py::test_f2_each_violation_is_answered_validation_failed_and_nothing_is_dispatched`
  - failure: services/fulfillment/tests/unit/test_stock_requests.py:215: in test_f2_each_violation_is_answered_validation_failed_and_nothing_is_dispatched ⏎ E   AssertionError: ('missing companyCode', RpcError(code=<Code.internal_error: 'INTERNAL_ERROR'>, message='The request could not be proce...n_id=UUID('00000000-0000-0000 ⏎ E   assert <Code.internal_error: 'INTERNAL_ERROR'> is <Code.validation_failed: 'VALIDATION_FAILED'>
- **F2c-drop-length-check** — RED (exit 1); cmp identical; re-run green; sha256 a81152d2a69e66b24c259e39c8b07b7b3720a2a986c876ee2cf1bcb65069976c
  - mutation: `'if len(value) > ORDER_REFERENCE_MAX_LENGTH:'` -> `'if False:'` (drop the length check)
  - test: `…/unit/test_stock_requests.py::test_fs28_a_reference_longer_than_the_column_is_refused_as_validation_failed`
  - failure: services/fulfillment/tests/unit/test_stock_requests.py:156: in test_fs28_a_reference_longer_than_the_column_is_refused_as_validation_failed ⏎ E   Failed: DID NOT RAISE InvalidStockRequestError
- **F4a-store-unavailable-as-conflict** — RED (exit 1); cmp identical; re-run green; sha256 dd7883043a80bf73208ec0c8a000af88f8aa4bf8baf0c94caaa98d66b5bbd47b
  - mutation: `'case StoreUnavailableError() | ConcurrentReservationChangeError():\n            return rpc(Code.unavailable, str(error))'` -> `'case ConcurrentReservationChangeError():\n            return rpc(Code.
  - test: `tests/architecture/test_fulfillment_rpc_error_retryability.py::test_fs21_every_transient_store_failure_maps_to_a_code_the_saga_adapter_retries`
  - failure: tests/architecture/test_fulfillment_rpc_error_retryability.py:66: in test_fs21_every_transient_store_failure_maps_to_a_code_the_saga_adapter_retries ⏎ E   AssertionError: StoreUnavailableError(the stock store is temporarily unavailable (40001)) is answered CONFLICT, which Orders' saga adapter treats as a terminal reject ⏎ E   assert <Code.conflict: 'CONFLICT'> not in frozenset({<Code.conflict: 'CONFLICT'>, <Code.domain_error: 'DOMAIN_ERROR'>, <Code.invoice_not_payable: 'INVOICE_NOT_P...'NO
- **F4a2-no-input-conflict** — RED (exit 1); cmp identical; re-run green; sha256 dd7883043a80bf73208ec0c8a000af88f8aa4bf8baf0c94caaa98d66b5bbd47b
  - mutation: `'case StoreUnavailableError() | ConcurrentReservationChangeError():\n            return rpc(Code.unavailable, str(error))'` -> `'case ConcurrentReservationChangeError():\n            return rpc(Code.
  - test: `tests/architecture/test_fulfillment_rpc_error_retryability.py::test_fs21_no_input_produces_conflict`
  - failure: tests/architecture/test_fulfillment_rpc_error_retryability.py:76: in test_fs21_no_input_produces_conflict ⏎ E   AssertionError: assert <Code.conflict: 'CONFLICT'> not in {<Code.conflict: 'CONFLICT'>, <Code.domain_error: 'DOMAIN_ERROR'>, <Code.internal_error: 'INTERNAL_ERROR'>,  ⏎ E    +  where <Code.conflict: 'CONFLICT'> = Code.conflict
- **F4b-concurrent-as-conflict** — RED (exit 1); cmp identical; re-run green; sha256 dd7883043a80bf73208ec0c8a000af88f8aa4bf8baf0c94caaa98d66b5bbd47b
  - mutation: `'case StoreUnavailableError() | ConcurrentReservationChangeError():\n            return rpc(Code.unavailable, str(error))'` -> `'case StoreUnavailableError():\n            return rpc(Code.unavailable
  - test: `tests/architecture/test_fulfillment_rpc_error_retryability.py::test_fs21_every_transient_store_failure_maps_to_a_code_the_saga_adapter_retries`
  - failure: tests/architecture/test_fulfillment_rpc_error_retryability.py:66: in test_fs21_every_transient_store_failure_maps_to_a_code_the_saga_adapter_retries ⏎ E   AssertionError: ConcurrentReservationChangeError(order ORD-000042 gained a reservation on a stock item that was not locked) is answered CONFLICT, which Orders' saga a ⏎ E   assert <Code.conflict: 'CONFLICT'> not in frozenset({<Code.conflict: 'CONFLICT'>, <Code.domain_error: 'DOMAIN_ERROR'>, <Code.invoice_not_payable: 'INVOICE_NOT_P...'NO
- **F4c-terminal-as-domain-error** — RED (exit 1); cmp identical; re-run green; sha256 dd7883043a80bf73208ec0c8a000af88f8aa4bf8baf0c94caaa98d66b5bbd47b
  - mutation: `'return rpc(Code.precondition_failed, error.message, {"code": error.code})'` -> `'return rpc(Code.domain_error, error.message, {"code": error.code})'` (sibling code: the unit row must fail naming PRE
  - test: `…/unit/test_stock_rpc_errors.py::test_each_row_of_the_mapping_answers_its_code_and_details`
  - failure: services/fulfillment/tests/unit/test_stock_rpc_errors.py:80: in test_each_row_of_the_mapping_answers_its_code_and_details ⏎ E   AssertionError: consumed reservation ⏎ E   assert <Code.domain_error: 'DOMAIN_ERROR'> is <Code.precondition_failed: 'PRECONDITION_FAILED'>
- **F6a-no-semaphore** — RED (exit 1); cmp identical; re-run green; sha256 94fa63cbf9266b4c2c07a385f4ab394a5978e08dbe0d738a784ad46400a56f48
  - mutation: `'async with self._bound:'` -> `'if True:'` (remove the semaphore: three entered)
  - test: `…/unit/test_stock_responder.py::test_fs18_at_most_the_configured_number_of_requests_are_handled_at_once_and_the_next_starts_when_one_ends`
  - failure: services/fulfillment/tests/unit/test_stock_responder.py:280: in test_fs18_at_most_the_configured_number_of_requests_are_handled_at_once_and_the_next_starts_when_one_ends ⏎ E   AssertionError: exactly two requests entered; the third waits for a slot ⏎ E   assert {'one', 'three', 'two'} == {'one', 'two'}
- **F6b-one-scope-per-responder** — RED (exit 1); cmp identical; re-run green; sha256 94fa63cbf9266b4c2c07a385f4ab394a5978e08dbe0d738a784ad46400a56f48
  - mutation: `"['message.data, message.headers, self._dispatcher, self._scope_factory()\\n', '        self._inbox: asyncio.Queue[tuple[str, Msg] | None] = asyncio.Queue()\\n']"` -> `"['message.data, message.header
  - test: `…/unit/test_stock_responder.py::test_fs18_each_request_gets_its_own_unit_of_work`
  - failure: services/fulfillment/tests/unit/test_stock_responder.py:299: in test_fs18_each_request_gets_its_own_unit_of_work ⏎ E   AssertionError: two concurrent requests observe two distinct scopes ⏎ E   assert <object object at 0x7ce79bbd7ae0> is not <object object at 0x7ce79bbd7ae0>
- **F3a-skip-header-check-on-release** — RED (exit 1); cmp identical; re-run green; sha256 94fa63cbf9266b4c2c07a385f4ab394a5978e08dbe0d738a784ad46400a56f48
  - mutation: `'correlation = required_correlation(headers)\n    result = await dispatcher.send(stock_wire.decode_release(body, correlation), scope)'` -> `'from otc_fulfillment.presentation.stock_headers import Rpc
  - test: `…/unit/test_stock_responder.py::test_fs3_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_or_malformed`
  - failure: services/fulfillment/tests/unit/test_stock_responder.py:231: in test_fs3_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_ ⏎ E   assert <Code.internal_error: 'INTERNAL_ERROR'> is <Code.validation_failed: 'VALIDATION_FAILED'> ⏎ E    +  where <Code.internal_error: 'INTERNAL_ERROR'> = RpcError(code=<Code.internal_error: 'INTERNAL_ERROR'>, message='The request could not be processed.', details=None
- **F3b-accept-malformed-request-id** — RED (exit 1); cmp identical; re-run green; sha256 8f3bbeaf2b2d42b907b421f2bc37969e774873386aa556aac273529a62fe5c5f
  - mutation: `'request_id=_identifier(headers, REQUEST_HEADER),'` -> `'request_id=UniqueId.new(),'` (ignore x-request-id: a malformed/missing one is accepted)
  - test: `…/unit/test_stock_responder.py::test_fs3_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_or_malformed`
  - failure: services/fulfillment/tests/unit/test_stock_responder.py:231: in test_fs3_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_ ⏎ E   assert <Code.internal_error: 'INTERNAL_ERROR'> is <Code.validation_failed: 'VALIDATION_FAILED'> ⏎ E    +  where <Code.internal_error: 'INTERNAL_ERROR'> = RpcError(code=<Code.internal_error: 'INTERNAL_ERROR'>, message='The request could not be processed.', details=None
- **F7-gather-without-return-exceptions** — RED (exit 1); cmp identical; re-run green; sha256 94fa63cbf9266b4c2c07a385f4ab394a5978e08dbe0d738a784ad46400a56f48
  - mutation: `'await asyncio.gather(*tuple(in_flight), return_exceptions=True)'` -> `'await asyncio.gather(*tuple(in_flight))'` (gather without return_exceptions)
  - test: `…/unit/test_stock_responder.py::test_fs26_shutdown_with_one_faulted_and_one_healthy_request_in_flight_completes_and_waits`
  - failure: services/fulfillment/tests/unit/test_stock_responder.py:327: in test_fs26_shutdown_with_one_faulted_and_one_healthy_request_in_flight_completes_and_waits ⏎ E   AssertionError: one request finishing (badly) must not end the drain early ⏎ E   assert not True
- **F8a-delete-flush** — RED (exit 1); cmp identical; re-run green; sha256 94fa63cbf9266b4c2c07a385f4ab394a5978e08dbe0d738a784ad46400a56f48
  - mutation: `'await self._connection.flush()'` -> `''` (delete the flush)
  - test: `…/unit/test_stock_responder.py::test_fs27_start_flushes_after_the_last_subscription`
  - failure: services/fulfillment/tests/unit/test_stock_responder.py:348: in test_fs27_start_flushes_after_the_last_subscription ⏎ E   AssertionError: assert ('subscribe',...-fulfillment') == ('flush',) ⏎ E     
- **F8b-subscribe-without-queue** — RED (exit 1); cmp identical; re-run green; sha256 94fa63cbf9266b4c2c07a385f4ab394a5978e08dbe0d738a784ad46400a56f48
  - mutation: `'queue=FULFILLMENT_QUEUE_GROUP,'` -> `'queue="otc-orders",'` (sibling substitution: Orders' queue group; the failure must name the queue)
  - test: `…/unit/test_stock_responder.py::test_fs27_start_flushes_after_the_last_subscription`
  - failure: services/fulfillment/tests/unit/test_stock_responder.py:347: in test_fs27_start_flushes_after_the_last_subscription ⏎ E   AssertionError: every subscription is queue-grouped ⏎ E   assert {'otc-orders'} == {'otc-fulfillment'}
- **F9-swallow-cancellation** — RED (exit 1); cmp identical; re-run green; sha256 94fa63cbf9266b4c2c07a385f4ab394a5978e08dbe0d738a784ad46400a56f48
  - mutation: `'for task in in_flight:\n                task.cancel()\n            raise'` -> `'for task in in_flight:\n                task.cancel()'` (swallow CancelledError in run)
  - test: `…/unit/test_stock_responder.py::test_cancelling_the_task_propagates_and_cancels_its_requests`
  - failure: services/fulfillment/tests/unit/test_stock_responder.py:402: in test_cancelling_the_task_propagates_and_cancels_its_requests ⏎ E   Failed: DID NOT RAISE CancelledError
- **G3-client-id-alias-is-the-shared-variable** — RED (exit 1); cmp identical; re-run green; sha256 cbce893f1f486543e86728fb2512c3ead7004a1ae1cb6217eb73f8d58baf36ff
  - mutation: `'validation_alias="FULFILLMENT_KAFKA_CLIENT_ID"'` -> `'validation_alias="KAFKA_CLIENT_ID"'` (sibling substitution: `.env` holds otc-orders under KAFKA_CLIENT_ID)
  - test: `…/unit/test_fulfillment_settings_env.py`
  - failure: services/fulfillment/tests/unit/test_fulfillment_settings_env.py:108: in test_the_population_of_environment_variables_is_exactly_the_literal ⏎ E   AssertionError: declared but untested: ['KAFKA_CLIENT_ID']; tested but not declared: ['FULFILLMENT_KAFKA_CLIENT_ID'] ⏎ E   assert {'FULFILLMENT...CH_SIZE', ...} == {'FULFILLMENT...CH_SIZE', ...}
- **G5-environ-get-in-stock-reads** — RED (exit 1); cmp identical; re-run green; sha256 7e023f06b1b0f89da618aa550dadb003e9bea8ee39c2076958549b42efa02ee3
  - mutation: `'class SqlAlchemyStockReads:'` -> `"import os\n\n\nclass SqlAlchemyStockReads:\n    def _leak(self) -> object:\n        if False:\n            return os.environ.get('KAFKA_BROKERS')\n        return N
  - test: `tests/architecture/test_composition_env_reads.py::test_nothing_in_a_service_with_a_root_reads_the_environment_directly`
  - failure: tests/architecture/test_composition_env_reads.py:133: in test_nothing_in_a_service_with_a_root_reads_the_environment_directly ⏎ E   AssertionError: read the environment through a settings class instead: {'services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_reads.py line 29: o ⏎ E   assert not {'services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_reads.py line 29: os.environ'}
- **J1a-consumer-import-in-fulfillment-publisher** — RED (exit 1); cmp identical; re-run green; sha256 ca943a4d348ff155a1db0cddaa4766cf45d0693adc0b5d8d7cf023ede383c889
  - mutation: `'import asyncio'` -> `'import asyncio\n\nfrom aiokafka import AIOKafkaConsumer  # noqa: F401'` (an AIOKafkaConsumer import in Fulfillment's kafka_publisher.py)
  - test: `tests/architecture/test_kafka_client_confinement.py::test_the_modules_importing_aiokafka_are_exactly_the_two_publishers_and_the_subscriber`
  - failure: tests/architecture/test_kafka_client_confinement.py:99: in test_the_modules_importing_aiokafka_are_exactly_the_two_publishers_and_the_subscriber ⏎ E   assert ["the publish...kaConsumer']"] == [] ⏎ E     
- **J1b-aiokafka-in-application** — RED (exit 1); cmp identical; re-run green; sha256 feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d
  - mutation: `'from datetime import datetime'` -> `'from datetime import datetime\n\nimport aiokafka  # noqa: F401'` (an aiokafka import in application/stock_reservation.py; ALSO caught by import-linter, recorded 
  - test: `tests/architecture/test_kafka_client_confinement.py::test_the_modules_importing_aiokafka_are_exactly_the_two_publishers_and_the_subscriber`
  - failure: tests/architecture/test_kafka_client_confinement.py:99: in test_the_modules_importing_aiokafka_are_exactly_the_two_publishers_and_the_subscriber ⏎ E   assert ["the modules..._publisher']"] == [] ⏎ E     
- **G8-F-g-and-F-j-on-this-root** — RED (exit 1); cmp identical; re-run green; sha256 13ac8d21d562a96b811d680466e2dc3774b57a31b880c9eff50a14b6820c7422, 94d57c82dcbfe9b555ef95c69a4d4dbd6261cfe5b8bbf1be33dcdbff294658c9, 94d57c82dcbfe9b555ef95c69a4d4dbd6261cfe5b8bbf1be33dcdbff294658c9
  - mutation: (F-g ALONE on this root, corrected in round 2 per review D7b: an __init_subclass__ hook on `ReserveStockCommand` in messages.py + a helper loop in composition.register_handlers. The hook is inert, because nothing subclasses `ReserveStockCommand` and the root drains a literal tuple, so the F-j half did not run; the arm failed by F-g's WIRE clause alone. The real F-j pipeline is the reviewer's `Q6` fixture, RED by the WIRE clause: `.arm/review17/log.md`)
  - test: `tests/architecture/test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[fulfillment]`
  - failure: tests/architecture/test_registration_behaviour.py:229: in test_a_service_registers_only_from_its_composition_root_and_its_tables_match ⏎ E   assert ["WIRE: 3 reg...ockCommand']"] == [] ⏎ E     
- **G4a-hardcode-client-id** — RED (exit 1); cmp identical; re-run green; sha256 94d57c82dcbfe9b555ef95c69a4d4dbd6261cfe5b8bbf1be33dcdbff294658c9
  - mutation: `'KafkaFactPublisher(settings.kafka)'` -> `"KafkaFactPublisher(settings.kafka.model_copy(update={'client_id': 'otc-fulfillment'}))"` (hard-code the client id in composition.py)
  - test: `…/integration/test_fulfillment_host_lifespan.py::test_every_setting_the_composition_root_reads_reaches_its_adapter`
  - failure: services/fulfillment/tests/integration/test_fulfillment_host_lifespan.py:369: in test_every_setting_the_composition_root_reads_reaches_its_adapter ⏎ E   AssertionError: FULFILLMENT_KAFKA_CLIENT_ID must reach it ⏎ E   assert 'otc-fulfillment' == 'otc-fulfillment-sentinel'
- **G4b-engine-without-pool-arguments** — RED (exit 1); cmp identical; re-run green; sha256 94d57c82dcbfe9b555ef95c69a4d4dbd6261cfe5b8bbf1be33dcdbff294658c9
  - mutation: `"settings.database.url,\n            pool_size=bound + 1,  # the responder's sessions, plus the relay's\n            max_overflow=0,"` -> `'settings.database.url,'` (build the engine without the pool
  - test: `…/integration/test_fulfillment_host_lifespan.py::test_every_setting_the_composition_root_reads_reaches_its_adapter`
  - failure: services/fulfillment/tests/integration/test_fulfillment_host_lifespan.py:366: in test_every_setting_the_composition_root_reads_reaches_its_adapter ⏎ E   AssertionError: the engine's pool is sized from the bound + 1 ⏎ E   assert 5 == 8
- **G6-skip-registered-factories** — RED (exit 1); cmp identical; re-run green; sha256 94d57c82dcbfe9b555ef95c69a4d4dbd6261cfe5b8bbf1be33dcdbff294658c9
  - mutation: `'for factory in registered_factories:\n            factory(scope_factory())'` -> `''` (skip the registered_factories() construction: the unbound-port case fails)
  - test: `…/integration/test_fulfillment_host_lifespan.py::test_a_port_bound_to_nothing_fails_the_boot_not_the_first_message`
  - failure: services/fulfillment/tests/integration/test_fulfillment_host_lifespan.py:271: in test_a_port_bound_to_nothing_fails_the_boot_not_the_first_message ⏎ E   Failed: the host must not come up with the reads port unbound
- **G6b-skip-registered-factories-unbuildable** — RED (exit 1); cmp identical; re-run green; sha256 94d57c82dcbfe9b555ef95c69a4d4dbd6261cfe5b8bbf1be33dcdbff294658c9
  - mutation: `'for factory in registered_factories:\n            factory(scope_factory())'` -> `''` (same mutation: the unbuildable-handler cases fail)
  - test: `…/integration/test_fulfillment_host_lifespan.py::test_a_registered_handler_that_cannot_be_built_fails_the_boot_whoever_registered_it`
  - failure: services/fulfillment/tests/integration/test_fulfillment_host_lifespan.py:307: in test_a_registered_handler_that_cannot_be_built_fails_the_boot_whoever_registered_it ⏎ E   Failed: the host must not come up with a registered handler that cannot be built ⏎ services/fulfillment/tests/integration/test_fulfillment_host_lifespan.py:307: in test_a_registered_handler_that_cannot_be_built_fails_the_boot_whoever_registered_it
- **G7a-responder-not-in-readiness** — RED (exit 1); cmp identical; re-run green (superseded by G7a2 (the dict mutation died at a KeyError in the test, not at readiness)); sha256 94d57c82dcbfe9b555ef95c69a4d4dbd6261cfe5b8bbf1be33dcdbff294658c9
  - mutation: `'tasks=tasks,\n                connection=connection,\n                engine=engine,'` -> `"tasks={k: v for k, v in tasks.items() if k != 'nats-responder'},\n                connection=connection,\n
  - test: `…/integration/test_fulfillment_host_lifespan.py::test_a_transport_task_that_dies_takes_readiness_down_and_names_it`
  - failure: services/fulfillment/tests/integration/test_fulfillment_host_lifespan.py:78: in test_a_transport_task_that_dies_takes_readiness_down_and_names_it ⏎ E   KeyError: 'nats-responder'
- **G7b-no-single-relay-assertion** — RED (exit 1); cmp identical; re-run green; sha256 94d57c82dcbfe9b555ef95c69a4d4dbd6261cfe5b8bbf1be33dcdbff294658c9
  - mutation: `'assert_single_outbox_relay(\n            relay_enabled=relay_enabled,\n            web_concurrency=settings.server.web_concurrency,\n            in_worker_process=running_in_worker_process(),\n     
  - test: `…/integration/test_fulfillment_host_lifespan.py::test_more_than_one_worker_with_the_relay_enabled_refuses_to_boot_before_connecting`
  - failure: services/fulfillment/tests/integration/test_fulfillment_host_lifespan.py:392: in test_more_than_one_worker_with_the_relay_enabled_refuses_to_boot_before_connecting ⏎ /home/juanpabloperez/.local/share/uv/python/cpython-3.14.8-linux-x86_64-gnu/lib/python3.14/contextlib.py:214: in __aenter__ ⏎ services/fulfillment/tests/integration/conftest.py:190: in start
- **G7a2-readiness-ignores-the-responder** — RED (exit 1); cmp identical; re-run green; sha256 94d57c82dcbfe9b555ef95c69a4d4dbd6261cfe5b8bbf1be33dcdbff294658c9
  - mutation: `'f"transport task {name} is not running" for name, t in self.tasks.items() if t.done()'` -> `'f"transport task {name} is not running"\n            for name, t in self.tasks.items()\n            if t.
  - test: `…/integration/test_fulfillment_host_lifespan.py::test_a_transport_task_that_dies_takes_readiness_down_and_names_it`
  - failure: services/fulfillment/tests/integration/test_fulfillment_host_lifespan.py:85: in test_a_transport_task_that_dies_takes_readiness_down_and_names_it ⏎ E   assert 200 == 503 ⏎ E    +  where 200 = <Response [200 OK]>.status_code
- **H1a-check-writes-an-outbox-row** — RED (exit 1); cmp identical; re-run green; sha256 7e023f06b1b0f89da618aa550dadb003e9bea8ee39c2076958549b42efa02ee3
  - mutation: `"['        codes = list(dict.fromkeys(code for code, _ in lines))\\n']"` -> `'["        codes = list(dict.fromkeys(code for code, _ in lines))\\n        import uuid as _u\\n        from datetime impo
  - test: `…/integration/test_stock_check.py::test_r31_answers_per_line_without_mutating_a_stock_item_and_without_emitting_a_fact`
  - failure: services/fulfillment/tests/integration/test_stock_check.py:39: in test_r31_answers_per_line_without_mutating_a_stock_item_and_without_emitting_a_fact ⏎ E   AssertionError: a check emits no fact ⏎ E   assert [{'id': UUID(...24422'), ...}] == []
- **H1b-check-mutates-a-stock-row** — RED (exit 1); cmp identical; re-run green (superseded by H1b2 (it died at the reply assertion before the rows-equal one)); sha256 7e023f06b1b0f89da618aa550dadb003e9bea8ee39c2076958549b42efa02ee3
  - mutation: `"['        codes = list(dict.fromkeys(code for code, _ in lines))\\n']"` -> `'[\'        codes = list(dict.fromkeys(code for code, _ in lines))\\n        from sqlalchemy import text as _t\\n        a
  - test: `…/integration/test_stock_check.py::test_r31_answers_per_line_without_mutating_a_stock_item_and_without_emitting_a_fact`
  - failure: services/fulfillment/tests/integration/test_stock_check.py:30: in test_r31_answers_per_line_without_mutating_a_stock_item_and_without_emitting_a_fact ⏎ E   AssertionError: assert {'available':...ent': False}]} == {'available':...ent': False}]} ⏎ E     
- **H1c-unknown-product-not-found** — RED (exit 1); cmp identical; re-run green; sha256 7e023f06b1b0f89da618aa550dadb003e9bea8ee39c2076958549b42efa02ee3
  - mutation: `"['        available_by_code = {row.product_code: row.units - row.reserved_units for row in rows}\\n']"` -> `"['        available_by_code = {row.product_code: row.units - row.reserved_units for row i
  - test: `…/integration/test_stock_check.py::test_fs22_answers_an_unknown_product_with_available_zero_and_sufficient_false_never_with_an_rpc_error`
  - failure: services/fulfillment/tests/integration/test_stock_check.py:81: in test_fs22_answers_an_unknown_product_with_available_zero_and_sufficient_false_never_with_an_rpc_error ⏎ E   AssertionError: an unknown product is not an RpcError: {'code': 'NOT_FOUND', 'message': "no stock item for product 'PRD-Z9' of company 'ACME-CO'", 'details': {'compan ⏎ E   assert 'code' not in {'code': 'NOT_FOUND', 'message': "no stock item for product 'PRD-Z9' of company 'ACME-CO'", 'details': {'companyCode': 'ACME-CO', 'productCode': 
- **H2-check-locks-the-row** — RED (exit 1); cmp identical; re-run green; sha256 7e023f06b1b0f89da618aa550dadb003e9bea8ee39c2076958549b42efa02ee3
  - mutation: `"['                    select(Stock.product_code, Stock.units, Stock.reserved_units).where(\\n                        Stock.company_code == company_code, Stock.product_code.in_(codes)\\n             
  - test: `…/integration/test_stock_check.py::test_a_check_is_answered_while_a_test_transaction_holds_the_row_for_update`
  - failure: /home/juanpabloperez/.local/share/uv/python/cpython-3.14.8-linux-x86_64-gnu/lib/python3.14/asyncio/tasks.py:486: in wait_for ⏎ services/fulfillment/tests/integration/conftest.py:350: in call ⏎ .venv/lib/python3.14/site-packages/nats/aio/client.py:1142: in request
- **H1b2-check-touches-a-stock-row-reply-unchanged** — RED (exit 1); cmp identical; re-run green; sha256 7e023f06b1b0f89da618aa550dadb003e9bea8ee39c2076958549b42efa02ee3
  - mutation: `"['        codes = list(dict.fromkeys(code for code, _ in lines))\\n']"` -> `'[\'        codes = list(dict.fromkeys(code for code, _ in lines))\\n        from sqlalchemy import text as _t\\n        a
  - test: `…/integration/test_stock_check.py::test_r31_answers_per_line_without_mutating_a_stock_item_and_without_emitting_a_fact`
  - failure: services/fulfillment/tests/integration/test_stock_check.py:38: in test_r31_answers_per_line_without_mutating_a_stock_item_and_without_emitting_a_fact ⏎ E   AssertionError: a check mutates no stock item ⏎ E   assert [{'id': UUID(...ts': 50, ...}] == [{'id': UUID(...ts': 50, ...}]
- **H3a-no-outbox-write** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `'events.extend(loaded.item.domain_events)'` -> `'pass'` (delete the emission: the repository drains no events)
  - test: `…/integration/test_stock_reserve.py::test_r32_the_accepted_path_creates_one_reservation_per_line_raises_the_counters_and_writes_exactly_one_reserved_fact`
  - failure: services/fulfillment/tests/integration/test_stock_reserve.py:82: in test_r32_the_accepted_path_creates_one_reservation_per_line_raises_the_counters_and_writes_exactly_one ⏎ E   ValueError: not enough values to unpack (expected 1, got 0)
- **H3b-causation-from-correlation** — RED (exit 1); cmp identical; re-run green; sha256 feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d
  - mutation: `'StockContext(occurred_at=now, causation_id=command.request_id),\n        new_id,\n    )\n    match outcome:\n        case NoCarrier():'` -> `'StockContext(occurred_at=now, causation_id=command.corre
  - test: `…/integration/test_stock_reserve.py::test_fs3_stamps_correlation_id_from_the_header_and_causation_id_from_the_request_id_on_the_emitted_fact`
  - failure: services/fulfillment/tests/integration/test_stock_reserve.py:104: in test_fs3_stamps_correlation_id_from_the_header_and_causation_id_from_the_request_id_on_the_emitted_fa ⏎ E   AssertionError: assert '00000000-000...-00000000c0c0' == '00000000-000...-00000000ca05' ⏎ E     
- **H3c-drop-retailer-code** — RED (exit 1); cmp identical; re-run green; sha256 f577efe4033f8c00afca1f10a647bc4bcc0ffda1a68191dc849b773f4b1a28d4
  - mutation: `'retailer_code=event.retailer_code,\n        reservations='` -> `'reservations='` (row 7: drop retailerCode at the integration level)
  - test: `…/integration/test_stock_reserve.py::test_r32_the_accepted_path_creates_one_reservation_per_line_raises_the_counters_and_writes_exactly_one_reserved_fact`
  - failure: services/fulfillment/tests/integration/test_stock_reserve.py:85: in test_r32_the_accepted_path_creates_one_reservation_per_line_raises_the_counters_and_writes_exactly_one ⏎ E   AssertionError: assert {'orderRefere... 'units': 2}]} == {'orderRefere... 'units': 2}]} ⏎ E     
- **H4a-skip-save-on-rejected** — RED (exit 1); cmp identical; re-run green; sha256 feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d
  - mutation: `'case Rejected():\n            await repository.save()'` -> `'case Rejected():'` (#8 D1's mutation: skip save() on the rejected path)
  - test: `…/integration/test_stock_reserve.py::test_h4_the_rejected_path_replies_rejected_creates_nothing_and_writes_exactly_one_rejected_fact`
  - failure: services/fulfillment/tests/integration/test_stock_reserve.py:130: in test_h4_the_rejected_path_replies_rejected_creates_nothing_and_writes_exactly_one_rejected_fact ⏎ E   ValueError: not enough values to unpack (expected 1, got 0)
- **H4b-corrupt-available** — RED (exit 1); cmp identical; re-run green; sha256 2e52e55f047c876ecdde0d7163a325c53cd0ee4aeb144719fae2fea9976b954d
  - mutation: `'Shortage(product_code=product_code, requested=units, available=item.available_units)'` -> `'Shortage(product_code=product_code, requested=units, available=item.units)'` (corrupt `available` in the s
  - test: `…/integration/test_stock_reserve.py::test_h4_the_rejected_path_replies_rejected_creates_nothing_and_writes_exactly_one_rejected_fact`
  - failure: services/fulfillment/tests/integration/test_stock_reserve.py:122: in test_h4_the_rejected_path_replies_rejected_creates_nothing_and_writes_exactly_one_rejected_fact ⏎ E   AssertionError: assert {'outcome': '...ailable': 5}]} == {'outcome': '...ailable': 2}]} ⏎ E     
- **H4c-reason-substitution** — RED (exit 1); cmp identical; re-run green; sha256 2e52e55f047c876ecdde0d7163a325c53cd0ee4aeb144719fae2fea9976b954d
  - mutation: `'reason = RejectionReason.UNKNOWN_PRODUCT if unknown else RejectionReason.INSUFFICIENT_STOCK'` -> `'reason = RejectionReason.INSUFFICIENT_STOCK'` (insufficient_stock substituted for unknown_product)
  - test: `…/integration/test_stock_reserve.py::test_h4_an_unstocked_product_is_rejected_with_reason_unknown_product`
  - failure: services/fulfillment/tests/integration/test_stock_reserve.py:158: in test_h4_an_unstocked_product_is_rejected_with_reason_unknown_product ⏎ E   AssertionError: assert 'insufficient_stock' == 'unknown_product' ⏎ E     
- **H5a-status-filter-integration** — RED (exit 1); cmp identical; re-run green; sha256 feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d
  - mutation: `"['    if locked.reservations_of_order:\\n', 'from otc_fulfillment.domain.snapshot import ReservationSnapshot\\n']"` -> `"['    if any(r.status is ReservationStatus.RESERVED for r in locked.reservati
  - test: `…/integration/test_stock_reserve.py::test_fs5_answers_already_reserved_for_an_order_whose_only_reservation_is_already_released_reserving_nothing_new`
  - failure: services/fulfillment/tests/integration/test_stock_reserve.py:215: in test_fs5_answers_already_reserved_for_an_order_whose_only_reservation_is_already_released_reserving_n ⏎ E   AssertionError: assert 'accepted' == 'already_reserved' ⏎ E     
- **H5b-scoped-reservation-read** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `"['        reservations = await self._lock_reservations_of(order_reference)\\n        return LockedStock(\\n            items=self._load(rows, reservations),\\n            reservations_of_order=tuple
  - test: `…/integration/test_stock_reserve.py::test_fs5_answers_already_reserved_for_a_reissue_naming_a_different_product`
  - failure: services/fulfillment/tests/integration/test_stock_reserve.py:245: in test_fs5_answers_already_reserved_for_a_reissue_naming_a_different_product ⏎ E   AssertionError: assert 'accepted' == 'already_reserved' ⏎ E     
- **H5c-parse-with-order-number** — RED (exit 1); cmp identical; re-run green; sha256 a81152d2a69e66b24c259e39c8b07b7b3720a2a986c876ee2cf1bcb65069976c
  - mutation: `"['def _order_reference(value: str) -> str:\\n', 'ORDER_REFERENCE_MAX_LENGTH = 20']"` -> `"['def _order_reference(value: str) -> str:\\n    from otc_shared_kernel import OrderNumber\\n\\n    OrderNum
  - test: `…/integration/test_stock_reserve.py::test_fs28_reserves_for_ord_000000_which_the_kernel_parse_refuses`
  - failure: services/fulfillment/tests/integration/test_stock_reserve.py:263: in test_fs28_reserves_for_ord_000000_which_the_kernel_parse_refuses ⏎ E   KeyError: 'outcome'
- **H6-no-carrier-falls-through** — RED (exit 1); cmp identical; re-run green; sha256 feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d
  - mutation: `'case NoCarrier():\n            raise NoKnownStockItemError(command.order_reference)'` -> `'case NoCarrier():\n            await repository.save()\n            return ReserveResult(\n                
  - test: `…/integration/test_stock_reserve.py::test_a_reserve_naming_no_stocked_product_answers_not_found_and_writes_nothing`
  - failure: services/fulfillment/tests/integration/test_stock_reserve.py:282: in test_a_reserve_naming_no_stocked_product_answers_not_found_and_writes_nothing ⏎ E   KeyError: 'code'
- **H12b-case-insensitive-everywhere** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `"['from sqlalchemy import select\\n', '                .where(Stock.company_code == company_code, Stock.product_code == product_code)\\n', '        reservations = await self._lock_reservations_of(ord
  - test: `…/integration/test_stock_reserve.py::test_a_code_differing_only_in_letter_case_is_a_different_product`
  - failure: services/fulfillment/tests/integration/test_stock_reserve.py:305: in test_a_code_differing_only_in_letter_case_is_a_different_product ⏎ E   KeyError: 'code'
- **H7a-released-reason-constant** — RED (exit 1); cmp identical; re-run green; sha256 f577efe4033f8c00afca1f10a647bc4bcc0ffda1a68191dc849b773f4b1a28d4
  - mutation: `'reason=asyncapi.Reason1(event.reason.value),'` -> `'reason=asyncapi.Reason1.order_cancelled,'` (#8 D2: corrupt reason in the payload mapper)
  - test: `…/integration/test_stock_release_idempotency.py::test_the_reason_of_the_released_fact_is_the_requests_whichever_it_is`
  - failure: services/fulfillment/tests/integration/test_stock_release_idempotency.py:88: in test_the_reason_of_the_released_fact_is_the_requests_whichever_it_is ⏎ E   AssertionError: assert 'order_cancelled' == 'credit_rejected' ⏎ E     
- **H7b-delete-emission** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `'events.extend(loaded.item.domain_events)'` -> `'pass'` (delete the emission)
  - test: `…/integration/test_stock_release_idempotency.py::test_the_release_releases_every_reservation_lowers_the_counters_and_writes_exactly_one_released_fact`
  - failure: services/fulfillment/tests/integration/test_stock_release_idempotency.py:64: in test_the_release_releases_every_reservation_lowers_the_counters_and_writes_exactly_one_rel ⏎ E   ValueError: not enough values to unpack (expected 1, got 0)
- **H7c-emit-on-already-released** — RED (exit 1); cmp identical; re-run green; sha256 feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d
  - mutation: `"['        case AlreadyReleased():\\n            return ReleaseResult(']"` -> `'["        case AlreadyReleased():\\n            from otc_fulfillment.domain.events import StockReleased as _SR\\n\\n   
  - test: `…/integration/test_stock_release_idempotency.py::test_r34_answers_success_and_emits_no_second_fact_when_every_reservation_is_already_released`
  - failure: services/fulfillment/tests/integration/test_stock_release_idempotency.py:108: in test_r34_answers_success_and_emits_no_second_fact_when_every_reservation_is_already_relea ⏎ E   AssertionError: no second fact ⏎ E   assert 2 == 1
- **H7d-release-a-consumed-row** — RED (exit 1); cmp identical; re-run green; sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc
  - mutation: `'if any(r.status is ReservationStatus.CONSUMED for r in mine):\n            raise ReservationTerminalError(\n                ReservationStatus.CONSUMED.value, ReservationStatus.RELEASED.value\n      
  - test: `…/integration/test_stock_release_idempotency.py::test_fs10_replies_precondition_failed_and_emits_nothing_when_the_orders_reservations_are_consumed`
  - failure: services/fulfillment/tests/integration/test_stock_release_idempotency.py:152: in test_fs10_replies_precondition_failed_and_emits_nothing_when_the_orders_reservations_are_ ⏎ E   KeyError: 'code'
- **I5-release-lock-dropped** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `'.with_for_update()\n            )\n            if row is not None:'` -> `')\n            if row is not None:'` (drop with_for_update() from the stock step shared by lock_order_items)
  - test: `…/integration/test_stock_release_idempotency.py::test_fs25_a_release_waits_for_a_transaction_holding_a_stock_row_of_the_order_before_reading_its_reservations`
  - failure: services/fulfillment/tests/integration/conftest.py:283: in wait_for_lock_waiters ⏎ /home/juanpabloperez/.local/share/uv/python/cpython-3.14.8-linux-x86_64-gnu/lib/python3.14/asyncio/tasks.py:712: in sleep ⏎ E   asyncio.exceptions.CancelledError
- **H8-wrap-replies-in-response** — RED (exit 1); cmp identical; re-run green; sha256 a81152d2a69e66b24c259e39c8b07b7b3720a2a986c876ee2cf1bcb65069976c
  - mutation: `'def encode(model: WireModel) -> bytes:\n    return to_wire_json(model).encode("utf-8")'` -> `'def encode(model: WireModel) -> bytes:\n    return (\'{"response":\' + to_wire_json(model) + \',"isDispo
  - test: `…/integration/test_stock_wire.py`
  - failure: services/fulfillment/tests/integration/test_stock_wire.py:79: in test_fs4_answers_a_bare_json_request_with_a_bare_json_reply_on_all_five_subjects ⏎ E   AssertionError: exactly the reply schema's properties that are present ⏎ E   assert {'isDisposed', 'response'} == {'available', 'lines'}
- **H9-serve-inline** — RED (exit 1); cmp identical; re-run green; sha256 94fa63cbf9266b4c2c07a385f4ab394a5978e08dbe0d738a784ad46400a56f48
  - mutation: `'self._serve_in_task(*item, in_flight)'` -> `'await self._serve(*item)'` (serve each request inline in the loop: the second request times out)
  - test: `…/integration/test_stock_responder_concurrency.py`
  - failure: /home/juanpabloperez/.local/share/uv/python/cpython-3.14.8-linux-x86_64-gnu/lib/python3.14/asyncio/tasks.py:486: in wait_for ⏎ services/fulfillment/tests/integration/conftest.py:350: in call ⏎ .venv/lib/python3.14/site-packages/nats/aio/client.py:1142: in request
- **H10a-replenish-before-check-INTEGRATION-LEVEL** — STAYED GREEN (exit 0); cmp identical; re-run green; sha256 7a4a2eecab0a9fea00d2aeb9a530d9d019b1544aa4539cbd0f69f55bcdd8a57e
  - mutation: `'for product_code in totals:\n        if product_code not in items:\n            raise UnknownStockItemError(command.company_code, product_code)\n    for product_code, total in totals.items():\n     
  - test: `…/integration/test_stock_replenish.py::test_fs14_replies_not_found_and_replenishes_no_line_when_any_line_names_an_unknown_product`
  - failure: 
- **H10b-units-written-through-update-values** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `"['            stock_mapper.apply_item(loaded.item, loaded.row, now)\\n', 'from sqlalchemy import select\\n']"` -> `"['            await self._session.execute(\\n                update(Stock)\\n     
  - test: `…/integration/test_stock_replenish.py::test_fs20_refuses_a_replenishment_that_would_overflow_the_unit_column_with_a_domain_error_and_changes_nothing`
  - failure: services/fulfillment/tests/integration/test_stock_replenish.py:100: in test_fs20_refuses_a_replenishment_that_would_overflow_the_unit_column_with_a_domain_error_and_chang ⏎ E   AssertionError: assert 'INTERNAL_ERROR' == 'DOMAIN_ERROR' ⏎ E     
- **H11a-order-by-product-only** — RED (exit 1); cmp identical; re-run green; sha256 7e023f06b1b0f89da618aa550dadb003e9bea8ee39c2076958549b42efa02ee3
  - mutation: `'.order_by(Stock.company_code, Stock.product_code)'` -> `'.order_by(Stock.product_code)'` (order by product_code only)
  - test: `…/integration/test_stock_list.py::test_fs15_lists_stock_views_with_derived_available_units_pages_filters_and_below_threshold_without_locking_or_mutating`
  - failure: services/fulfillment/tests/integration/test_stock_list.py:27: in test_fs15_lists_stock_views_with_derived_available_units_pages_filters_and_below_threshold_without_lockin ⏎ E   AssertionError: assert [('BBB-CO', '...O', 'PRD-Z9')] == [('AAA-CO', '...O', 'PRD-A1')] ⏎ E     
- **H11b-inverted-threshold** — RED (exit 1); cmp identical; re-run green; sha256 7e023f06b1b0f89da618aa550dadb003e9bea8ee39c2076958549b42efa02ee3
  - mutation: `'Stock.units - Stock.reserved_units < Stock.low_stock_threshold'` -> `'Stock.units - Stock.reserved_units >= Stock.low_stock_threshold'` (invert the threshold comparison)
  - test: `…/integration/test_stock_list.py::test_fs15_lists_stock_views_with_derived_available_units_pages_filters_and_below_threshold_without_locking_or_mutating`
  - failure: services/fulfillment/tests/integration/test_stock_list.py:57: in test_fs15_lists_stock_views_with_derived_available_units_pages_filters_and_below_threshold_without_lockin ⏎ E   AssertionError: assert [('AAA-CO', '...O', 'PRD-A1')] == [('AAA-CO', 'PRD-Z9')] ⏎ E     
- **H11c-list-locks** — RED (exit 1); cmp identical; re-run green; sha256 7e023f06b1b0f89da618aa550dadb003e9bea8ee39c2076958549b42efa02ee3
  - mutation: `'.limit(page_size)'` -> `'.limit(page_size)\n                    .with_for_update()'` (add with_for_update())
  - test: `…/integration/test_stock_list.py::test_a_list_is_answered_while_a_test_transaction_holds_a_listed_row_for_update`
  - failure: /home/juanpabloperez/.local/share/uv/python/cpython-3.14.8-linux-x86_64-gnu/lib/python3.14/asyncio/tasks.py:486: in wait_for ⏎ services/fulfillment/tests/integration/conftest.py:350: in call ⏎ .venv/lib/python3.14/site-packages/nats/aio/client.py:1142: in request
- **C6a-key-by-aggregate-id** — RED (exit 1); cmp identical; re-run green; sha256 6c7c1711d8b028a7501227e2b3b07f6fc82065c1944c7b7482caaf259f00d869
  - mutation: `'key=str(row.correlation_id).encode("utf-8"),'` -> `'key=str(row.aggregate_id).encode("utf-8"),'` (key by aggregate_id in the relay copy's wire.py; the C3 parity test is red for the same edit, record
  - test: `…/integration/test_fulfillment_outbox_relay.py::test_fs16_publishes_a_reserve_transactions_fact_to_the_fulfillment_topic_keyed_by_correlation_id_and_stamps_it_only_after_acknowledgement`
  - failure: services/fulfillment/tests/integration/test_fulfillment_outbox_relay.py:130: in test_fs16_publishes_a_reserve_transactions_fact_to_the_fulfillment_topic_keyed_by_correlat ⏎ E   ValueError: not enough values to unpack (expected 1, got 0)
- **C6b-publish-to-orders-topic** — RED (exit 1); cmp identical; re-run green; sha256 ca943a4d348ff155a1db0cddaa4766cf45d0693adc0b5d8d7cf023ede383c889
  - mutation: `'FULFILLMENT_FACTS_TOPIC,'` -> `"'otc.orders.facts.v1',"` (sibling substitution: publish to the Orders topic)
  - test: `…/integration/test_fulfillment_outbox_relay.py::test_fs16_publishes_a_reserve_transactions_fact_to_the_fulfillment_topic_keyed_by_correlation_id_and_stamps_it_only_after_acknowledgement`
  - failure: services/fulfillment/tests/integration/test_fulfillment_outbox_relay.py:130: in test_fs16_publishes_a_reserve_transactions_fact_to_the_fulfillment_topic_keyed_by_correlat ⏎ E   ValueError: not enough values to unpack (expected 1, got 0)
- **C6c-parity-also-red-for-the-key-edit** — RED (exit 1); cmp identical; re-run green; sha256 6c7c1711d8b028a7501227e2b3b07f6fc82065c1944c7b7482caaf259f00d869
  - mutation: `'key=str(row.correlation_id).encode("utf-8"),'` -> `'key=str(row.aggregate_id).encode("utf-8"),'` (the same wire.py edit against C3's parity guard)
  - test: `tests/architecture/test_outbox_copy_parity.py::test_every_listed_module_is_a_faithful_copy_of_its_canonical`
  - failure: tests/architecture/test_outbox_copy_parity.py:154: in test_every_listed_module_is_a_faithful_copy_of_its_canonical ⏎ E   assert ['infrastruct..."utf-8"),\']'] == [] ⏎ E     
- **D5a-swap-the-two-reads** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `'rows = await self._lock_stock_rows([(company_code, code) for code in product_codes])\n        reservations = await self._lock_reservations_of(order_reference)\n        return LockedStock(\n         
  - test: `…/integration/test_stock_repository.py::test_fs19_the_reservation_read_made_after_the_stock_lock_sees_a_reservation_committed_while_it_waited`
  - failure: services/fulfillment/tests/integration/test_stock_repository.py:100: in test_fs19_the_reservation_read_made_after_the_stock_lock_sees_a_reservation_committed_while_it_wai ⏎ E   AssertionError: the reservation committed while the lock waited is seen ⏎ E   assert [] == [UUID('35d8ea...1b16a64823a')]
- **D5b-repeatable-read-first-test** — RED (exit 1); cmp identical; re-run green; sha256 34f9bd11c09570624aebf99de9f754f3baa2729e80db7cfad7b09688b70cf0b3
  - mutation: `'"isolation_level": "READ COMMITTED"'` -> `'"isolation_level": "REPEATABLE READ"'` (pin REPEATABLE READ: the lock itself raises 40001, surfaced as StoreUnavailableError)
  - test: `…/integration/test_stock_repository.py::test_fs19_the_reservation_read_made_after_the_stock_lock_sees_a_reservation_committed_while_it_waited`
  - failure: .venv/lib/python3.14/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:605: in _prepare_and_execute ⏎ .venv/lib/python3.14/site-packages/asyncpg/prepared_stmt.py:177: in fetch ⏎ .venv/lib/python3.14/site-packages/asyncpg/prepared_stmt.py:268: in __bind_execute
- **D5c-repeatable-read-second-test** — RED (exit 1); cmp identical; re-run green; sha256 34f9bd11c09570624aebf99de9f754f3baa2729e80db7cfad7b09688b70cf0b3
  - mutation: `'"isolation_level": "READ COMMITTED"'` -> `'"isolation_level": "REPEATABLE READ"'` (pin REPEATABLE READ: the second test names the level)
  - test: `…/integration/test_stock_repository.py::test_fs19_every_stock_transaction_runs_at_read_committed`
  - failure: services/fulfillment/tests/integration/test_stock_repository.py:115: in test_fs19_every_stock_transaction_runs_at_read_committed ⏎ E   AssertionError: assert 'repeatable read' == 'read committed' ⏎ E     
- **D6-scoped-reservation-read** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `"['        rows = await self._lock_stock_rows([(company_code, code) for code in product_codes])\\n        reservations = await self._lock_reservations_of(order_reference)\\n        return LockedStock
  - test: `…/integration/test_stock_repository.py::test_the_reserve_lock_returns_every_reservation_of_the_order_including_products_outside_the_request`
  - failure: services/fulfillment/tests/integration/test_stock_repository.py:134: in test_the_reserve_lock_returns_every_reservation_of_the_order_including_products_outside_the_reques ⏎ E   AssertionError: assert [] == [(UUID('4108f...'), 'PRD-A1')] ⏎ E     
- **D7a-mapper-skips-reserved-units-decrease** — RED (exit 1); cmp identical; re-run green; sha256 9028d00c4985f67cbc8cba2ebc76309b1b543a0d061a0092d02c8ec53ebafe20
  - mutation: `'if row.reserved_units != item.reserved_units:'` -> `'if row.reserved_units < item.reserved_units:'` (the mapper skips reserved_units on release)
  - test: `…/integration/test_stock_repository.py::test_fs12_reserved_units_equals_the_sum_of_reserved_reservation_units_after_every_committed_operation`
  - failure: services/fulfillment/tests/integration/test_stock_repository.py:181: in test_fs12_reserved_units_equals_the_sum_of_reserved_reservation_units_after_every_committed_operat ⏎ E   AssertionError: after a release ⏎ E   assert [<Record comp...1 expected=5>] == []
- **D7b-writer-own-session** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `"['        await self._outbox.write(self._session, events)\\n', 'from sqlalchemy import select\\n']"` -> `"['        _other = async_sessionmaker(self._session.bind)()\\n        await self._outbox.wri
  - test: `…/integration/test_stock_repository.py::test_a_failure_after_save_inside_run_leaves_no_stock_change_no_reservation_and_no_outbox_row`
  - failure: services/fulfillment/tests/integration/test_stock_repository.py:241: in test_a_failure_after_save_inside_run_leaves_no_stock_change_no_reservation_and_no_outbox_row ⏎ E   AssertionError: no outbox row ⏎ E   assert [{'id': UUID(...2cf7a'), ...}] == []
- **D9a-update-stock-values** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `'await self._session.flush()'` -> `'await self._session.flush()\n        await self._session.execute(update(Stock).values(units=1))'` (add update(Stock).values(units=...) to stock_repository.py: the 
  - test: `tests/architecture/test_write_path_population.py::test_every_write_path_in_the_service_is_a_classified_literal[fulfillment]`
  - failure: tests/architecture/test_write_path_population.py:392: in test_every_write_path_in_the_service_is_a_classified_literal ⏎ E   AssertionError: services/fulfillment/src has an unclassified write path (or lost a classified one, or gained a second occurrence of one): add it to EXPECTED with its  ⏎ E   assert {'infrastruct...e'): 2}), ...} == {'infrastruct...d'): 1}), ...}
- **D9b-on-conflict-insert** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `'await self._session.flush()'` -> `'await self._session.flush()\n        await self._session.execute(pg_insert(Stock).on_conflict_do_nothing())'` (an on_conflict_do_nothing insert: ledger L6)
  - test: `tests/architecture/test_write_path_population.py::test_every_write_path_in_the_service_is_a_classified_literal[fulfillment]`
  - failure: tests/architecture/test_write_path_population.py:392: in test_every_write_path_in_the_service_is_a_classified_literal ⏎ E   AssertionError: services/fulfillment/src has an unclassified write path (or lost a classified one, or gained a second occurrence of one): add it to EXPECTED with its  ⏎ E   assert {'infrastruct...e'): 2}), ...} == {'infrastruct...d'): 1}), ...}
- **I1-drop-stock-lock** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `'.with_for_update()\n            )\n            if row is not None:'` -> `')\n            if row is not None:'` (drop with_for_update() from the reserve's stock lock: both read, both decide accepted)
  - test: `…/integration/test_stock_reserve_race.py::test_fs6_two_concurrent_reserves_for_the_last_units_yield_exactly_one_stock_reserved_and_one_stock_rejected`
  - failure: services/fulfillment/tests/integration/test_stock_reserve_race.py:64: in test_fs6_two_concurrent_reserves_for_the_last_units_yield_exactly_one_stock_reserved_and_one_stoc ⏎ E   AssertionError: exactly one wins the last units: {1: {'outcome': 'accepted', 'orderReference': 'ORD-000041', 'reservations': [{'reservationId': 'e023bb00-0620-4393-ba ⏎ E   assert ['accepted', 'accepted'] == ['accepted', 'rejected']
- **I2-check-reserves** — RED (exit 1); cmp identical; re-run green; sha256 346721e0af70f6d6c937fb8370c6ea5e5bd66e660ba1c1c9ccb259016ae4b157
  - mutation: `"['        return await self._scope.reads.availability(\\n            query.company_code, [(line.product_code, line.requested) for line in query.lines]\\n        )\\n', 'from otc_fulfillment.applicat
  - test: `…/integration/test_stock_reserve_race.py::test_fs7_a_line_reported_sufficient_by_stock_check_is_rejected_by_a_later_reserve_once_another_order_took_the_units`
  - failure: services/fulfillment/tests/integration/test_stock_reserve_race.py:95: in test_fs7_a_line_reported_sufficient_by_stock_check_is_rejected_by_a_later_reserve_once_another_or ⏎ E   AssertionError: assert 'rejected' == 'accepted' ⏎ E     
- **I3-lock-in-request-order** — RED (exit 1); cmp identical; re-run green; sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9
  - mutation: `'for company_code, product_code in distinct_stock_keys(keys):\n            row = await self._session.scalar('` -> `'for company_code, product_code in dict.fromkeys(keys):\n            row = await sel
  - test: `…/integration/test_stock_reserve_race.py::test_fs19_two_multi_line_reserves_naming_the_same_products_in_opposite_order_both_succeed_with_no_deadlock`
  - failure: services/fulfillment/tests/integration/test_stock_reserve_race.py:134: in test_fs19_two_multi_line_reserves_naming_the_same_products_in_opposite_order_both_succeed_with_n ⏎ E   AssertionError: no transaction was a deadlock victim: ['stock transaction was a deadlock victim (SQLSTATE 40P01); re-running it from the start'] ⏎ E   assert [<LogRecord: ...m the start">] == []
- **I4-one-attempt** — RED (exit 1); cmp identical; re-run green; sha256 34f9bd11c09570624aebf99de9f754f3baa2729e80db7cfad7b09688b70cf0b3
  - mutation: `"DEADLOCK_ATTEMPTS = 3  # total attempts, the relay's"` -> `"DEADLOCK_ATTEMPTS = 1  # total attempts, the relay's"` (DEADLOCK_ATTEMPTS = 1: the reply becomes UNAVAILABLE, zero outbox rows)
  - test: `…/integration/test_stock_deadlock_retry.py::test_fs23_a_real_40p01_on_a_reserve_is_rerun_and_the_reserve_is_accepted_once`
  - failure: services/fulfillment/tests/integration/test_stock_deadlock_retry.py:65: in test_fs23_a_real_40p01_on_a_reserve_is_rerun_and_the_reserve_is_accepted_once ⏎ E   AssertionError: [] ⏎ E   assert 0 == 1

## Round 2 (fix round after the round-1 rejection, `progress/review_fulfillment_stock.md` § 6 / § 7)

**No file under `services/*/src/`, `packages/` or `tests/architecture/` was changed permanently** (every `src` edit was an arm, restored by `cp` + `cmp`). Arm script `.arm/fix17/arms.py` (helper `.arm/fix17/rarm.py`: process-group timeout, backup with sha256, `cmp`, cache clear, green re-run), backups in `.arm/fix17/bak/`, verbatim outputs `.arm/fix17/logs/<arm>.red.txt|.green.txt`, records appended to `.arm/fix17/log.md`. Unit under test in every arm: the one named test.

### What changed

| Item | Change | Test(s) |
|---|---|---|
| D1 (R1) | the SA-4 lock's read order, D5's construction applied to `lock_order_items` | `integration/test_stock_repository.py::test_fs25_the_release_lock_reads_the_orders_reservations_only_after_the_stock_lock_and_sees_a_reservation_committed_while_it_waited` (proves FS25 / SA-4, R-row of the release lock). The order already holds a reservation; the test's connection inserts a further one and holds; the lock is seen ungranted; after the commit both ids must be returned |
| D2 (M1) | FS24 at the application -> domain seam | `unit/test_stock_reservation_service.py::test_fs24_the_reserve_uses_the_id_port_for_every_reservation_id_and_the_reserved_facts_event_id` (ids `0x9001`, `0x9002`, event `0x9003`, in minting order) and `::test_fs24_the_release_uses_the_id_port_for_the_released_facts_event_id` (`0x9001`). `test_fs5_…` no longer relies on `ids.minted == 0` (blind under M1): it asserts the item's snapshot unchanged, `reservations == ()` and `domain_events == ()`, with the reason in a comment; the two FS24 tests cover the port |
| D3 (M9) | the defensive branch | `integration/test_stock_repository.py::test_the_release_lock_raises_concurrent_reservation_change_when_the_order_holds_a_reservation_on_a_stock_row_outside_the_keys`, with a control row (all keys given -> accepted, two reservations) |
| D6 | FS25's lock wait fails naming the claim | `integration/test_stock_release_idempotency.py::test_fs25_a_release_waits_for_…`: `wait_for_lock_waiters(..., deadline_seconds=10)` wrapped in `pytest.fail("the release never waited on the held stock row: …")`. `conftest.py` untouched |
| D5 | stale line citations corrected (substance unchanged) | `design.md` (lines 26, 31, 40, 103, 104, 353, 395) and `requirements.md` (39, 63, 91), each re-verified against the file: `models.py` classes 59 – 144, `QUANTITY_COLUMNS` 151 – 157, Orders `composition.py` 100 – 464 (single-relay guard 181 – 230), `nats_saga_commands.py` terminal set 65 – 75, header dict 143 – 146, classification `if error.code in TERMINAL_RPC_ERROR_CODES` at 174, `writer.py` `session.add` 57 and `flush` 72. Also design § 3 L1 and § 17 ids 49 / 79 now name the new guards |
| D7 | record | § 8.1 filled (points at § 16 and this section); G8's description restated truthfully (F-g alone; the F-j half was inert; the real F-j pipeline is the reviewer's `Q6`, RED by the WIRE clause); § 7 id 49 / id 79 dispositions and § 4 L1 restated in place |

### Arms (all in `.arm/fix17/`)

| Arm | Mutation | Red (verbatim, the line naming the claim) | Backup sha256 | Green re-run |
|---|---|---|---|---|
| **R1** | `stock_repository.py:101-102` swap the two reads in `lock_order_items` | `AssertionError: the lock read the order's reservations BEFORE the stock lock was granted: the reservation committed while it waited is missing` | `1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9` | 1 passed, `cmp` identical |
| **M9** | `:104` `if False and any(...)` | `Failed: DID NOT RAISE ConcurrentReservationChangeError` | same | 1 passed |
| **M1a** | `stock_reservation.py:115` `new_id=scope.ids.new` -> `UniqueId.new` (reserve) | `AssertionError: assert [UniqueId(val…)] == [UniqueId(val…0000009002')]` at the reservation-ids assertion (first id a random uuid, expected `…9001`) | `feead357afe950ba82f8cf8459c553540f52c54eb9c343737cc4a8cc9df23d3d` | 1 passed |
| **M1b** | `:170` same substitution (release) | `AssertionError: the released fact's event id comes from the id port` | same | 1 passed |
| **I5** (re-run, D6) | drop `.with_for_update()` in `_lock_stock_rows` | `Failed: the release never waited on the held stock row: no locking SELECT on stock was seen ungranted, so the release does not take the stock lock (FS25)` (chained after the `TimeoutError`) | `1088a62c…dddc9` | 1 passed |
| **D5a** (re-run) | swap the two reads in `lock_for_reserve` | `AssertionError: the reservation committed while the lock waited is seen` | same | 1 passed |

Defeat rows applied: 1 (delete: M9), 2/3 (substitute a sibling producer of the same type: M1, R1's reordering), 9 (the `minted == 0` premise was stale; replaced).

### `quality.sh`

Developer stack down (only `otcpy-n8n`). Exit 0, **2690 passed in 285.58 s** (script 308 s; the J4 reference was 2686 passed, +4 = the 4 new tests), coverage 98 % overall / 99 % domain, web build and Vitest green. A first run stopped at `ruff format` and a second at `mypy --strict` (three narrowings in the new unit tests, fixed with `assert … is not None` / `isinstance`); the reported run is the third. `./init.sh` exits 0.

### Not done

Review § 7 item 7 (D4, feature 18's acceptance item) is the leader's and was not touched. The optional host-level `UNAVAILABLE` reply for D3 was not added (the mapping row is unit-tested and the raise is now guarded at the repository). `specs/shared/test-matrix.md` unchanged: the new tests guard FS rows, not R rows.
