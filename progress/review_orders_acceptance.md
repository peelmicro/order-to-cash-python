# Review: feature 15 `orders_acceptance` (phase 8, `sdd: false`, full group), round 1

**Verdict: REJECTED.** Feature 15 is set back to `in_progress` (that line only).

The build is sound and most of it is well guarded. 40 reviewer mutations were run: 36 failed at least one named test and **3 survived**. One more defect was found by a direct probe of the boot-failure path. Two of the leader's questions (Q2, Q3) are findings that can be fixed now. All six are small, and none is wrong behaviour on the tested path. Every one is #8's defect class for this feature: the behaviour is correct and nothing would notice it being reverted, or (D-1) a hand-built property that no test drives. CLAUDE.md allows one more round without asking the maintainer.

## 0. What I ran, and what I did not

- **The feature's 15 test files, once, unmutated:** `216 passed in 38.36s` (developer stack down: `docker ps` showed only `otcpy-n8n`). These 216 are the 215 new tests plus the 1 pre-existing health test.
- **Counts:** I collected each file with `pytest --collect-only -q <file> | grep -c ::`: 21 + 45 + 6 + 21 + 10 + 2 + 17 + 35 + 6 + 12 + 16 + 1 + 11 + 6 + 7 = **216**. The pre-existing health test (`git show HEAD:services/orders/tests/test_orders_health.py | grep -c 'def test_'` gives 1) brings the new total to **215**. A whole-workspace collection gives `1867 tests collected`. So the implementer's 215 and 1867 reconcile. I could not re-derive the 1652 baseline independently, because the working tree carries four uncommitted features. The delta is consistent with it.
- **`uv run lint-imports`:** `Contracts: 11 kept, 0 broken.` `ruff check` and `ruff format --check` over `services/orders` and `tests/architecture`: clean (126 files). **`./init.sh`: exit 0.**
- **Not re-run:** the whole `./quality.sh` (mypy, coverage, the web gate). That claim is about the full suite, the implementer reports exit 0, 193 s, 1867 passed, and none of my findings depends on it. Instead I ran the 216 feature tests, 40 mutations over them, two direct probes and lint-imports.
- **Mutation protocol:** harness `scratchpad/rv/rv_arm.py`. For each mutation: `cp` a backup, one replacement (exactly one occurrence asserted), run all 15 files without `-x`, restore by copy, `filecmp` identical (every row printed `restored_identical: true`), delete that module's `.pyc`. Afterwards `sha256sum -c` over the 9 mutated files gave all `OK`, and I cleared their `__pycache__` entries again. No git command that writes the index or working tree was used.

## 1. CHECKPOINTS.md walk

**C1 — harness**
- [x] `AGENTS.md`, `CLAUDE.md`, `CHECKPOINTS.md`, `feature_list.json`, `init.sh` exist
- [x] `progress/current.md`, `progress/history.md` exist
- [x] `.claude/agents/` holds the seven roles (`ls`)
- [x] agent models declared (not changed by this feature; `init.sh` checks it)
- [x] `./init.sh` exits 0

**C2 — state**
- [x] at most one feature `in_progress`: feature 15 after this verdict. 16 is `spec_ready`.
- [x] every status is valid (`init.sh`)
- [ ] every `done` feature has passing tests: not applicable, 15 is not closed
- [x] `progress/current.md` is the leader's; not touched by this review
- [x] no `blocked` feature introduced

**C3 — architecture**
- [x] no framework import in any `domain` or `shared_kernel`, checked by `lint-imports` (11 kept), not by eye
- [x] no cross-service DB access and no service imports another (`service-independence` kept). The reference catalogue reads Orders' own reference tables.
- [x] no shared runtime code beyond the three packages. This feature touches nothing in `packages/`.
- [x] no `domain` imports `otc_cqrs` (`domain-purity` kept)
- [x] `shared_kernel` / `cqrs` `dependencies = []` (untouched)
- [x] no float, `Decimal` or `/` in domain money. The feature adds no domain code. The only `/` in new code is `self._timeout_ms / 1000` (`nats_stock_availability.py:61`, milliseconds to seconds, infrastructure). `grep -n ' / '` over the new modules found that line and one docstring line, nothing else.
- [x] Kafka-fact vs NATS-RPC: `orders.create` and `fulfillment.stock.check` are RPC rows. The placed fact goes through the outbox relay to Kafka.
- [x] no stray debug output or TODO. `grep -n 'print(\|TODO\|FIXME\|breakpoint'` over the 18 new or edited source modules gave no hits (exit 1).

**C4 — verification**
- [ ] `./quality.sh` passes. Not re-run by me (see §0). This box is left to the round-2 run.
- [x] domain tests pure (no domain tests added)
- [x] integration tests use testcontainers (Postgres, Kafka, NATS `nats:2.14.5-alpine`), not mocks, and passed with the developer stack down
- [ ] coverage thresholds: not re-measured (the implementer reports the gate green)
- [x] no Jest, Karma or Jasmine (no web change)

**C5 — clean close:** not applicable, rejected. No commit was made by me.

**C6 — SDD:** not applicable (`sdd: false`). No `R<n>` is claimed. The working-tree diff of `test-matrix.md` predates this feature, as the implementer states.

**C7 — reuse fidelity**
- [x] `specs/shared/` untouched by this feature
- [x] inherited #8 findings accounted for in the implementer's report (§5). My reading of each is in §4 below. **One recurs in part (id 56, D-2).**
- [ ] history entry: not written (rejected)

## 2. Acceptance items → tests (verified)

| Item | Named tests | Reviewer evidence |
|---|---|---|
| 1 stock check via NATS, `success \| RpcError` (id 46) | `test_acceptance_1_and_2_stock_is_checked_synchronously_and_the_order_id_is_returned`, `test_nats_stock_check.py` (12) | R22 (request quantity corrupted) and R23 (company replaced by retailer) both killed by the acceptance test. R24 (discriminator off) killed by 3 tests. |
| 2 order id synchronously; rejection | the same test, `test_acceptance_2_the_placed_fact_reaches_kafka_through_the_started_relay`, `test_acceptance_2_a_short_line_is_refused_with_the_shortage_and_persists_nothing` | R32 (shortage ignored) killed by 2. R21 (shortage `available` corrupted) killed by 2. R14 and R15 (money swaps) killed by 3 and 4. **R16 (currency) survived: D-3.** |
| 3 `ORD-######` under `FOR UPDATE`, cheap pre-check (id 47) | `test_order_number_allocator.py` (6) | R01 (`FOR UPDATE` removed) killed by 2, verbatim `AssertionError: duplicate references: ['ORD-000001', 'ORD-000002', 'ORD-000002', ...` and `assert 'ORD-000002' == 'ORD-000003'`. Id 47's scan-only-when-seeding was not re-probed (feature 11's `EXPLAIN` test pins it). |
| 4 responder shutdown isolated (id 50); env reads guarded (id 56) | `test_orders_create_responder.py` (6), `test_shutdown_waits_for_the_request_in_flight_before_closing_what_it_uses`, `test_orders_host_sigterm.py`, `test_orders_settings_env.py`, `test_composition_env_reads.py`, `test_every_setting_the_composition_root_reads_reaches_its_adapter` | R25 (drain without `return_exceptions`) killed. R02 (tasks not awaited on stop) killed by 2: `shutdown must wait for the request that is mid-flight`, `the server must wait for the request in flight`. R19 and R20 killed. **R18 (stock-check timeout literal) survived: D-2. The boot-failure path leaks the responder task: D-1.** |
| 5 F7, no `Order(` outside `order.py` | `tests/architecture/test_order_construction_sites.py` (11) | Not re-armed. Included in the 216 green. |
| 6 explicit registration, validated in the lifespan; behavioural guard | `test_a_command_with_no_registered_handler_fails_the_boot`, `..._two_registered_handlers_...`, `..._new_command_nobody_registered_...`, `tests/architecture/test_registration_behaviour.py` (7) | R05 (registration deleted): 15 failed + 52 errors, verbatim `DispatcherValidationError: No command handler is registered for PlaceOrderCommand. Exactly one is required.` R28 (boot probe deleted) killed: `Failed: the host must not come up with the stock port unbound`. **The probe has a hole: D-6.** |
| 7 relay task started, owned, awaited; a dying task takes readiness down | `test_the_lifespan_starts_the_responder_and_the_relay_and_awaits_both_on_shutdown`, `test_a_transport_task_that_dies_takes_readiness_down_and_names_it[...]`, `test_a_closed_nats_connection_...` | R06 (relay never started) killed by 5. R08 (readiness ignores the runtime) killed by 3. R31 (closed NATS ignored) killed by 1. R07 (responder never subscribed) killed by 59. |
| 8 one relay per process, no multi-worker while enabled | `test_single_outbox_relay.py` (10), `test_more_than_one_worker_...`, `test_a_second_relay_owning_runtime_...`, `test_a_real_uvicorn_with_two_workers_...` | R35 (the `assert_single_outbox_relay` call deleted) killed by 2. R26 (worker probe forced false) killed by the real-uvicorn test. R30 (slot never released) killed by 8 + 51 errors. Ruling on the residual in Q4. |

## 3. Rulings on the leader's questions

**Q1: lifespan in `otc_orders/main.py`. Sound, #8's shape, and one CLAUDE.md line now lies.**
- I proved it with a command. I added `import otc_orders.composition` to `presentation/app.py` (backup, restore, `cmp` identical, pyc cleared) and ran `lint-imports`: `fact-producer-confinement ... BROKEN`, `Contracts: 10 kept, 1 broken`, `otc_orders.presentation.app -> otc_orders.composition (l.15)`. A presentation-resident lifespan cannot run the composition root without breaking R14's contract.
- #8 did the same: `../order-to-cash-dotnet/src/Orders/` holds `OrdersHost.cs` and `Program.cs` at the project root beside `Presentation/` (`ls`).
- Nothing in the contracts lies. `composition.py` and `main.py` sit outside every `layers` contract. An infrastructure → composition → presentation chain is still an indirect upward import that `layers-orders` reports, and application or presentation → composition is caught by `fact-producer-confinement`. The cqrs guard's composition-root rule (`is_composition_root`, exactly `composition.py`) is unaffected: `main.py` has no `register_*`, and `asynccontextmanager` is on that guard's decorator allow-list for lifespans.
- **What lies is `CLAUDE.md` line 75**: *"`presentation` (FastAPI routers, NATS responder tasks, Kafka consumer tasks, the lifespan)"*. **This is the leader's to amend.** Suggested wording: *"the lifespan lives in the service's host module `otc_<name>/main.py`, beside `composition.py` and outside the four layers, because it runs the composition root, which `fact-producer-confinement` keeps out of `presentation`; `presentation/app.py` takes it as `create_app(lifespan=...)`"*. Lines 79–81 stay true.

**Q2: `RpcSubjectsTests` not ported. This is a finding: D-5.** #8 has it (`../order-to-cash-dotnet/tests/Orders.UnitTests/RpcSubjectsTests.cs:17-28`, `ordersCreate` and `stockCheck`). The implementer's own report calls it *"cheap and not written"*. The tests do not cover the property it guards: every test addresses NATS by a hand-typed literal (`grep` lists `"orders.create"` and `"fulfillment.stock.check"` in 9 test files). So a drift between `asyncapi.yaml` and both the code and the tests stays green. The sibling-subject arm (R29: 25 failed) proves only that code and test literals agree with each other, not that they agree with the spec. Findings are fixed in the phase that detects them, so it is ported now.

**Q3: the hand-built boot probe. Yes, a guard with a hole. Finding D-6.** The binding property #8's D3 was about is carried by `scope_factory()` → `OrdersScope.__post_init__` (`application/scope.py:31-34`). That covers every port of every handler, present and future, because a handler reaches ports only through the scope. What the probe adds is that each registered handler can be constructed at boot. Only `PlaceOrderCommandHandler` is constructed (`composition.py:247`), and no test fails when features 16 or 41 register a handler that the probe does not build (the implementer says so in §11.7). The test that closes it does not depend on unbuilt code, so it is owed now, not carried.

**Q4: one relay per process. Item 8 is met. The residual is ACCEPTED, NOT FIXED, with a trigger.**
- The supported server is uvicorn (`uv.lock`: `uvicorn 0.54.0`). `grep '^name = "gunicorn"' uv.lock` finds nothing, and no deployment manifest for the Orders service exists yet.
- The enforcement runs in the composition root before anything is connected. It is proven against the real lifespan and a real `uvicorn --workers 2`, and it is armed (R35, R26, R30, R19 all killed).
- `WEB_CONCURRENCY`, which is checked, is also gunicorn's default worker count, so only an explicit `gunicorn -w N` would escape.
- Two replicas are outside the item's wording ("per process"). `outbox_and_idempotency/design.md` 5.2 already records the single-relay rule as operational.
- **Re-open trigger:** gunicorn or any non-`multiprocessing` pre-fork server enters `uv.lock`, or an Orders deployment manifest runs more than one replica with `OUTBOX_RELAY_ENABLED` true or unset.
- **Routing:** the leader should attach an acceptance item to feature 36 `full_docker_compose`, which will build the Orders container: *"the orders service runs one replica and one uvicorn worker while `OUTBOX_RELAY_ENABLED=true`, or disables the relay on all but one"*.

**Q5: mutations.** The full table is in §5. Three survivors (D-2, D-3, D-4) plus the probe finding D-1.

**Q6: counts and arms.** The counts reconcile (§0).
- **Arms re-run by me:**
  - A11a, the identical mutation, gave the identical verbatim failure.
  - `7c`, the same mutation (`[None for _ in self.tasks]`), now fails 2 tests.
  - D5 call site, in a different form (an unvalidated `model_construct`): 34 of the 35 validation cases fail with `INTERNAL_ERROR`, plus 23 other tests. The one survivor is `body is empty`, as the implementer reports.
  - Also 46, 50a, 6d, 8d, D1's timeout direction, the money swaps, a sibling subject, `closed_nats` and 7b/7d. Every one fired.
- **One recorded arm is weaker than its row claims.** The implementer's `56d_stock_timeout_not_used` (`scratchpad/arms.json`) substituted `timeout_ms=5000`, the default, which the end-to-end timeout test notices. Substituting the fixture's own `1500` survives: D-2.
- The implementer's harness output (`scratchpad/arms_out.jsonl`, 53 results, plus `arms2–5.json`) exists, and `7c`'s first run is recorded there as `exit 0, 1 passed`, matching the reported survivor.

## 4. Inherited findings: my reading

| Id | Reading |
|---|---|
| #8 D1 (no-responders vs timeout) | **Avoided at the code level.** R10 (timeout clause deleted) is killed: `assert 'UNAVAILABLE' == 'TIMEOUT'`. **The no-responders clause itself is not pinned: D-4.** |
| D2 (stand-in leak) | avoided (every stand-in client goes on an `AsyncExitStack` when created, `conftest.py` `stand_in_stock_check`) |
| D3 (unbound port boots clean) | avoided (R28 killed) |
| D4 (mapper arm unguarded) | avoided (R04 mapper call site: 49 failed; R33, R34 killed) |
| D5 (required fields unchecked) | avoided (R11, R12, R13, R03 killed) |
| D6 (test supplies the options) | avoided (real `create_app()` and lifespan, environment only; R05, R35 killed) |
| A3, A5, A10 | avoided, avoided (`place_order.py:10-13`), not applicable |
| A11 (allocator unprobed) | avoided (R01 killed; 24-way race) |
| id 46 / 47 / 50 | avoided (R24) / avoided (static, not re-probed) / avoided (R25, R02) |
| **id 56** | **recurred in part: D-2** (one variable's reach to its adapter is unguarded) |
| #7 N2 (host bootstrap unguarded) | avoided (two real-uvicorn tests; R26 and R02 killed through them) |
| **#7 N3 (a guard covering half its claim)** | **recurred in class: D-2** (the reach test asserts the settings half, not the adapter half) **and D-3** |

## 5. Mutation table (verbatim summary line of each run; all restored identical)

| # | Mutation | Result |
|---|---|---|
| R01 | `FOR UPDATE` removed (`sequences.py`) | 2 failed: `duplicate references: ['ORD-000001', 'ORD-000002', 'ORD-000002', ...` |
| R02 | `OrdersRuntime.stop` does not await the tasks (`7c`) | 2 failed: `shutdown must wait for the request that is mid-flight` |
| R03 | validator call site bypassed (`model_construct`) | 57 failed (34 of 35 validation cases: `'code': 'INTERNAL_ERROR'`) |
| R04 | mapper call site: every failure mapped as `RuntimeError()` | 49 failed |
| R05 | `register_command` statement deleted | 15 failed, 52 errors: `No command handler is registered for PlaceOrderCommand` |
| R06 | relay branch `if False:` | 5 failed |
| R07 | `await responder.start()` deleted | 59 failed |
| R08 | `/health/ready` ignores `unready_reasons()` | 3 failed |
| **R09** | **`except nats.errors.NoRespondersError` clause deleted** | **216 passed: SURVIVED (D-4)** |
| R10 | `except nats.errors.TimeoutError` clause deleted | 2 failed: `assert 'UNAVAILABLE' == 'TIMEOUT'` |
| R11 | blank `companyCode` check deleted | 2 failed |
| R12 | blank `productCode` check neutralised | 2 failed |
| R13 | `retailerCode` made optional (default `"RET-01"`, generated model) | 1 failed: `('retailerCode missing', {'code': 'UNAVAILABLE', ...` |
| R14 | reply `initialAmount` from `total_amount` | 3 failed |
| R15 | reply `initialDiscount` from `total_amount` | 4 failed |
| **R16** | **reply `currency="EUR"` literal** | **216 passed: SURVIVED (D-3)** |
| R17 | reply `orderDate` = now | 1 failed |
| **R18** | **`NatsStockAvailability(..., timeout_ms=1500)` literal** | **216 passed: SURVIVED (D-2)** |
| R19 | `web_concurrency=1` literal | 1 failed |
| R20 | `poll_interval=0.05` literal | 1 failed |
| R21 | shortage `available=s.requested` | 2 failed |
| R22 | stock request `quantity=1` | 2 failed |
| R23 | stock request company = retailer code | 2 failed |
| R24 | `success \| RpcError` discriminator `if False:` | 3 failed |
| R25 | drain without `return_exceptions` | 1 failed |
| R26 | `in_worker_process=False` | 1 failed (real uvicorn) |
| R27 | queue group dropped | 5 failed |
| R28 | boot probe `PlaceOrderCommandHandler(scope_factory())` deleted | 1 failed |
| R29 | `STOCK_CHECK_SUBJECT = "fulfillment.stock.reserve"` | 25 failed |
| R30 | relay slot never released | 8 failed, 51 errors |
| R31 | readiness ignores a closed NATS connection | 1 failed |
| R32 | `if not stock.available:` → `if False:` | 2 failed |
| R33 | NOT_FOUND `value` = field name | 5 failed |
| R34 | responder message replaced by `str(error)` | 14 failed |
| R35 | `assert_single_outbox_relay(...)` call neutralised | 2 failed |
| R36 | reply `orderReference` literal `"ORD-000001"` | 1 failed (unit wire test) |
| R37 | command `unit_price=None` | 3 failed |
| R38 | command `line_discount=None` | 4 failed |
| R39 | buyer GLN from the company | 1 failed |
| R40 | line description dropped | 2 failed |

## 6. Defects

**D-1: a boot failure after the responder task exists leaves that task pending and never awaited.** `services/orders/src/otc_orders/composition.py:252-261`. Its docstring (lines 8-10) claims *"a failure at any step closes what was already opened"*.
- `asyncio.create_task(responder.run(stop_event))` (line 256) runs before `await publisher.start()` (line 260). Neither task is on the `AsyncExitStack`.
- When the Kafka producer cannot start, the stack drains NATS and the exception leaves `start_runtime`, but `nats-responder` and its `orders.create stop waiter` stay pending. Nobody sets `stop_event` or awaits them.
- Probe (`scratchpad/rv/probe_orphan.py`: a real NATS container, `KAFKA_BROKERS=127.0.0.1:1`, relay enabled, the real `create_app()` lifespan), verbatim:
  `boot failed: KafkaConnectionError KafkaConnectionError: Unable to bootstrap from [('127.0.0.1', 1, ...)]`
  `tasks left after failed boot: [('nats-responder', False), ('orders.create stop waiter', False)]`
- The same run printed `Unclosed AIOKafkaProducer`. `KafkaFactPublisher.start` (`infrastructure/outbox/kafka_publisher.py:52-55`) does not stop a producer whose `start()` raised, and the composition registers `publisher.stop` only after a successful start.
- Why it matters: CLAUDE.md, Async: *"every task created is awaited or owned by a `TaskGroup`; no fire-and-forget"*. Kafka coming up after the service is the ordinary compose start-up race.
- No test drives this path. `grep -rn 'KAFKA_BROKERS=\|all_tasks' services/orders/tests/` returns two hits and nothing else:
  - `test_orders_host_lifespan.py:116`: relay disabled, so Kafka is never contacted.
  - `:300`: refused by `WEB_CONCURRENCY` before connecting.

**D-2: the reach of `STOCK_CHECK_TIMEOUT_MS` to its adapter is unguarded (#8 id 56, acceptance item 4).**
- R18 (`timeout_ms=1500` at `composition.py:240`) passes 216 of 216.
- The host fixture sets `STOCK_CHECK_TIMEOUT_MS=1500` (`services/orders/tests/integration/conftest.py`, `host_environment`), and the timeout test asserts `timeoutMs: 1500`. The literal equals the fixture: defeat row 8.
- `test_every_setting_the_composition_root_reads_reaches_its_adapter` (`test_orders_host_lifespan.py:277`) asserts `host.runtime.settings.nats.stock_check_timeout_ms == 1777`, which is the settings object, not the adapter. That is half the claim the ledger row and impl §3 Q4(c) make.
- The implementer's `56d` used the default `5000`, which is why it fired.
- Related: `NatsSettings.stock_check_timeout_seconds` (`settings.py:104`) is used by no production code (`grep` finds it only in `test_orders_settings_env.py:167`). The adapter divides by 1000 itself.

**D-3: the reply's `currency` field can be replaced by a literal unnoticed.**
- R16 (`currency="EUR"` in `to_reply`, `presentation/orders_create.py:110`) passes 216 of 216.
- Every fixture of the feature is EUR: `result()` in `test_orders_create_wire.py:128`, and `REQUEST` in the acceptance, validation and SIGTERM tests.
- CLAUDE.md: *"Fixtures must not satisfy the assertion's relation by accident."*

**D-4: the no-responders branch is unobservable.**
- R09, deleting `except nats.errors.NoRespondersError` (`nats_stock_availability.py:63-66`), passes 216 of 216.
- `NoRespondersError` is a `nats.errors.Error`, so it falls into the generic branch with the same code (`UNAVAILABLE`) and the same `details`. Only the message changes, from `no responder is subscribed to fulfillment.stock.check.` to `the NATS request failed: NoRespondersError.`, and no test reads it (`test_nats_stock_check.py:51-58` and `test_orders_create_acceptance.py:297-298` assert type, subject, code and details only).
- This is #8's "the code you fixed last" note, on D1's own branch.

**D-5: #8's `RpcSubjectsTests` not ported (Q2).** `services/orders/src/otc_orders/infrastructure/messaging/subjects.py` has no guard against `specs/shared/asyncapi.yaml` (`ordersCreate` address `orders.create` at :244, `stockCheck` address `fulfillment.stock.check` at :293).

**D-6: the boot probe covers only today's handler (Q3).** `composition.py:247`. A handler registered later and not added to the probe boots green.

Nothing here is rooted in `specs/shared/`. There is no SA-n proposal and no backlog entry. The two routed items (CLAUDE.md line 75; the feature-36 acceptance item) are the leader's.

## What must change

1. **D-1.** Make every task `start_runtime` creates owned by the boot path's cleanup: on any failure after a task exists, stop it and await it. Either register a stop-and-gather callback on the stack when the task is created, or create the tasks only after every fallible step. Make `KafkaFactPublisher.start` stop the producer when its `start()` raises. **Proof:** a new test in `test_orders_host_lifespan.py` boots the real lifespan with the relay enabled and `KAFKA_BROKERS` pointing at a dead port, expects the boot to raise, and asserts that no task named `nats-responder` or `orders.create stop waiter` remains in `asyncio.all_tasks()`. **Arm:** revert the ownership; the test must fail naming the leaked task. A second test, or an assertion in the same one, covers the stopped producer (for example a recording publisher subclass). Arm it by deleting the stop.
2. **D-2.** Prove that `STOCK_CHECK_TIMEOUT_MS` reaches `NatsStockAvailability`. For example, record the adapter's `timeout_ms` in `test_every_setting_the_composition_root_reads_reaches_its_adapter` with the 1777 sentinel, as that test already does for the relay. **Arm:** R18 (`timeout_ms=1500`) and the default `timeout_ms=5000`; both must fail it. Remove the unused `stock_check_timeout_seconds` property, or have the adapter use it, and keep its test consistent.
3. **D-3.** Add a non-EUR result to the `to_reply` unit tests, for example JPY or KWD with distinct money values, asserting `currency`. Preferably also add one non-EUR order end to end (reference data with a second currency). **Arm:** R16 (`currency="EUR"`) must fail a named test.
4. **D-4.** Pin the no-responders message, or another observable unique to that branch, in `test_the_two_transport_failures_are_different_errors` and/or `test_no_responder_on_the_stock_check_subject_is_unavailable_at_once_and_persists_nothing`. **Arm:** R09 (the clause deleted) must fail.
5. **D-5.** Port `RpcSubjectsTests`: two tests asserting `ORDERS_CREATE_SUBJECT` and `STOCK_CHECK_SUBJECT` equal the `address:` of channels `ordersCreate` and `stockCheck`, parsed from `specs/shared/asyncapi.yaml` by channel id, not by grepping the literal. **Arm:** substitute a sibling (`fulfillment.stock.reserve`, `orders.cancel`) in `subjects.py`; each test must fail naming its channel.
6. **D-6.** Make a handler that is registered but not constructed at boot fail a test, or derive the probe from the registrations. **Arm:** through the real lifespan, register a second command and a handler whose factory raises, and leave the probe as it is. The boot must fail. A version in which the new handler's factory never runs at boot must be seen to fail the new test.
7. Re-run `./quality.sh` once with the developer stack down, and report the exit code, the duration and the new count, with per-file counts summing to the delta.

---

# Round 2

**Verdict: REJECTED.** Feature 15 goes back to `in_progress` (that line only). This was the last round without asking the maintainer, so the leader now asks.

All six round-1 defects are fixed, and every arm the implementer recorded fires again when I re-run it. The 11 round-1 mutations on the changed files are all killed again. `settings.py` lost nothing except docstring text. The rejection is about the round-2 fixes themselves: **four properties of the D-1 and D-6 fixes survive their own reversion.** One of them puts D-1's exact leak back on the cancellation path, and the full feature suite stays green. There is also one survivor in the adapter that I missed in round 1, and one latent leak in the boot path. This is #8's round-2 shape for this feature (`../order-to-cash-dotnet/progress/history.md` line 786): *"three of the four repairs were themselves unguarded"*. Everything owed is test-only except one line of production ordering (R2-D4) and a read accessor in `otc_cqrs` that the leader can route as a light change (§R2.3, check 2).

## R2.0 What I ran, what I did not, and an incident

- **Baseline, unmutated:** the 16 feature files, plus `test_outbox_settings.py` and `test_kafka_fact_publisher.py` (because the settings and the publisher changed): `238 passed in 42.61s`. The developer stack was down: `docker ps` showed only `otcpy-n8n`, then and now.
- **Counts:** `pytest --collect-only -q <file> | grep -c ::` over the 16 feature files gives 21+48+6+21+10+2+18+35+6+12+20+1+11+6+7+2 = **226** (= 216 + 10). A whole-workspace collection gives **`1877 tests collected`**. The implementer's +10 table reconciles file by file: lifespan 16→20, wire 45→48, acceptance 17→18, rpc_subjects 0→2.
- **Mutation harness:** `scratchpad/rv2/arm.py`. For each mutation it took a `cp` backup, made exactly one replacement (the occurrence count was asserted to be 1), ran all 18 files without `-x`, restored by copy, checked `filecmp` (every completed row printed `restored_identical: true`), and deleted the module's `.pyc`. 41 mutations were queued and **39 completed**. S10 was running when the session ended, and S11 never ran.
- **Incident (mine), with the restore evidence.** The session ended during S10 (`NatsSettings.url` alias → `"NATS_URI"`), and that mutation was left in `settings.py`. My scratchpad backups under `/tmp` did not survive the restart. I restored the file by reversing that single replacement (exactly one occurrence asserted), then checked it against the SHA-256 values I recorded for all seven mutable files **before** the run. `sha256sum -c` gave **7 of 7 `OK`**, including `settings.py` (`bcdaabb4…298b`), so the file is byte-identical to its pre-run state. I then cleared every `__pycache__` under `services/orders` and `.mypy_cache`. `find services packages tests conftest.py pyproject.toml -newer progress/brief_review_orders_acceptance_round2.md` lists only `settings.py`, which is the restore write itself. No temporary probe file remains: `find . -name '*zz_rv2*'` returns nothing. After the restore: the four settings and host files gave `47 passed`, `lint-imports` gave `11 kept, 0 broken`, `ruff check` and `ruff format --check` were clean (127 files), and `./init.sh` exited 0. **Any test run made between the interruption and this restore ran with a broken `NATS_URL` alias, so its result is void.**
- **Not re-run: `./quality.sh`.** The claim at stake is about the full suite (exit 0, 198 s, 1877 passed). The verdict does not depend on it, and a rejection makes it stale anyway. Instead I ran the 238-test feature set 40 times (the baseline plus 39 mutations), two boot-path probes, `lint-imports`, ruff and `init.sh`. The 1877 collection figure reconciles.

## R2.1 Round-1 items 1–7: re-armed, not re-read

| Item | Re-run arm (my harness, 238 tests) | Result |
|---|---|---|
| 1 D-1 | D1a (the `except` body reduced to `raise`) | 2 failed: `AssertionError: a failed boot leaked tasks: ['nats-responder', 'orders.create stop waiter']` |
| 1 D-1 | D1b (the producer stop removed) | 1 failed: `assert ['constructed', 'start'] == ['constructed...tart', 'stop']` |
| 2 D-2 | D2a = R18 (`timeout_ms=1500`) | 1 failed: `STOCK_CHECK_TIMEOUT_MS must reach the stock adapter … assert {'timeout_ms': 1500} == {'timeout_ms': 1777}` |
| 2 D-2 | D2b (`timeout_ms=5000`) | 2 failed: the above, plus `{'subject': '...eoutMs': 5000} == {...1500}` |
| 3 D-3 | D3 (`currency="EUR"`) | 3 failed: `assert 'EUR' == 'JPY'` (the JPY and KWD unit cases, and the end-to-end JPY test) |
| 4 D-4 | D4 (the no-responders clause deleted) | 2 failed: `'the NATS req...pondersError.' == 'no responder....stock.check.'` |
| 5 D-5 | D5a (`orders.cancel`), D5b (`fulfillment.stock.reserve`) | 61 failed, and 27 failed (`test_rpc_subjects.py` among them) |
| 6 D-6 | D6a (the probe back to hand-built), D6b (the factories never called) | 1 failed, and 2 failed, `test_a_registered_handler_that_cannot_be_built_fails_the_boot_whoever_registered_it` each time |
| 7 | the counts reconcile (§R2.0); `quality.sh` not re-run | — |

**The 11 round-1 mutations on the changed files, re-run:** R02 2 failed (`shutdown must wait for the request that is mid-flight`). R05 19 failed and 53 errors. R06 8 failed (`assert [] == ['order.placed.v1']`). R07 60 failed. R19 1 failed. R20 1 failed (`(0.05, True) == (0.073, True)`). R26 1 failed (real uvicorn). R28 (the probe loop deleted) 2 failed. R30 12 failed and 52 errors. R31 1 failed (`assert 200 == 503`). R35 2 failed. **11 of 11 killed.**

## R2.2 Mutations on the fixes and on the rebuilt settings (mine)

| # | Mutation | Result |
|---|---|---|
| **P1** | `_stop_tasks` without the `gather`: the event is set, the tasks are not awaited (`composition.py:239`) | **238 passed: SURVIVED (R2-D2)** |
| P2 | `_stop_tasks` cancels instead of setting the event | 1 failed: `the responder task must end on its stop event, not by cancel` |
| **P3** | boot net `except BaseException` → `except Exception` (`composition.py:317`) | **238 passed: SURVIVED (R2-D1)** |
| **P4** | producer net `except BaseException` → `except Exception` (`kafka_publisher.py:57`) | **238 passed: SURVIVED (R2-D1)** |
| **P5** | `registered_factories` reads `(self._commands,)` only (`composition.py:94`) | **238 passed: SURVIVED (R2-D3)** |
| P6 | `registered_factories` skips `_commands` | 2 failed |
| P7 | the registry's table written directly in `_wire` instead of `register_command` | 4 failed (the boot validation, and the registration guard) |
| **P8** | adapter `timeout=self._timeout_ms / 1000` → `timeout=5` (`nats_stock_availability.py:61`) | **238 passed: SURVIVED (R2-D5)**, 57 s instead of 45 s |
| P9 | the no-responders message corrupted (trailing period dropped) | 2 failed |
| S1 / S3 / S5 / S8 | defaults changed: `KAFKA_BROKERS`, `NATS_URL`, `STOCK_CHECK_TIMEOUT_MS`, `KAFKA_CLIENT_ID` | 4, 2, 1 and 3 failed |
| S2 / S4 | aliases renamed: `KAFKA_CLIENT_ID`, `STOCK_CHECK_TIMEOUT_MS` | 5 failed and 4 failed (`declared but untested: ['KAFKA_CLIENTID']`, …) |
| S6 / S7 | `poll_interval_seconds` divisor 100; `publish_timeout_seconds` computed from the poll interval | 3 failed each |
| S9 | `populate_by_name=True` on `NatsSettings` | 2 failed: `AssertionError: NatsSettings` |
| S10 / S11 | the `NATS_URL` alias renamed; `populate_by_name` on `KafkaSettings` | interrupted / not run (S9 and S2 cover the same two guards on sibling fields) |

**Boot-step failure probe (brief check 3).** This was a temporary test file, since removed, driving the real lifespan. It injected a failure at each fallible step and checked four things: leaked transport tasks, whether the relay slot was released, whether NATS was closed, and whether the engine was disposed and the producer stopped. Verbatim:
```
[nats_connect]     leaked=[] relay_owner=None conns_closed=[]     engines_disposed=1 producers=[]
[stock_adapter]    leaked=[] relay_owner=None conns_closed=[True] engines_disposed=1 producers=[]
[handler_build]    leaked=[] relay_owner=None conns_closed=[True] engines_disposed=1 producers=[]
[responder_start]  leaked=[] relay_owner=None conns_closed=[True] engines_disposed=1 producers=[]
[publisher_start]  leaked=[] relay_owner=None conns_closed=[True] engines_disposed=1 producers=[['start', 'stop']]
[relay_ctor]       leaked=[] relay_owner=None conns_closed=[True] engines_disposed=1 producers=[['start', 'stop']]
[relay_task_ctor]  leaked=[] relay_owner=None conns_closed=[True] engines_disposed=1 producers=[['start', 'stop']]
[runtime_ctor]     leaked=[] relay_owner=<contextlib.AsyncExitStack object at 0x74e2ba912140> conns_closed=[False] engines_disposed=0 producers=[['start']]
[cancel_during_kafka_start] leaked=[] relay_owner=None conns_closed=[True] engines_disposed=1 producers=[['start', 'stop']]
```
Seven of the eight injected steps, and a cancellation during the Kafka bootstrap, close everything. The `runtime_ctor` row is R2-D4. After it, a normal boot in the same process is refused: `MultipleOutboxRelaysError: this process already runs an outbox relay`, plus `Unclosed AIOKafkaProducer`.

**P3 driven through the cancellation probe** (`cp` backup, mutation, run, restore, `cmp` gave `restored_identical`):
- unmutated: `leaked=[] relay_owner=None`, `1 passed`
- `except Exception`: `AssertionError: a cancelled boot leaked tasks: ['nats-responder', 'orders.create stop waiter']`

## R2.3 The brief's specific checks

**Check 1: `settings.py` after the accidental partial deletion. Nothing behavioural was lost.** Better evidence than the tests exists. The implementer's own round-1 arm backups (`…/scratchpad/arms/56h_stock_timeout_alias_deleted.bak`, 16:03:33, md5 `8b23e44f…`, written before the incident) hold the complete pre-incident file. A `diff` of it against the current file shows only these changes:
- the comment above the properties: `` `asyncio` `` became `asyncio` (backticks lost);
- the `KafkaSettings` docstring: ``"""Where the producer connects (`KAFKA_BROKERS` and `KAFKA_CLIENT_ID` are #7's names)."""`` was replaced. **The #7 provenance is lost.**
- the `NatsSettings` docstring: rewritten. It keeps "#7's names" but drops "and defaults".
- the `stock_check_timeout_seconds` property: removed. That was the deliberate D-2 removal, and `grep -rn stock_check_timeout_seconds` over `*.py` finds no remaining use.

Every field, alias, default, validator, `model_config` and the two `OutboxRelaySettings` properties are textually identical to the pre-incident copy. Feature 14's own backup (`7c242614…/scratchpad/arm/settings.bak`, 12:18) also matches it for `OutboxRelaySettings` and `KafkaSettings`, and that agrees with `outbox_and_idempotency/design.md` §10. S1–S9 show the tests pin these values. **Disposition: text item.** The leader's verbatim recollection of both original lines is correct, and restoring them is a two-line docstring edit.

**Check 2: D-6's `_ProbedRegistry` and SLF001. It is coupling, and a public accessor is owed.**
- `pyproject.toml:66-67` states the reason for SLF001: *"nothing outside a class may reach its private state, e.g. a HandlerRegistry's handler tables (feature 43 review round 2, residual F-c)"*.
- `_ProbedRegistry.registered_factories` (`composition.py:91-97`) reads exactly those tables (`self._commands`, `self._queries`, `self._events`) from production code in another distribution. SLF001 does not see it only because the access goes through `self`. That keeps the letter of the rule while defeating its stated purpose. It also ties `otc_orders` to `otc_cqrs`'s private layout.
- Writes stay guarded: P7, a direct table write, is killed by the behavioural registration guard and the boot validation. So the cost is coupling, not an open hole.
- Features 17, 19, 23, 24 and 25 each carry the same per-service registration item, and each would copy this subclass.
- **What is owed:** a public read accessor on `HandlerRegistry` in `packages/cqrs`, for example `registered_factories() -> tuple[...]` over all three kinds. It needs its own test in `packages/cqrs/tests` that registers one command, one query and one event handler and asserts all three are listed. `_ProbedRegistry` is then deleted.
- **This is a light change the leader can route**: read-only, no change to registration or dispatch, and out of the feature-15 implementer's bounds. It is part of "What must change", and the R2-D3 test then runs on top of it.

**Check 3: a failure at each fallible boot step.** Done above. Every step except the runtime constructor cleans up. The cancellation path works, but nothing guards it (R2-D1).

**Check 4: `quality.sh`.** Not re-run (§R2.0). The reported 1877 count reconciles with my collection.

## R2.4 Defects

**R2-D1: the cancellation half of the D-1 fix is unguarded.** `composition.py:317` and `kafka_publisher.py:57` catch `BaseException`, so a `CancelledError` during boot also stops and awaits the tasks and closes the producer. That is the deliberate, correct choice. But narrowing either one to `except Exception` passes all 238 tests (P3, P4). Driven through a cancelled boot, P3 brings back D-1's exact leak, verbatim: `a cancelled boot leaked tasks: ['nats-responder', 'orders.create stop waiter']`. CLAUDE.md, Async: *"cancellation propagated, never swallowed"*, plus *"every task created is awaited"*. Its port questions also name *"task cancellation and exception propagation"*.

**R2-D2: the "awaited" half of the D-1 fix is unguarded.**
- Deleting the `gather` in `_stop_tasks` (`composition.py:239`) passes all 238 (P1).
- `test_a_boot_that_fails_after_the_responder_task_exists_awaited_it_to_completion` asserts `responder.done()` only after the lifespan has exited. Under P1 the responder still finishes in time, because the stack's NATS `drain()` gives it loop turns. So the test's name claims more than it distinguishes.
- This matters because the responder subscribes at `composition.py:282`, before the Kafka bootstrap, so it can be serving a request when the boot fails. Without the await, the engine and NATS close under that request.

**R2-D3: D-6's derivation is guarded for commands only.**
- `registered_factories` iterating `(self._commands,)` alone passes all 238 (P5), because the only handler registered in any test is a command. D-6 existed to stop *"a handler registered later and not added to the probe"* from booting green.
- Query and event handlers are the next to be registered, and for them the hole is still open.

**R2-D4: a failure in `OrdersRuntime(...)` leaks everything the stack owned.**
- `stack=stack.pop_all()` is an argument (`composition.py:315`). It is evaluated before `OrdersRuntime.__init__` runs, so if the constructor raises, the stack is already empty.
- The probe shows NATS left open, the engine not disposed, the producer started and never stopped, and the relay slot held, which refuses every later boot in the process.
- **This cannot be reached today**: the constructor has no fallible statement and no `await`. But it contradicts the docstring (`composition.py:8-10`, *"a failure at any step closes what was already opened"*), and the first statement added to that constructor makes it real.
- The fix is ordering: build the runtime first, then hand it `stack.pop_all()` as the last statement. Low severity, but a one-line fix, so per the fix-in-phase ruling it is fixed now.

**R2-D5: the stock-check budget is guarded from below only (my round-1 miss).**
- `timeout=5` in place of `self._timeout_ms / 1000` (`nats_stock_availability.py:61`) passes all 238 (P8).
- `test_a_silent_stock_check_responder_is_a_timeout_after_the_budget_and_persists_nothing` asserts `elapsed >= 1.4` (`test_orders_create_acceptance.py:347`) and no upper bound. The `timeoutMs: 1500` in `details` comes from `self._timeout_ms`, not from the timeout actually applied.
- So D-2's settings → adapter reach is now proven, but the adapter's use of the value is not. That is #7's N3, *"a guard covering half its claim"*.

**Text items (no rejection on their own):**
- (a) The provenance in the `settings.py` docstrings (check 1).
- (b) Three ledger rows in `progress/impl_orders_acceptance.md` §2 are stale:
  - "composition validation at boot" still says *"one handler built at boot"*;
  - "money on the wire" says *"`/ 1000` appears only in settings seconds properties"*, which is false, because the adapter divides at `nats_stock_availability.py:61` (it already did in round 1);
  - "task cancellation / faults" says *"`CancelledError` never caught (`except Exception` only)"*. It is now caught and re-raised at `composition.py:317` and `kafka_publisher.py:57`.

Nothing here is rooted in `specs/shared/`: no SA-n proposal, no backlog entry.

## R2.5 Inherited findings, updated

- **#8 D1 (no-responders vs timeout): avoided.** Both halves are now pinned (D4 and P9 killed).
- **#8 D3 (an unbound port boots clean): avoided.** R28 and D6a/D6b are killed. **Its extension to every registered handler recurred in part: R2-D3.**
- **id 56: closed for the settings → adapter reach** (D2a/D2b, S1–S9 killed). **Its use inside the adapter recurred in class: R2-D5.**
- **#8's round-2 note, *"three of the four repairs were themselves unguarded"*: recurred**, as R2-D1, R2-D2 and R2-D3, on the D-1 and D-6 repairs.
- **#7 N3: recurred in class (R2-D5).**
- Everything else is as in round 1 §4.

## R2.6 CHECKPOINTS.md

- **C1** [x] all five harness files exist; [x] `progress/current.md` and `history.md` exist; [x] the seven agent roles; [x] models declared; [x] `./init.sh` exit 0 (after the restore).
- **C2** [x] one feature `in_progress` (15, after this verdict); [x] statuses valid; [ ] done features' tests: not applicable, 15 is not closed; [x] `current.md` not touched by me; [x] no `blocked`.
- **C3**
  - [x] `lint-imports`: 11 kept, 0 broken.
  - [x] no cross-service access or imports.
  - [x] no shared runtime code beyond the three packages. This feature adds none, and the accessor owed by check 2 goes into `packages/cqrs`, one of the three.
  - [x] no domain imports `otc_cqrs`.
  - [x] `dependencies = []` untouched.
  - [x] no domain money `/`. The `/ 1000` sites are infrastructure, milliseconds to seconds.
  - [x] Kafka-fact vs NATS-RPC as round 1.
  - [x] no debug output or TODO.
- **C4** [ ] `quality.sh`: not re-run by me (§R2.0); [x] no domain tests added; [x] testcontainers, developer stack down; [ ] coverage not re-measured; [x] no Jest, Karma or Jasmine.
- **C5** not applicable (rejected). No commit made.
- **C6** not applicable (`sdd: false`).
- **C7** [x] `specs/shared/` untouched; [x] inherited findings accounted for (§R2.5); [ ] history entry: not written (rejected).

## What must change (round 3)

Every item except 4 and 5 is test-only. The leader may judge this a light pass: one implementer, the leader reads the diff and runs one arm per fix. Item 5 is the leader's to route into `packages/cqrs`.

1. **R2-D1.** Add a test in `test_orders_host_lifespan.py` that cancels the real lifespan while the producer's `start()` hangs. A fake `AIOKafkaProducer` whose `start` awaits forever, the same shape as `test_a_kafka_producer_that_cannot_start_is_stopped_before_the_boot_fails`, will do. The test asserts that no `nats-responder` or `orders.create stop waiter` remains and that the producer was stopped. **Arms:** P3 (`except Exception` at `composition.py:317`) must fail it naming the leaked tasks. P4 (`except Exception` at `kafka_publisher.py:57`) must fail it, or a sibling test, naming the missing `stop`.
2. **R2-D2.** Make the boot-failure test distinguish *awaited* from *ended later*. One way: hold an `orders.create` request in flight (a stand-in stock responder that waits on an event) when the producer start fails, and assert that the request was answered before the engine or NATS was closed. Another: assert that the responder task is `done()` at the moment the first stack callback runs. **Arm:** P1 (the `gather` deleted at `composition.py:239`) must fail it.
3. **R2-D3.** Extend `test_a_registered_handler_that_cannot_be_built_fails_the_boot_whoever_registered_it`, or add siblings, with an unbuildable **query** handler and an unbuildable **event** handler, each registered through the patched `register_handlers`. **Arms:** P5 (`(self._commands,)` only) must fail both. A version that drops only `_events` must fail the event case.
4. **R2-D4.** Construct `OrdersRuntime` before taking `stack.pop_all()`, so a failure in the constructor still unwinds the stack. Add a test that makes the runtime constructor raise, then asserts the relay slot is released (a second boot succeeds) and NATS is closed. **Arm:** the current argument-position `pop_all()` must fail it.
5. **Check 2 (leader routes, light).** Add a public `HandlerRegistry` read accessor in `packages/cqrs` with its own three-kind test, switch `composition.py` to it, and delete `_ProbedRegistry`. Re-arm D6a/D6b and P5 after the switch.
6. **R2-D5.** Add an upper bound to the timeout test: for example `elapsed < 1.5 + margin` with the 1.5 s budget, or a direct adapter test with `timeout_ms=400` asserting the elapsed time sits in a window. **Arm:** P8 (`timeout=5` at `nats_stock_availability.py:61`) must fail it.
7. **Text:** restore the two `settings.py` docstring provenances (check 1), and correct the three stale ledger rows (R2.4 text item b).
8. Re-run the round-2 arms that touch any file changed (D1a, D1b, D2a, D2b, D6a, D6b, R02, R28, R30, R35 at least). Run `./quality.sh` once with the stack down, and report the exit code, the duration and the per-file count delta from 1877.
