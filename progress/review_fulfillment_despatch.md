# Review — feature 18 `fulfillment_despatch` (phase 9, `sdd: false`, full group), round 1

**Verdict: APPROVED** (0 blocking defects; 2 non-blocking items with disposition FIX now, light and test-only; 1 accepted naming nit; 2 record notes).

Reviewer: Opus, 2026-10-08, ≈10:49 → ≈11:12 local (≈23 min). Inputs: `progress/brief_review_fulfillment_despatch.md` (premise-checked, 0 false), `progress/impl_fulfillment_despatch.md`, `feature_list.json` id 18 (three acceptance items), `specs/shared/` R36 / F6–F8 / `asyncapi.yaml`, `specs/fulfillment_stock/design.md` hand-over sections, #7 and #8 checkouts. The developer stack stayed stopped (`docker ps`: `otcpy-n8n` only, before and after; note it reported `unhealthy` at 11:06, not caused by this review: no test here touches it).

## What I ran (verification, not repetition)

| Run | Result |
|---|---|
| `./quality.sh` in full (the claim under test is a full-suite claim: the gate that closes Phase 9) | **exit 0, 341 s, `2784 passed in 302.11s`**, domain coverage TOTAL 99 %, `quality.sh: all gates passed` (`.arm/review18/quality.log`). Reconciles with the implementer's 2784 (+94 over 2690). |
| `./init.sh` | exit 0; 5d shared spec byte-identical to #8 and #7 across 6 files (`.arm/review18/init.log`) |
| `uv run lint-imports` | `Contracts: 11 kept, 0 broken` |
| the nine new test files' unit half + `test_stock_responder.py` | 99 passed |
| the four new integration files + `test_fulfillment_host_lifespan.py` (testcontainers, stack down) | 44 passed in 24.67 s, both J4 legs included |
| `tests/architecture/{test_registration_behaviour,test_write_path_population,test_fulfillment_rpc_error_retryability,test_money_guard}.py` | 387 passed |
| 21 reviewer arms (R1–R21), every one with `cp` backup in `.arm/review18/bak/`, the ONE named test in its own session (`start_new_session` + `killpg` on timeout), restore by `cp` + `cmp` (all `cmp=True`), `__pycache__` / `.mypy_cache` cleared, the same test re-run green | 21 RED, 0 survived, none hung (longest 20.3 s). Full output per arm in `.arm/review18/out/R*.txt`; helper `.arm/review18/arm.py` |

Every restored file equals the implementer's submitted content: sha256 of the backups `despatch_creation.py 2845956…`, `despatch_advice.py 4565242…`, `despatch_repository.py 6f87627…`, `stock_transactions.py ecce609…`, `stock_repository.py 1088a62…`, `stock_rpc_errors.py 57a9b2b…`, `stock_wire.py e0f71b4…`, `payloads.py 7a310e0…`, `sequences.py 626545d…`, `composition.py 75625c7…`, `handlers.py 80d8fe3…` — identical to the values in the implementer's appendix, and `cmp`-identical to the files on disk after the last arm.

## The reviewer's arms (verbatim first failure line)

| Arm | Family | Site (brief Q9 site) | Mutation | Test | Failure |
|---|---|---|---|---|---|
| R1 | corrupt wire field | domain → outbox payload | `despatched_payload` `company_code=event.retailer_code` | `test_despatch_payload.py::test_r36_the_despatched_fact_becomes_its_envelope_and_payload_with_every_field_equal_to_the_supplied_value` | `{'companyCode': 'RET-77'} != {'companyCode': 'CMP-88'}` |
| R2 | corrupt wire field (order) | aggregate → fact | the fact's lines built from `lines` (minting order) instead of `ordered` | `test_despatch_store.py::test_fs24_every_id_…_in_minting_order` | `At index 0 diff: ('PRD-A1', 3) != ('PRD-A1', 4)` at line 369 (the fact payload's lines) |
| R3 | sibling identifier | responder → command (mapper) | `decode_despatch` swaps `correlation_id` / `request_id` | `test_despatch_create.py::test_r36_consumes_…_exactly_one_despatched_fact` (real host) | `'…da05' == '…d0d0'` at line 126 (the fact's `correlation_id`) |
| R4 | duplicate the call | allocator call | `next_reference()` called twice | same | `{'despatchReference': 'DES-000002'} != {'despatchReference': 'DES-000001'}` |
| R5 | corrupt supplied value | lock-method call | `lock_order_items(…, keys[:1])` | `test_despatch_race.py::test_fs25_a_despatch_waits_…` (hold on the SECOND row) | `Failed: the despatch never waited on the held stock row: … does not take the SA-4 lock (FS25)` |
| R6 | corrupt field | reload mapper | `load_despatch` `retailer_code=row.company_code` | `test_fs24_every_id_…` | `retailer_code: 'ACME-CO' != 'RET-9'` (the repeat's snapshot vs the creation's) |
| R7a | sibling code (terminal) | error mapper | `NoReservedStockForDespatchError` → `NOT_FOUND` | `test_despatch_race.py::test_sa4_release_wins_…` | `assert 'NOT_FOUND' == 'PRECONDITION_FAILED'` |
| R7b | sibling code (transient) | error mapper | `ConcurrentDespatchChangeError` → `INTERNAL_ERROR` | `test_despatch_wire.py::test_f8_consumed_reservations_without_an_advice_are_unavailable_…` | `<Code.internal_error> is <Code.unavailable>` |
| R8 | sibling code (terminal) | retryability guard | `ConcurrentDespatchChangeError` → `PRECONDITION_FAILED` | `test_fulfillment_rpc_error_retryability.py::test_fs21_every_transient_store_failure_…` | `ConcurrentDespatchChangeError(…) is answered PRECONDITION_FAILED, which Orders' saga adapter treats as a terminal rejection` |
| R9 | F-g + F-j as one pipeline | composition | the four command handlers self-register via `__init_subclass__` (incl. `CreateDespatchHandler`), drained by a helper loop | `test_registration_behaviour.py` | `WIRE: 4 registrations share one statement (composition.py:114): [… 'CreateDespatchCommand']` |
| R10 | delete | SA-4 lock | `.with_for_update()` removed from `_lock_stock_rows` | `test_sa4_despatch_wins_…` | `Failed: fulfillment.despatch.create never waited on the held stock row: it does not take the lock` (18.9 s, no hang) |
| R11 | reorder | SA-4 read order (#8 id 79) | `lock_order_items` reads reservations before the stock rows | `test_despatch_store.py::test_fs25_the_despatch_lock_reads_…` | `the despatch read the order's reservations BEFORE the stock lock was granted: the reservation committed while it waited was not consumed` |
| R12 | move out of the transaction | handler → transaction | `save` commits the session after the outbox write, then the injected fault | `test_j4_a_failure_after_the_advice_was_saved_…` | `AssertionError: no advice for the faulted order` (`DES-000002` survived) |
| R13 | delete | `DES-` allocator | `LOCK_DESPATCH_SEQUENCE` without `FOR UPDATE` | `test_concurrent_allocations_…_gap_free_and_unique` | `duplicate references: ['DES-000001', 'DES-000002', 'DES-000002', …]` |
| R14 | corrupt | `DES-` seed | seed `MAX + 0` | `test_seeding_over_a_non_empty_despatches_table_…` | `'DES-000042' == 'DES-000043'` |
| R15 | delete | F8 layer 2 | in-lock re-read replaced by `None` | `test_f8_two_concurrent_despatches_…` | loser `{'code': 'UNAVAILABLE', 'message': 'order ORD-000042 holds consumed reservations but has no despatch advice'}`; `exactly one repeats` |
| R16 | delete | F8 layer 1 | fast path deleted | `test_despatch_store.py::test_f8_the_fast_path_answers_a_repeat_from_a_plain_read` | bare `TimeoutError` (see N2) |
| R17 | sibling source | application → domain hand-over (#8 id 49) | `new_id=UniqueId.new` | `test_fs24_every_id_…` | `exactly the five supplied ids were used` |
| R18 | substitute source | repository line ids | `id=uuid4()` in `save` | `test_fs24_every_id_…` | `(UUID('78be0…'), 'PRD-A1', 3) != (UUID('…31'), 'PRD-A1', 4)` |
| R19 | clear on the rollback path | transaction | `despatches.clear_saved_events()` before `work` | `test_despatch_transactions.py::test_the_despatch_events_are_kept_when_the_attempt_rolls_back` | `a rolled-back attempt keeps its events` (see record note RN1) |
| R20 | sibling isolation level | #8 id 54 pin | `READ COMMITTED` → `REPEATABLE READ` | `test_f8_two_concurrent_despatches_…` | loser `{'code': 'UNAVAILABLE', 'message': 'the stock store is temporarily unavailable (40001)'}` |
| R21 | delete the emission | repository → outbox | the outbox write removed from `save` | `test_r36_consumes_…_exactly_one_despatched_fact` | `ValueError: not enough values to unpack (expected 1, got 0)` at line 121 (see N1) |

Both mutation families on the fact were attacked: deletion (R21) and payload-field corruption on the wire (R1, R2, R3), plus the sibling family at every code site (R7a, R7b, R8, R20).

## The brief's questions, ruled

1. **F8's layers.** With the code as built the concurrent pair yields exactly one `created: true`, one `created: false`, one advice, two lines, one fact whose `causation_id` is the creator's, `next_value` 2 (baseline green). Without the re-read the loser answers `UNAVAILABLE` (R15), under `REPEATABLE READ` `UNAVAILABLE (40001)` (R20); the implementer's I3b (`PRECONDITION_FAILED`, terminal) shows why the `consumed` branch matters. **"`UNAVAILABLE` then a retry that finds the advice" is an acceptable last line**: `UNAVAILABLE` and `INTERNAL_ERROR` are transient in `TERMINAL_RPC_ERROR_CODES` (`services/orders/src/otc_orders/infrastructure/messaging/nats_saga_commands.py:65-75`), the retry takes the fast path, and F8's success reply follows; no second fact is possible in any layer (the unique key, proved by `test_f8_the_unique_key_refuses_…`, armed I18). Mapping `23505` to the existing advice is not required: F8 (`domain-model.md:313`) requires at most one advice and an idempotent success on a repeat, which the re-read delivers; #7 left `23505` unmapped (`INTERNAL_ERROR`), #8's `StockErrorMapper.cs:56-71` has no unique-violation row either (bare `SqlException` → `UNAVAILABLE`, else `INTERNAL_ERROR`). #8 id 54's ledger row is L4, present and armed (I4_v2, and R20 re-run here).
2. **Id provenance.** Population by search over the despatch sources: `grep -rn "new_id()\|UniqueId.new\|uuid4\|ids.new\|uuid1\|UniqueId(uuid\|UUID(int"` over `despatch_creation.py, order_despatch.py, despatch_advice.py, despatch_repository.py, despatch_number_allocator.py, stock_reads.py, stock_transactions.py, stock_wire.py, stock_responder.py, payloads.py, events.py, snapshot.py` → 5 hits: `order_despatch.py` advice id, line ids (comprehension), event id (mint sites); `despatch_creation.py` `new_id=scope.ids.new` (the hand-over); `despatch_repository.py:34` `UniqueId(UUID(int=value.int))` (classification: a type conversion of a loaded id, not a mint). Three mint sites plus one hand-over, each asserted by EQUALITY with a supplied value in minting order and armed separately (D1, D2, D3, D4/D4b crossed, D5 extra mint, A1 / R17 hand-over, I6 / R18 and I7_v2 repository). I read every new test's assertions back against its name (`test_despatch.py` all 15, `test_despatch_creation_service.py` 10, `test_despatch_store.py` 7, `test_despatch_create.py` 7, `test_despatch_race.py` 3): no contradiction. #8's round-1 defect did not recur.
3. **Atomicity by fault injection.** Both legs re-run green (J4 and its control); production arm R12 (an early commit inside `save`) turns J4 red on the surviving advice; the implementer's I5 covers the outbox-on-its-own-session shape. The probe compares all six tables whole, so it discriminates.
4. **SA-4 in both outcomes + FS25's despatch half.** Constructed with a held lock and `pg_stat_activity` waits; R10 (lock removed) and R5 (only the first key locked) fail at the wait with messages naming the SA-4 lock, R11 (reads swapped) fails naming the read order. None hung.
5. **`DES-` allocator.** Orders' six tests: all six ported (one re-aimed at `SqlAlchemyStockTransactions.run`, the real path), none N/A — I confirmed against `services/orders/tests/integration/test_order_number_allocator.py`. Re-ran two arms: R13 and R14, both red.
6. **Equivalent mutants.** P2 is genuinely equivalent: `wire_instant` truncates and the serializer writes `.mmm` from the same instant, and the instant is already whole-millisecond because `SystemClock.now()` returns `wire_instant(datetime.now(UTC))` (a parity-guarded copy of Orders' clock, guarded by `services/orders/tests/unit/test_system_clock.py` and `tests/architecture/test_outbox_copy_parity.py`); the claim it was meant to guard (payload date = envelope date) is held by `test_r36_the_despatch_date_in_the_payload_is_the_same_millisecond_as_the_envelopes` against P2b. X9 is equivalent at the integration level by design (the in-lock re-read gives the same reply); the fast-path claim is guarded by the unit `test_f8_the_fast_path_returns_the_existing_advice_without_a_transaction_or_a_lock` (A3) and by `test_f8_the_fast_path_answers_a_repeat_from_a_plain_read`, which I armed myself by deleting the fast path (R16: red).
7. **Deviations.** (a) Both headers required: `RpcHeaders` (`asyncapi.yaml:2816`) requires only `traceparent`, but `x-request-id` is described as the attempt identity and R12 needs `correlationId` / `causationId` on the fact; #7 (`apps/fulfillment/src/presentation/despatch.controller.ts:31-43`) and #8 require both, as do 17's reserve and release (`stock_responder.py:84,95`). Accepted, consistent. (b) Line ids minted in the domain: a strengthening over both predecessors, guarded (R18). (c) `OrderDespatched(StockEventBase)`: see N3. (d) Edits to 17's tests: `test_stock_responder.py` replaced `[1] * 5` / `== 5` with `len(ROUTES)` and added `assert len(ROUTES) == 6` (tighter, not weaker); `test_fulfillment_host_lifespan.py`'s equality list gained one entry; `TABLES["fulfillment"]` gained `CreateDespatchCommand` (seen red before the edit, `.arm/impl18/registration_red_before.txt`); the write-path census gained two classified files; the retryability population grew (`>= 8` → `>= 9`). No guard weakened; R9 (F-g + F-j) and R8 (retryability) re-run against the new code, both red.
8. **Error table.** Every row in impl § 4 checked against `stock_rpc_errors.py` and #8's mapper: `VALIDATION_FAILED` (terminal), `PRECONDITION_FAILED` + `details.orderReference` for `NoReservedStockForDespatchError` (terminal; #7 and #8 agree), `UNAVAILABLE` for `ConcurrentDespatchChangeError` (transient; #8's, #7 `INTERNAL_ERROR`, also transient), `DOMAIN_ERROR` for F6 (terminal, defensive), `INTERNAL_ERROR` for `23505` and anything else (transient, text not leaked). Sibling substitutions R7a, R7b, R8 each red; the implementer's E1–E3 cover the rest.
9. **Unplanned mutations.** Eleven sites of my choosing across the six named seams (R1–R6, R12, R16–R19, R21): all red. #7's lesson and 17's round-1 D1/D2 shape did not recur.

**Dev-data side effect (the leader's reading confirmed, by code, not by running):** Orders advances only on the fact: `step_table.py:162-167` maps `order.despatched.v1` to `Advance(precondition=CONFIRMED, …)`; the RPC reply does not advance the order. Fulfillment answers a later `despatch.create` for `ORD-000007` from the fast path with `created: false` and writes no fact (`despatch_creation.py:104-106`, guarded by `test_f8_a_repeated_despatch_…`), and the original fact's `event_id` is already in `otc_orders.processed_events`, so a redelivery is skipped too. **Once `ORD-000007` reaches `confirmed`, it stalls there.** The next phase's live brief must avoid `ORD-000007` (and remember `IBERFOODS` `PRD-0001` 498 / 4, `PRD-0002` 492 / 0) or recreate `otc_fulfillment` from the seed. Not a code finding, and not rooted in `specs/shared/`: the walkthrough forced a despatch out of saga order.

## `R<n>` → test mapping (verified)

R36 is the only requirement row this feature owns (`test-matrix.md:141`, column 5 `DONE`). The twelve tests it names all exist (one definition each, by `grep -rln "def <name>"`), all ran green, and each is tied to a red arm:

| Claim of R36 / F6–F8 | Test | Arm that turns it red |
|---|---|---|
| reservations move to `consumed`, both counters fall | `test_despatch.py::test_r36_consumes_every_reserved_reservation_…`; `test_despatch_create.py::test_r36_consumes_the_reservations_…` | D6, S1, S2, X3 (impl) |
| one advice, one fact via the outbox, the request's ids, the advice's id as aggregate | same integration test; `test_despatch_payload.py` | R1, R3, R4, R21; D14, I17, P1–P4 (impl) |
| no `reserved` reservation → nothing (never reserved / all released) | `test_r36_an_order_holding_no_reserved_reservation_…`, `test_r36_an_order_that_holds_no_reservation_…`, `test_r36_an_order_whose_reservations_were_all_released_…` | R7a; A4, A7, D10 (impl) |
| F6 | `test_f6_an_advice_without_a_line_is_refused_and_records_no_fact` (+ control) | D12 (impl) |
| F7 | `test_f7_every_line_traces_one_to_one_…` | D7 (impl), R2 |
| F8 repeat and concurrent pair | `test_f8_a_repeated_despatch_…`, `test_f8_two_concurrent_despatches_…`, `test_f8_the_unique_key_refuses_…` | R15, R16, R20; I18 (impl) |
| SA-4 race, both outcomes; FS25 despatch half | `test_sa4_release_wins_…`, `test_sa4_despatch_wins_…`, `test_fs25_a_despatch_waits_…`, `test_fs25_the_despatch_lock_reads_…` | R5, R10, R11 |
| atomicity | `test_j4_…` + control | R12; I5 (impl) |

Test-matrix arithmetic: row 4 `8 | 7 | 0 | 1`, total `63 | 31 | 1 | 31` (31 + 1 + 31 = 63); R61's API half still open, correctly.

## Ported-idiom ledger (impl § 3): claims checked, not existence

L1 (provenance): checked by the population search above and R17/R18. L2 (allocator): R13/R14. L3 (fast path): R16. **L4 (in-lock re-read under the pinned READ COMMITTED, #8 id 54)** — the row most likely to be assumed; probed both ways: green at `READ COMMITTED`, red at `REPEATABLE READ` (R20, `40001`), so the execution option demonstrably reaches the transaction. L5 (unique key): impl I18 plus the unit mapping. L6 (SA-4 reuse): `despatch_creation.py:70` calls `tx.repository.lock_order_items`, the method `stock.release` calls; R5, R10, R11. L7 (consume): impl S1–S3, D6. L8 (outbox in the transaction): R12, R21. L9 (reply shape): impl W5/W6. L10 (Python questions): `grep -n " / \|float\|Decimal"` over the five new source files → no hit (exit 1); `mypy --strict` clean inside `quality.sh`. Every "#7 relied on / #8 supplied" half carries a file and line; spot-checked #8 `StockErrorMapper.cs:49,56-57` and #7 `despatch.controller.ts:31-43`.

## `CHECKPOINTS.md`

C1 — harness: [x] five root files exist (init.sh); [x] `progress/current.md`, `history.md`; [x] seven agent definitions; [x] every agent declares its model or documents inheriting it; [x] `./init.sh` exit 0.
C2 — state: [x] at most one `in_progress` (none); [x] every status valid; [x] every `done` feature has passing tests (2784 passed); [x] `current.md`'s Feature line names the active feature (init.sh; body not re-read, the leader's file); [x] no `blocked` feature without a reason (none blocked in scope).
C3 — architecture: [x] `lint-imports` 11 kept, 0 broken (domain purity, independence, Kafka confinement); [x] no cross-service DB access (despatch reads only `otc_fulfillment` tables; Orders untouched); [x] shared runtime still the three packages; [x] no `domain` imports `otc_cqrs` (contract kept); [x] `shared_kernel` and `cqrs` `dependencies = []`; [x] no `float` / `Decimal` / `/` in the new domain (search above); [x] `despatch.create` is NATS RPC, `order.despatched.v1` a Kafka fact on `otc.fulfillment.facts.v1` (`asyncapi.yaml:124-148`); [x] no debug prints or bare TODOs in the five new sources (`grep "TODO\|print("` exit 1).
C4 — verification: [x] `./quality.sh` exit 0 (my run); [x] domain tests pure (imports of `test_despatch.py` and `unit/domain/conftest.py`: stdlib, pytest, `otc_fulfillment.domain`, `otc_shared_kernel` only); [x] integration on testcontainers with the stack down; [x] coverage domain 99 %, overall above 60 % (gate passed); [x] no Jest/Karma/Jasmine (`grep -i` of `apps/web/package.json` exit 1).
C5 — clean close: [x] no stray `*.tmp`/`*.orig`/`*.rej` (`git status --porcelain` filter, exit 1); [x] `history.md` entry with effort record (appended with this verdict); [x] `feature_list.json` 18 → `done` (this verdict, that line only); [x] manual test script = impl § 11 (the leader relays it); [x] no commit by any agent.
C6 — SDD: n/a for this `sdd: false` feature, except [x] R36 covered by named tests recorded in the matrix. (Spec-before-implementation commit order is the wrap-up's.)
C7 — second reuse: [x] `specs/shared/` byte-identical to #8 and #7 (init.sh 5d, `cmp`); [x] no deviation needing an `SA-n` (none found); [x] R36 is #7's id and the Python realisation satisfies it (arms above); n/a n8n and black-box API (not this feature's subject); [x] inherited findings accounted (below and in the history entry); [x] effort record honest (agent time and wall-clock, both baselines quoted from their files).

## Findings

**Blocking: none.**

**N1 (non-blocking; disposition FIX now, light, test-only, route to `test_maintainer`) — the fact-count assertion of the R36 happy path unpacks before it asserts.** `services/fulfillment/tests/integration/test_despatch_create.py:121`: `[fact] = facts_of(outbox, "order.despatched.v1")`. Deleting the emission (R21, and the implementer's own I17) fails with `ValueError: not enough values to unpack (expected 1, got 0)`, which does not name the claim (CLAUDE.md arming step 2; the same shape as feature 16's N1). Fix: `facts = facts_of(…); assert len(facts) == 1, "exactly one order.despatched.v1 in the outbox"` then unpack. Arm that proves it: R21 (remove `await self._outbox.write(self._session, advice.domain_events)` from `despatch_repository.py`) must fail with that message.

**N2 (non-blocking; disposition FIX now, light, test-only, same batch) — the fast-path test fails on a bare timeout.** `services/fulfillment/tests/integration/test_despatch_store.py:390-393` (`asyncio.wait_for(…, timeout=5)` inside the held-row block): with the fast path deleted (R16) or returning `None` (impl I15) the failure is a bare `TimeoutError`, not a message naming F8's fast path. Fix: catch `TimeoutError` and `pytest.fail("the repeat waited on the held stock row: F8's fast path did not answer before the transaction")`. Arm: R16 (delete the three fast-path lines at the top of `despatch_creation.create`) must fail with that message.

**N3 (ACCEPTED, NOT FIXED) — `OrderDespatched(StockEventBase)` is a misnomer** (`services/fulfillment/src/otc_fulfillment/domain/events.py:43,95`). Evidence: the base holds only the five envelope identity fields; no code branches on the base's name (`narrow` and `build_fact` match concrete classes under `assert_never`); a rename touches feature 17's three events and is cosmetic. Re-open trigger: the next event class added to `otc_fulfillment.domain.events`, or any code change to that module: rename to `FulfillmentEventBase` in the same change.

**RN1 (record note) — impl § 14 counts T3 as an "identity control" and never saw `test_the_despatch_events_are_kept_when_the_attempt_rolls_back` red.** The guard is real: my R19 (clear the despatch events on the rollback path) turns it red with its own message. Nothing owed; recorded so the arm count credits R19, not T3.

**RN2 (record note) — the stored `despatches.despatch_date` is written without `wire_instant`** (`despatch_repository.py:84`); the equality "stored = fact's `despatchDate` = reply's" rests on `SystemClock.now()` already truncating (guarded by Orders' `test_system_clock.py` plus the copy-parity test). Correct today; anyone injecting a sub-millisecond clock into the despatch path must route the instant through `wire_instant` first.

**No `specs/shared/` root cause** was found (the both-headers rule, the `23505` reply and the dev-data stall were each checked against the shared spec above), so no `SA-n` and no backlog entry is proposed.

## Inherited findings

- **#8 id 54** — avoided (L4; R20 and impl I4_v2).
- **#8 id 79** — avoided, despatch half (R5, R10, R11; the release half was 17's).
- **#8 id 49's lesson** ("count the sites when you add the seam") — avoided, with the count (3 mint sites + 1 hand-over, 0 in the repository; R17, R18, D1–D5).
- **#8's round-1 test-name defect** (`Assert.NotEqual` under a "minted by" name) — avoided (every provenance assertion is equality with a supplied value; read-back done).
- **#8 ids 45 / 47** (counter seed race and scan cost) — avoided (R13, R14; the constants are 17's).
- **#7's fault-injection proof** — followed, with its discriminating control (J4 + control; R12).
- Recurred: none. N1/N2 are the arming-message shape of feature 16's N1 (an assertion that fails without naming its claim), now in two despatch tests: a minor recurrence of #9's own feature-16 note, not of an #8 id.

## What must change before re-review

Nothing: APPROVED. N1 and N2 are owed now as one light, test-only batch (leader arms R21 and R16 against the new messages); N3 carries its re-open trigger.
