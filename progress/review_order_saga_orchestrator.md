# Review: feature 16 `order_saga_orchestrator` (round 1, full group)

**Verdict: REJECTED.** Three ported guards cover only half of what they claim. Each was shown by a mutation that the whole relevant population survives:

- **D1:** the eleven `SAGA_*` settings are never proven to reach their adapters. This is #8 id 56 recurring, the class feature 15 already recurred in.
- **D2:** a parked row's back-off is not enforced on the claim.
- **D3:** a `sent` row can be claimed again.

Everything else holds:

- the SO9 offset contract fails (never hangs) under every mutation I applied;
- feature 15's five arms still fail;
- the step table and compensation branches are armed;
- `./quality.sh`'s full-suite claim reproduces (2350 passed).

Feature 16 is set back to `in_progress`. This is round 1, so one more round is allowed without asking the maintainer.

## What I ran, and what I did not

I did not re-run `./quality.sh` as a whole. I ran its parts instead:

| Gate | Result |
|---|---|
| `uv run mypy` | Success, 385 files |
| `uv run lint-imports` | 11 kept, 0 broken |
| `ruff check .` | clean |
| `ruff format --check .` | clean |
| Full `uv run pytest -q` on the real code, developer stack down (log `.arm/review/full_green.log`) | **2350 passed in 389.5 s**, exit 0. Matches the record. |
| `./init.sh` | exit 0 |
| Web gates | not re-run (the feature does not touch `apps/web`) |

Mutations:

- 17 of my own, each run through a reviewer tool that starts pytest in its own process group under an outer timeout that kills the whole group. The tool is `.arm/review/` plus a scratchpad script, with a log per arm in `.arm/review/<id>/run.log`.
- Each one was backed up with a sha256, restored by copy, checked `cmp`-identical with an equal sha256, and caches were cleared.
- After the session, every backup under `.arm/review/` and `.arm/bak/` is `cmp`-identical to the live file. No `ACTIVE` marker remains, no pytest process is left, and no container is left except `otcpy-n8n`.
- One run of mine was void: the first settings probe exited 4 because my tool passed two paths as one argument. I fixed the tool and re-ran; this is recorded in `.arm/review/log.md`.

## Rulings on the brief's questions

### Q1: SO9 offset contract (3.9 / 3.10 / 3.12)

These tests now **fail, they do not hang**. Every mutated run below ended in exit 1, and pgrep found no survivor in the process group.

| Arm | Mutation (in `kafka_fact_subscriber.py`) | Test | Result (verbatim) |
|---|---|---|---|
| R3.9a | `commit(offset+1)` before the handler `await` | SO9 #1 | 14.7 s: `AssertionError: the offset moved while the handler ran` |
| R3.9b | `enable_auto_commit=True` and the explicit commit removed | SO9 #1 | 16.7 s: `AssertionError: the offset moved while the handler ran` (the 5 s auto-commit tick) |
| R3.9c (corrupt) | the failure branch commits `offset+1` instead of seeking | SO9 #1 | 18.6 s: `AssertionError: a failed handler must not advance the offset` |
| R3.9d (#8 id 94) | no pacing, so an immediate in-process retry | SO9 #1 | 19.0 s: `AssertionError: a failed handler must not advance the offset` |
| R3.10 | the `seek` removed | SO9 #2 | 71.8 s: `AssertionError: only 1 attempts in 60 s` |
| R3.10b (corrupt) | `seek(tp, offset + 1)` | SO9 #2 | 70.8 s: `AssertionError: only 1 attempts in 60 s` |
| R3.10c | commit `offset+1` on failure while still seeking | SO9 #2 | 21.8 s: `AssertionError: the committed offset 1 passed the failed record at 0: samples=[0, …, 1, 1, …]`. Restored run green. |
| R3.12 | `auto_offset_reset="latest"` | SO1 | 30.6 s: `timed out after 20s waiting for: the credit.hold row exists: the fact published first was consumed`. Restored run green. |

R3.9d is what matters most here: the test tells an in-process retry apart from a genuine redelivery by a restarted consumer.

**Observation (not blocking):** the recorded arm for 3.10 (`seek` removed) dies at the 60-second attempt-count assertion (`test_saga_consumption.py:227`). That is earlier than the assertion task 3.10 is about, the committed offset never passing the failed record (`:231`), so by tasks.md's own rule that arm does not prove the sampling assertion. My R3.10c does: it fails at `:231` with the claim in its message.

**Timing margin (not blocking):** in SO9 #1, the in-process retry is paced at 1 s. The test leaves the first lifespan about 0.5 s plus one admin round-trip after the failure. If that window ever exceeds 1 s, the test fails safe: the committed offset check after exit goes red. It cannot pass falsely, but it is a possible flake on a loaded machine.

**Arming tool (development tooling, git-ignored):** `.arm/arm.py` calls `subprocess.run([...], timeout=420)`, which kills only the `uv` parent. That is why the leader found orphaned pytest processes. The tool still has this defect. Future arming should use `start_new_session=True` plus `os.killpg`, as `.arm/review`'s tool does.

### Q2: line order

- **What is true:** `_load` (`order_repository.py:159-165`) has no `ORDER BY`, but `Order.rehydrate` sorts the lines by line-id integer (`domain/order.py:322-336`), and `order_of` always goes through `rehydrate` (`order_mapper.py:131`).
- So request lines come out in **line-UUID order**. That is deterministic per order, unrelated to the database's order, and random against product order, because line ids are random.
- **The impl record's explanation is wrong:** `impl_order_saga_orchestrator.md:236` says lines come back "in the database's order". So is the comment at `test_saga_happy_path.py:43-44`.
- **What flaked:** the restored run of arm 7.5 in the first batch (`.arm/old/results1.md:131`, `restored green=False`). Its failure output was overwritten by the re-run (`old/logs1/7.5.log` now shows the later green run), so the exact assertion is not recoverable. The surviving mutated-run payload of the same batch shows `SKU-B` before `SKU-A`. That fits a then-order-dependent assertion meeting UUID-sorted lines, which would fail about half the time.
- **Current state:** every saga assertion on lines sorts by product code before comparing (`test_saga_happy_path.py:45, 78, 151`). Unit payload tests use fixed line UUIDs (`unit/saga/conftest.py:66-67`). Nothing remains order-dependent.
- The flake is a finding because its cause was misattributed. This is D4 below.

### Q3: forced edits to feature 15's tests

- **No feature 15 guard was weakened in effect.** The "no handler" test now asserts the `PlaceOrderCommand` message, `len == 11`, and that every problem is a "no handler" message, instead of the exact tuple. The ten fact-command names are not listed literally, but the count plus the prefix still fails on any loss.
- I re-ran P1, P3, P4, P5 and P8 against the current `composition.py`. All fail:
  - **P1** (`_stop_stages` gather replaced by `[None] * len(...)`): fails at `reply = json.loads((await asyncio.wait_for(request, ...)` with `nats.errors.ConnectionClosedError`, meaning the request was not answered.
  - **P3** (`composition.py:461` changed to `except Exception`): `a cancelled boot leaked tasks: ['nats-responder', 'orders.create stop waiter']`.
  - **P4** (`kafka_publisher.py:57` changed to `except Exception`): `the producer must be stopped`.
  - **P5** (`registered_factories` over `(self._commands,)`): `Failed: the host must not come up with an unbuildable query handler`.
  - **P5e** (`_events` dropped): `… unbuildable event handler`.
  - **P8** (`timeout=5`): `the 1.5 s budget is what was applied, not a longer one: 5.11s`.

### Q4: G1 as built

- **No head-of-line blocking:** proven at integration level by `test_so13_a_command_whose_responder_never_answers_does_not_delay_another_orders_command`. It runs through the real lifespan with the sweeper disabled, and the recorded arm is a sequential drain (13.4).
- **Overflow:** dropped at unit level (6.4a/b).
- **Boot refusal of a maximum below 1:** armed (9.2b).
- **Trace context (L7):** `TaskGroup.create_task` with `context=None` copies the caller's context, and `signal` is called inside the consumer task's fact handling. Armed at unit level by 6.5 (`context=contextvars.Context()`).
- **But the maximum itself never reaches the fast path under test.** `max_in_flight=saga.fast_path_max_in_flight` hard-coded to `256` survives the whole Orders suite (D1). So #8 id 90 is avoided for "≤ 0 dispatches nothing", while #8 id 56's half, "the configured value is the one applied", is open.

### Q5: feature 42 boundary, stated for the leader's scoping

- **Item 2 (retryable transport failures still retried): delivered.**
  - Timeout and no-responders are distinct types (`nats_saga_commands.py:128-139`). The dispatcher retries and parks every `SagaCommandError`.
  - My probe RC4, narrowing the dispatcher to retry only `SagaCommandTimeoutError`, fails `test_command_dispatcher.py` at once with `SagaCommandTransportError: s: no responder`.
  - The live walkthrough showed no-responders being parked.
- **Item 1: half delivered, as stated, with one correction.**
  - A known-code `RpcError` raises `SagaCommandRpcError(code)` (`nats_saga_commands.py:148-150`); the terminal set and the short-circuit are not built.
  - Correction: a code outside the twelve does **not** carry "the raw string" as `requirements.md:163` says. It fails validation and becomes a plain `SagaCommandTransportError("malformed reply …")` with no `code` attribute. That matches `design.md` §9.3 / L18 and task 4.4, so the sentence in `requirements.md` §5 is the inconsistent one. It is a local-spec wording fix for the leader; it is not in the implementer's file list.
- **Item 3 (a resolved end state): not delivered.** Note for 42:
  - The claims name their statuses explicitly (`command_ledger.py:99, 116-123`).
  - **`park` does not:** `WHERE status <> 'sent'` (`command_ledger.py:157`) would move a future `rejected` row to `parked`. Feature 42 must change that predicate as well as add the status.

### Q6: #8's defect class (mutating the code changed last and its call sites)

**Killed:**

| Probe | Mutation | Result |
|---|---|---|
| RC1 | consumer swallows a dispatch failure (`saga_facts_consumer.py:86`) | `timed out after 30s waiting for: two failed attempts of the poisoned record` |
| RC4 | dispatcher retries only timeouts | fails on `SagaCommandTransportError` |
| RL-a | `mark_sent` unconditional (`command_ledger.py:144`) | `assert datetime(...,12,0,10) == datetime(...,12,0,5)` in `test_marks_are_conditional_and_attempts_accumulate` |

These call sites are covered by the implementer's 123 arms, all of whose backups I verified identical to the live files:

- enqueue inside the fact transaction (7.6);
- the fast-path signal (6.8, 6.9, 7.7, 13.4);
- the sweeper claim (8.2, 8.3, 8.6d, 8.8);
- reply decode (4.4, 4.6);
- compensation branches (11.1–11.9);
- step-table rows (2.2, the full 14 × 9 matrix).

**Survived:** D1, D2 and D3 below.

## Defects

### D1: #8 id 56 recurred: no `SAGA_*` setting is proven to reach its adapter (blocking)

- **Where:**
  - `composition.py:345-358` and `:417-431` wire the eleven `SagaSettings` fields.
  - `test_orders_host_lifespan.py:575-622` (`test_every_setting_the_composition_root_reads_reaches_its_adapter`) records only the stock adapter, the publisher, the relay and the relay task.
  - `tests/architecture/test_composition_env_reads.py:13-17` declares half 3 of the mechanism: "EACH FIELD is read, and reaches the thing it configures … through the real lifespan".
  - `design.md` §12.2: "`SagaSettings` joins A4's environment-read guard population".
- **Evidence (probe RS):** `max_attempts=3`, `backoff_ms=500`, `max_in_flight=256` and `batch_limit=20` hard-coded at once in `composition.py` gave **1407 passed in 305 s** over `services/orders/tests tests/architecture`, exit 0. Survived.
- **Why it matters:** a deployment that sets `SAGA_FAST_PATH_MAX_IN_FLIGHT`, `SAGA_COMMAND_MAX_ATTEMPTS`, `SAGA_COMMAND_BACKOFF_MS` or `SAGA_SWEEPER_BATCH_LIMIT` could be silently ignored. This is exactly #8 id 56. Feature 15 recurred in it twice (D-2, R2-D5), and its history entry warned feature 16 that tasks added to `start_runtime` "must join that rule".

### D2: the park back-off is not enforced on the claim, and nothing notices (blocking)

- **Where:** `command_ledger.py:123`, the `parked` branch of `claim_due`: `and_(status == "parked", next_attempt_at <= now)`.
- **Evidence (probe RL-b):** the branch reduced to `status == "parked"` gave **438 passed** over `unit/saga` and `integration/saga` (every test that drives the ledger). Survived.
- **Why it matters:** SO5 says "re-attempt it … with capped exponential backoff". Test 8.4 proves that `next_attempt_at` is computed correctly, but no test proves the sweeper honours it. A regression would re-issue every parked command on every sweep (30 s) and nothing would fail. `try_claim`'s equivalent clause (`or_(next_attempt_at IS NULL, next_attempt_at <= now)`) for a parked row is likewise asserted only for leased rows, not for parked ones.

### D3: a `sent` row is claimable, and nothing notices (blocking)

- **Where:** `command_ledger.py:99`, `try_claim`'s `status.in_(CLAIMABLE)`.
- **Evidence (probe RL-c):** with that line deleted, **438 passed** over the same population. Survived.
- **Why it matters:** `design.md` §7.5 says "a `sent` row is a no-op claim". That is the property that makes the `ALREADY_OWED` re-signal safe. Without it, a `sent` row (with `next_attempt_at` set to NULL by `mark_sent`) is re-claimed and re-sent on every re-signal.
  - The mid-compensation case (`test_credit_rejected_redelivered_with_a_new_event_id_mid_compensation_owes_one_stock_release_and_commits_its_offset`) drives exactly this path but asserts row count only, not requests at the stand-in.
  - The absence ("no-op", "never re-dispatched") is a countable claim that was never seen to fail.

### D4: line order misattributed (minor, fix in the same round)

- `test_saga_happy_path.py:43-44` and `impl_order_saga_orchestrator.md:236` attribute the line order to the database. `Order.rehydrate` sorts lines by id (`domain/order.py:322-336`).
- The flake's cause is recorded wrongly. The next reader will "fix" an `ORDER BY` that changes nothing.

## What must change before re-review

Each item is an instruction, with the test and the arm that will prove it. Record every arm verbatim in the impl record and restore by `cp` plus `cmp`.

1. **D1.** Extend `test_every_setting_the_composition_root_reads_reaches_its_adapter`, or add a sibling in the same module driven by the real lifespan, so that each of the eleven `SAGA_*` variables is set to a distinct non-default sentinel and observed at the object it configures:
   - `SagaCommandDispatcher`: `max_attempts`, `backoff_ms`, `park_cap_ms`;
   - `NatsSagaCommandsAdapter`: `timeout_ms`;
   - `SqlAlchemySagaCommandLedger`: `lease_ms`, `pending_grace_ms`;
   - `SagaFastPath`: `max_in_flight`;
   - `SagaCommandSweeper`: `batch_limit`;
   - `SagaCommandSweeperTask`: interval and enabled;
   - `SAGA_CONSUMER_ENABLED`: task presence.
   
   Sentinels must keep the lease rule valid and be pairwise distinct. **Arms:** each of the four hard-codings of probe RS, applied **one at a time** (`max_attempts=3`, `backoff_ms=500`, `max_in_flight=256`, `batch_limit=20`), must fail it naming the setting. So must `timeout_ms=5000`, `lease_ms=60_000` and `pending_grace_ms=10_000`.
2. **D2.** Add to `integration/saga/test_saga_command_ledger.py` a case where a row parked with `retry_after_ms = N` (fake clock) is returned by neither `claim_due` nor `try_claim` at `parked_at + N - 1 ms`, and is returned by `claim_due` at `parked_at + N`. **Arms:** RL-b (`claim_due`'s parked branch without `next_attempt_at <= now`) must fail it naming the back-off; dropping the `next_attempt_at` clause from `try_claim` must fail the `try_claim` half.
3. **D3.** Add to the same module a case where a row after `mark_sent` is returned by neither `try_claim` nor `claim_due`, even with the clock advanced past any lease. Also make the mid-compensation integration case assert that the `fulfillment.stock.release` stand-in recorded **exactly one** request after the second `credit.rejected.v1` was processed. **Arms:** RL-c (delete `SagaCommand.status.in_(CLAIMABLE)` from `try_claim`) must fail both the ledger case and the integration case, the latter naming the request count. Removing `status` from `claim_due`'s branches must fail the `claim_due` half.
4. **D4.** Correct the comment at `test_saga_happy_path.py:43-44` and the impl-record bullet at line 236: lines are re-sorted by line id in `Order.rehydrate`. Record the 7.5 flake as an order-dependent assertion against UUID-sorted lines, with the output lost.
5. **Record (no code):** add R3.10c (commit on failure while seeking) to the impl record as the arm of the committed-offset sampling assertion (`test_saga_consumption.py:231`). The existing 3.10 arm dies at `:227`.
6. **Re-run, do not re-read:** after the changes, re-run 9.2b, 6.4a, 6.4b, 8.2, 8.4, 8.5a-c and 10.3c, which touch the code or tests you change, plus `./quality.sh` once with the stack down. Report the pass count and its delta from 2350.

## For the leader (routing, not narration)

- **No `specs/shared/` root cause was found**, so no `SA-n` is proposed. The `traceparent` gap (`RpcHeaders` marks it required) is feature 27's by the decided outbox design §12.2. #8 id 94's SO9 re-run is already attached to feature 27's acceptance, and #8 id 91 / id 62 to feature 41's.
- **Local spec fix, owner the leader / spec author:** `specs/order_saga_orchestrator/requirements.md:163` says an out-of-set `RpcError` code is carried as "the raw string". The design and code make it a plain transport error with no code (Q5). Feature 42's scope should read the design's version.
- **Feature 42 scoping:** item 2 delivered; item 1 half delivered (known codes only carry `code`); item 3 not delivered. 42 must change `park`'s `status <> 'sent'` (`command_ledger.py:157`) as well as the claims.
- **Matrix rule 3 tension (precedent, not a defect of this feature):** R24, R28 and R29 are partly `TODO` and correctly counted under "Not yet green" (11 / 8 / 0 / 3). The deferrals were approved at the spec gate. The cells do not name the ratification, so rule 3 (b) is not literally met. Feature 14 closed on the same footing with R16, so this is the repository's practice, but naming the gate in the three cells would make it literal.
- **Tooling:** `.arm/arm.py`'s timeout leaves pytest children alive (Q1). Brief future arming to kill the process group.

## CHECKPOINTS walked

**C1**
- [x] `AGENTS.md`, `CLAUDE.md`, `CHECKPOINTS.md`, `feature_list.json`, `init.sh` all exist.
- [x] `progress/current.md` and `history.md` exist.
- [x] The seven agent definitions exist.
- [x] Each agent declares its model or deliberately inherits it (leader, reviewer and spec_author inherit, stated in their descriptions).
- [x] `./init.sh` exits 0.

**C2**
- [x] At most one feature in progress: 0 `in_progress`, 1 `in_review` (16).
- [x] Every status is valid (29 done, 25 pending, 1 in_review).
- [x] Every `done` feature has passing tests (full suite 2350 passed).
- [ ] `current.md` describes the active session or holds only the template: not checked here (leader-owned; out of scope for this review).
- [x] No `blocked` feature exists.

**C3**
- [x] `lint-imports`: 11 kept, including the domain and `shared_kernel` purity contracts and independence.
- [x] No cross-service database access or imports: Orders only; no new database or service.
- [x] Shared runtime is still only `shared_kernel`, `contracts` and `cqrs`; this feature touched none of them.
- [x] No `domain` imports `otc_cqrs` (contract kept).
- [x] `dependencies = []` unchanged (no `packages/` edits by this feature).
- [x] No domain money arithmetic added: amounts are copied as `int` from `Money` (`command_payloads.py`); the only `/` is ms-to-seconds at the transport boundary.
- [x] Every interaction classified: facts consumed over Kafka (three topics, matching `asyncapi.yaml`, armed 2.5); six commands as NATS RPC (armed 4.2).
- [x] No stray debug logging or context-free TODOs in the new modules (grep of the feature's modules for `print(`, `TODO`: none outside tests' explicit `print` of the SO13 timing).

**C4**
- [x] `quality.sh`'s parts all pass (mypy, ruff, lint-imports; pytest 2350). The web gates and the coverage figure are not re-run: they are taken from the record, 98.70%.
- [x] Domain tests are pure: `domain/` is untouched by this feature.
- [x] Integration tests use real PostgreSQL, Kafka and NATS containers and pass with the developer stack down (verified: only `otcpy-n8n` running).
- [x] Coverage gates met (from the record; not re-measured).
- [x] No Jest, Karma or Jasmine.

**C5**
- [x] No suspicious untracked files: `.arm/` is git-ignored; the untracked list is classified in the impl record, task 14.7.
- [ ] `history.md` effort entry: not written, because the feature is rejected.
- [x] `feature_list.json` reflects the truth: 16 set to `in_progress`.
- [x] The human has been told how to test it manually: impl record §14.2 holds the live-stack walkthrough commands.
- [x] Claude did not commit.

**C6**
- [x] `specs/order_saga_orchestrator/` has all three files.
- [x] `requirements.md` uses EARS with ids (R19–R29 by pointer, SO1–SO17).
- [x] All 101 tasks are ticked, though 14.4's "every arm armed" is contradicted by D1–D3's unguarded properties (those are properties no task arm targeted, not stale ticks).
- [x] Every R19–R29 is named in the matrix: each name has exactly one `def` (one shared name also defined once in a unit module, deliberate).
- [ ] Spec commit precedes the implementation commit: nothing is committed yet (wrap-up).

**C7**
- [x] `specs/shared/` is byte-identical to #7 and #8 except `test-matrix.md`: `cmp` over 6 files, all identical.
- [x] No unrecorded deviation: no `SA-n` needed.
- [x] R ids are #7's: the step table matches `saga.md` §3.1 / §4 row for row.
- [ ] n8n: n/a this feature.
- [ ] API script: n/a until feature 31.
- [ ] Inherited findings accounted for: **#8 id 56 recurred (D1) and is not yet listed in the record's §18 tally.** Everything else is listed.
- [ ] Effort honesty: deferred to closure.
- [ ] README benchmark: n/a until wrap-up.

## R<n> → test mapping verified

Each name was checked by a `def <name>(` search: exactly one definition each.

**Shared rows:**

| Id | Test | Arm(s) |
|---|---|---|
| R19 | `test_saga_happy_path.py::test_r19_…` | 10.2c |
| R20 | `test_r20_…` | 10.2b, 5.2a |
| R21 | `test_r21_…` | 10.2a, 11.1 |
| R22 | `test_r22_…` | — |
| R23 | `test_r23_…` | 11.7 |
| R24 | `test_r24_…` (integration half) | 11.2 |
| R25 | `test_saga_preconditions.py::test_r25_…` × 10 | 10.3a/b |
| R26 | `test_saga_compensation_stock_rejected.py::test_r26_…` | 11.3, 11.6i |
| R27 | `test_saga_compensation_credit_rejected.py::test_r27_…` | 11.8b |
| R28 | `test_r28_…` (integration half) | 11.9a, 12.2a |
| R29 | `test_saga_command_retry.py::test_r29_…` (retry case) | 12.3b |

**Local rows:**

| Id | Test(s) | Arm(s) |
|---|---|---|
| SO1 | — | R3.12 (mine) |
| SO2 | the two SO2 tests | 2.3a/b, 3.5b |
| SO3 | the three SO3 tests | 7.6, 7.7, 12.3a1 |
| SO4 | — | 8.6 |
| SO5 | — | 12.3a2 (the back-off half is open: **D2**) |
| SO6 | — | 4.7, 8.6a, 12.2b |
| SO7 | — | 2.4, 11.4 |
| SO8 | — | 10.4a |
| SO9 | the two SO9 tests | mine above |
| SO10 | — | 6.2 |
| SO11 | the two SO11 tests | 8.2 |
| SO12 | — | 10.4a/b |
| SO13 | the integration case | 13.4 |
| SO13 | the unit case | 6.4 (the configured maximum's reach is open: **D1**) |
| SO14 | — | 5.4a/b, 6.5 |
| SO15 | — | 4.4, 4.6 |
| SO16 | — | 8.8, 9.2 |
| SO17 | — | 7.1, 7.2 |

## Inherited findings (for the closing history entry)

- **Avoided as claimed:**
  - #8 ids 80, 88, 89, 110, 48, 51, 94 (here);
  - #8 id 90 (≤ 0 refused);
  - #8 D1–D5;
  - #7 D1, D2, D3, D5;
  - #7 third-pass ruling;
  - `review_shared_kernel` Q2.
- **Recurred:**
  - **#8 id 56** (D1: settings reach), the class of feature 15's D-2 / R2-D5;
  - **#7 N3 / #8's "correct and nothing notices its reversion"** (D2, D3: ledger predicates with half a guard).
- **Split as designed:** #8 id 62. **Assigned:** #8 ids 71, 91.

---

# Round 2 (reviewer, 2026-10-07 13:07 → 13:35)

**Verdict: APPROVED.** Items 1–6 of round 1's "What must change" are closed, and each closure was re-armed by me, not re-read: 26 mutations (my round-1 survivors RS ×4, RL-b, RL-c, both claim halves, plus 16 new probes across all three mutation families) all fail their named test with a message naming the setting or predicate, every restore is `cmp`- and sha256-identical, every restored run is green. `src/` is byte-identical to the state round 1 reviewed. Two non-blocking findings (N1, N2) are test-only hardening with a light disposition below; neither is a wrong line of shipped behaviour, and neither reopens a round-1 defect. Feature 16 is set to `done`.

## What I ran, and what I did not

| What | Result |
|---|---|
| Full `uv run pytest -q -p no:cacheprovider --junitxml=… --durations=30`, developer stack down (only `otcpy-n8n`), log `.arm/review2/full_r2.log` | **2355 passed in 392.76 s**, exit 0 (wall 6:35, CPU 32 %). Matches the record's 2355 (+5 from 2350). Run in full because the duration question (check 3) is a claim about the full suite. |
| Per-file counts (`pytest --collect-only -q`) | `test_orders_host_lifespan.py` 29, `test_saga_command_ledger.py` 13, `test_saga_preconditions.py` 14. Reconciles with the record's 27→29, 10→13, 14→14 = +5. |
| `ruff format --check` / `ruff check` / `mypy` / `lint-imports` | 471 files formatted / all checks passed / no issues in 385 files / 11 kept, 0 broken |
| `./init.sh` | exit 0 |
| `./quality.sh` as a whole | **not re-run**: its parts are above; coverage (98.70 %) and the web gates are taken from the record (no `apps/web` or coverage-relevant change this round). |
| Implementer's item-6 re-runs (9.2b, 6.4a/b, 8.2, 8.4, 8.5a-c, 10.3c) | **not re-run**: they guard code this round did not change (`src/` identical, check 2); the record's verbatim failures are consistent with round 1. |

## Check 4: the kill path, proven before use

I used my own tool (`rarm2.py`, a copy of round 1's with backups in `.arm/review2/<id>/`), which starts pytest with `start_new_session=True`, kills the group with `os.killpg(SIGKILL)` on timeout and then lists the group with `pgrep -g`. **Proof (K0):** a unit test made to `time.sleep(3600)` under a 25 s timeout gave `mutated run: exit=124 (25.1s); group survivors=[]`, `TIMEOUT 25s (process group 789170 killed)`; afterwards `ps … | grep "[p]ytest "` printed nothing and no `time.sleep` process existed; the test file restored `cmp`-identical, sha256 equal. The implementer's `.arm/arm.py` kill path is still unexercised; I did not use that tool, and it has the right shape (`Popen(start_new_session=True)`, `os.killpg(pr.pid, SIGKILL)`, read by me at `.arm/arm.py` `run()`).

## Check 2: `src/` untouched, and the round-1 state is what is under test

- `find services/orders/src -type f -newer progress/review_order_saga_orchestrator.md` (round 1's verdict, 12:33:00): **no output**. mtime alone is weak evidence here because both arm tools restore with `shutil.copy2`, which preserves mtime, so I also checked ctime and content.
- `find services/orders/src -type f -cnewer …`: 5 hits — `composition.py` (12:41), `settings.py` (12:56), `command_queue.py` (12:57), `command_ledger.py` (12:56), `fast_path.py` (12:56). Classification: each is the target of a round-2 arm (D1 arms; 9.2b; 10.3c; RL-b/RL-c/8.2/8.4/8.5; 6.4a/b) and its ctime is the restore.
- Content: `composition.py` sha256 `b963e14e…9646` equals my round-1 `sha256 before` (`.arm/review/log.md` lines 692, 928, 1305, 1317); all 18 of my round-1 backups under `.arm/review/` are `cmp`-identical to the live files (composition ×3, command_ledger ×3, kafka_fact_subscriber ×8, saga_facts_consumer, command_dispatcher, kafka_publisher, nats_stock_availability); `settings.py`, `command_queue.py`, `fast_path.py` are `cmp`-identical to the implementer's round-1 backups taken at 11:10–11:41 (9.2a/c/d, 7.4, 7.6, 6.2–6.10, 13.4), i.e. before round 1's review. **Confirmed: the code under test is the code round 1 reviewed.**

## Re-armed: items 1–3 and my round-1 survivors (26 arms, `.arm/review2/batch1.out`, one log per arm in `.arm/review2/<id>/run.log`)

Every mutated run exited 1 with `group survivors=[]`; every restore `cmp identical; sha256 equal: True`; every restored run exit 0. No `ACTIVE` marker left; all 27 backups under `.arm/review2/` are `cmp`-identical to the live files.

**Item 1 (D1) — `composition.py`, test `test_every_saga_setting_the_composition_root_reads_reaches_the_object_it_configures` unless stated:**

| Arm | Family | Mutation | Failure (verbatim) |
|---|---|---|---|
| a1 (RS) | delete | `max_attempts=3` | `SAGA_COMMAND_MAX_ATTEMPTS must reach the dispatcher` / `assert 3 == 4` |
| a2 (RS) | delete | `backoff_ms=500` | `SAGA_COMMAND_BACKOFF_MS must reach the dispatcher` / `assert 500 == 130` |
| a3 | delete | `park_cap_ms=900_000` | `SAGA_PARK_RETRY_CAP_MS must reach the dispatcher` / `assert 900000 == 777000` |
| a4 (RS) | delete | `max_in_flight=256` | `SAGA_FAST_PATH_MAX_IN_FLIGHT must reach the fast path` / `assert 256 == 33` |
| a5 (RS) | delete | `batch_limit=20` | `SAGA_SWEEPER_BATCH_LIMIT must reach the sweeper` / `assert 20 == 7` |
| a6 | delete | `timeout_ms=5000` | `SAGA_COMMAND_TIMEOUT_MS must reach the NATS adapter` / `assert {'timeout_ms': 5000} == {'timeout_ms': 1900}` |
| a7 | delete | `lease_ms=60_000` | `SAGA_COMMAND_LEASE_MS must reach the ledger` / `assert 60000 == 91000` |
| a8 | delete | `pending_grace_ms=10_000` | `SAGA_PENDING_GRACE_MS must reach the ledger` / `assert 10000 == 13300` |
| a9 | delete | `interval=30.0` | `SAGA_SWEEPER_INTERVAL_MS and SAGA_SWEEPER_ENABLED must reach the sweeper task` / `assert (30.0, True) == (41.0, True)` |
| a10 | sibling | `lease_ms=saga.pending_grace_ms, pending_grace_ms=saga.command_lease_ms` | `SAGA_COMMAND_LEASE_MS must reach the ledger` / `assert 13300 == 91000` |
| a11 | sibling | `backoff_ms=saga.command_timeout_ms` | `SAGA_COMMAND_BACKOFF_MS must reach the dispatcher` / `assert 1900 == 130` |
| a12 | corrupt | `batch_limit=saga.sweeper_batch_limit + 1` | `SAGA_SWEEPER_BATCH_LIMIT must reach the sweeper` / `assert 8 == 7` |
| a13 | delete | `if saga.sweeper_enabled:` → `if True:` (test `test_the_saga_enable_flags_decide_which_tasks_exist`) | `SAGA_SWEEPER_ENABLED=false: no sweeper` / `assert 'saga-sweeper' not in {…}` |
| a14 | delete | `if saga.consumer_enabled:` → `if True:` (same test) | `SAGA_CONSUMER_ENABLED=false: no consumer` / `assert 'saga-consumer' not in {…}` |

a13/a14 close the record's "not armed: the enable flags' task presence". The sentinels are pairwise distinct (asserted in the test), so the two sibling substitutions could not pass by coincidence. The population is complete today: `SagaSettings` has 11 fields (`settings.py:131-143`), the sentinel dict has 11 keys, one per field. See N2 for the future.

**Item 2 (D2) — `command_ledger.py`:**

| Arm | Family | Mutation | Test | Failure (verbatim) |
|---|---|---|---|---|
| b1 (RL-b) | delete | `claim_due` parked branch without `next_attempt_at <= now` | `test_so5_a_parked_rows_backoff_is_enforced_on_both_claims_…` | `claim_due: a parked row is not due one ms before its back-off ends` / `assert [ClaimedComma…] == []` |
| b2 | delete | `try_claim` without its `or_(next_attempt_at IS NULL, <= now)` clause | same | `try_claim: a parked row is not claimable one ms before its back-off ends` |
| b2' | delete | same | `test_so5_…_for_the_fast_path_claim` | `try_claim: a parked row is not claimable one ms before its back-off ends` |
| b3 | corrupt | `claim_due` parked branch `<=` → `<` | `test_so5_a_parked_rows_backoff_is_enforced_on_both_claims_…` | `ValueError: not enough values to unpack (expected 1, got 0)` at `[due] = await ledger.claim_due(10)` — fails, but see **N1** |
| b4 | corrupt | `try_claim` `<=` → `<` | `test_so5_…_for_the_fast_path_claim` | `try_claim: claimable at next_attempt_at` / `assert None is not None` |

**Item 3 (D3):**

| Arm | Family | Mutation | Test | Failure (verbatim) |
|---|---|---|---|---|
| c1 (RL-c) | delete | `SagaCommand.status.in_(CLAIMABLE)` deleted from `try_claim` | `test_so11_a_sent_row_is_a_no_op_claim_…` | `try_claim: a sent row is never claimed again` |
| c1' (RL-c) | delete | same | mid-compensation integration case | `exactly one fulfillment.stock.release request, got 2: the sent row must not be re-dispatched by the second credit.rejected.v1` / `assert 2 == 1` |
| c2 | delete | `status == "pending"` removed from `claim_due` | `test_so11_…` | `claim_due: a sent row is never due` |
| c3 | delete | `status == "parked"` removed from `claim_due`'s parked branch | `test_so11_…` | `claim_due: status, not a NULL next_attempt_at, keeps a sent row out` (the planted block) |
| c4 | sibling | `status == "parked"` → `status == "sent"` in `claim_due` | `test_so11_…` | `claim_due: status, not a NULL next_attempt_at, keeps a sent row out` |
| c5 | corrupt | `CLAIMABLE = ("pending", "parked", "sent")` | mid-compensation case | `exactly one fulfillment.stock.release request, got 2: …` / `assert 2 == 1` |
| c6 | corrupt (wire) | `x-correlation-id` header set to `meta.request_id` | mid-compensation case | `exactly one fulfillment.stock.release request, got 0: …` / `assert 0 == 1` |

c6 is the payload-corruption family against the new count assertion: the count reads the request's actual correlation header (`conftest.py:420-421`, `requests_for` filters on `x-correlation-id`), so a guard that only counted rows would not have caught it.

## Check 1: ruling on the planted state (`test_so11_…`, `test_saga_command_ledger.py:353-366`)

**Accepted, as written, as a guard of an invariant worth keeping — not row 12 in reverse.**

- **Reachability, established rather than assumed:** the writers of `saga_commands.next_attempt_at` are `try_claim` (guarded by `status IN ('pending','parked')`, `command_ledger.py:99`), `claim_due` (sub-select by status, `:114-124`), `mark_sent` (sets it NULL, `:145`) and `park` (refuses a `sent` row, `:157`); `enqueue` is `ON CONFLICT DO NOTHING`. A racing claimer's UPDATE re-evaluates its `WHERE` on the newest row version under READ COMMITTED. So a `sent` row with a non-NULL `next_attempt_at` is unreachable today, and c3 was a genuinely equivalent mutant through the API, as the implementer said.
- **Why it is still worth keeping:** design §7.5's property is "a `sent` row is a no-op claim" — a statement about `status`, which today happens to be doubly enforced (status predicate and the NULL). The reachable half is already guarded by the first block of the same test (c1, c2) and by `test_marks_are_conditional_and_attempts_accumulate` (`next_attempt_at is None` after `mark_sent`). The planted block guards the other half against the write paths that are coming: feature 42 adds a fourth status (`rejected`) and its own mark, and feature 27 adds the retry/DLQ wrapper. If either leaves `next_attempt_at` set on a terminal row, only the status predicate stands between that row and a re-send.
- **Why it is not row 12 in reverse:** row 12 is about a guard that misses a failure served through a path the population never drives. This block cannot fail correct code (correct code excludes `sent` by status whatever `next_attempt_at` holds), so it costs nothing in false alarms; it fails only when the status predicate is gone (c3, c4). It is labelled in the test as an impossible state planted on purpose (lines 353-355), so a reader will not mistake it for a production scenario.

## Check 3: the duration (441 s against 193 s at feature 15's close)

- **When:** the jump happened in **round 1**, not round 2. Round 1's `quality.sh` was already 7 min 08 s (`.arm/q1.time`; pytest 393.68 s), and my round-1 full run was 389.5 s. Round 2 adds 5 tests and **+3.3 s** (my 389.5 s → 392.8 s).
- **Where (junit, 2355 cases, 387.8 s summed):** feature 16's `integration/saga/` package is **224.6 s over 75 cases**, 58 % of the suite (preconditions 57.1 s, consumption 50.7 s, happy path 31.7 s, saga lifespan 22.7 s, credit-rejected 20.1 s, command retry 19.9 s, …). Feature 16's unit saga suite is 2.6 s over 366 cases; the row-lock module 1.3 s; the architecture module 0.1 s. Everything else is about 160 s, which matches feature 15's ≈172 s pytest (193 s total minus feature 14's ≈21 s non-pytest overhead). 172 + 224.6 + 4 ≈ 400 s.
- **Why each saga case costs ≈3.8 s (probe T1, measured):** the Kafka test container does not set `KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS` (`conftest.py:283-300`, no hit for `REBALANCE`), so the broker default of 3 s delays every `orders.saga` group join. Adding `.with_env("KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS", "0")` to the root `conftest.py` (backed up, restored `cmp`-identical, `__pycache__` cleared) took `test_saga_happy_path.py` + `test_saga_preconditions.py` from **22 passed in 98.68 s** (control, restored) to **22 passed in 32.28 s**: 3.0 s per case. Over the ≈62 harness cases that is ≈190 s of the 224.6 s.
- **Not machine load:** the full run used 32 % CPU (user 118.5 s, system 11.8 s over 6:35 wall); load average 1.78 on 16 cores during the arms.
- **For the maintainer at wrap-up (threshold is theirs):** setting the delay to 0 in the root `conftest.py` would bring `quality.sh` back to ≈250 s. It changes broker timing under the SO9 tests, whose round-1 timing margin I noted (1 s pacing), so if adopted, the SO9 arms R3.9a–d / R3.10 / R3.10c / R3.12 must be re-run under the new broker setting in the same change. Light classification (test infrastructure).

## Non-blocking findings (test-only; disposition: fix, light, this phase)

- **N1 — the "exactly at `next_attempt_at`" half of the parked back-off fails without naming its claim.** `test_saga_command_ledger.py:312`: `[due] = await ledger.claim_due(10)` unpacks before the assertion at `:313`, so arm b3 (`<=` → `<`) fails with `ValueError: not enough values to unpack (expected 1, got 0)` instead of `claim_due: the parked row is due exactly at next_attempt_at`. The boundary is guarded (the test does fail, at the right line), but the arming protocol asks for a message naming the claim. Fix: `due = await ledger.claim_due(10)` then `assert [row.id for row in due] == [claimed.id], "claim_due: the parked row is due exactly at next_attempt_at"`. Arm: b3 must then fail with that message.
- **N2 — the reach test's population is not tied to the settings population.** `SAGA_SENTINELS` (`test_orders_host_lifespan.py:637-649`) is a literal of its own; nothing compares it with the `SAGA_*` keys of the variable literal in `services/orders/tests/unit/test_orders_settings_env.py:54-64` (`grep` for `test_orders_settings_env`, `model_fields` or the unit literal in the lifespan module: no hit besides the dict itself). Today both hold the same 11 names. A twelfth `SAGA_*` variable (features 27 and 42 both touch this area) would fail the unit population test, be added there, and could be left out of the reach test silently — the exact recurrence path of #8 id 56 in features 15 and 16. Fix: one assertion that `set(SAGA_SENTINELS) == {name for name in <unit literal> if name.startswith("SAGA_")}` (import or a shared literal). Arm: add a 12th `SAGA_*` entry to the unit literal only; the reach test must fail naming the missing variable.

Both are mechanical test edits (route to `test_maintainer`, leader verifies each with its one arm, per the light rule). I am not rejecting for them: neither is a wrong line of behaviour, both guards fail today under the mutations that matter, and a third round would need the maintainer.

## Routing (for the leader, not narration)

- **No `specs/shared/` root cause found in round 2; no `SA-n` proposed.** `specs/shared/` is byte-identical to #8 except `test-matrix.md` (`cmp` over 7 files: 6 same, `test-matrix.md` differs as expected). The three matrix cells R24/R28/R29 now name the ratification (`grep -c "ratified at the feature 16 spec gate"` = 3); derived counts unchanged (11 / 8 / 0 / 3).
- **Round-1 routing item still unfiled:** round 1 said feature 42 must change `park`'s `status <> 'sent'` predicate (`command_ledger.py:157`) when it adds `rejected`, or `park` would move a `rejected` row to `parked`. Feature 42's `acceptance` in `feature_list.json` still has only its three original items (read this session). It should be attached to 42 as an acceptance item (the leader files it; I do not write `feature_list.json` beyond 16's status line).
- `requirements.md` §5's "raw string" wording (round 1 Q5): fixed by the leader (`requirements.md:163`, "becomes a plain `SagaCommandTransportError` with no `code`").
- #8 id 94 → feature 27 and #8 id 91 → feature 41: attached (`feature_list.json` lines 506 and 460).

## CHECKPOINTS walked (round 2)

**C1**
- [x] Harness files exist; seven agent definitions; models declared or deliberately inherited.
- [x] `./init.sh` exit 0.

**C2**
- [x] At most one feature in progress: 0 `in_progress`, 1 `in_review` (16) before my edit; 30 `done`, 25 `pending` after it.
- [x] Every status valid; no `blocked`.
- [x] Every `done` feature has passing tests: 2355 passed.
- [ ] `current.md`: leader-owned, not checked.

**C3**
- [x] `lint-imports` 11 kept (domain and `shared_kernel` purity, independence, `otc_cqrs` not imported by `domain`).
- [x] No cross-service access; no new database, service or shared runtime package; `packages/` untouched by round 2.
- [x] No domain money arithmetic: round 2 touched no `src/` file.
- [x] Interactions classified (Kafka facts, NATS commands) — unchanged since round 1's armed checks.
- [x] No debug output in the new tests (the new cases contain no `print(`).

**C4**
- [x] mypy, ruff, lint-imports clean; pytest 2355 passed. Coverage and web gates from the record (98.70 %).
- [x] Integration tests use real PostgreSQL, Kafka and NATS containers and pass with the developer stack down (only `otcpy-n8n` running before and after).
- [x] No Jest, Karma or Jasmine.

**C5**
- [x] No suspicious untracked files: round 2 added none outside `.arm/` (git-ignored, `.gitignore:87`).
- [x] `history.md` effort entry written (both rounds, the session incidents).
- [x] `feature_list.json`: 16 set to `done` (that line only).
- [x] Manual test instructions: impl record §14.2.
- [x] Claude did not commit.

**C6**
- [x] `specs/order_saga_orchestrator/` complete; EARS requirements with ids; 101/101 tasks ticked, and round 1's caveat on 14.4 is now discharged (D1–D3 armed).
- [x] Every R19–R29 named in the matrix.
- [ ] Spec commit before the implementation commit: wrap-up.

**C7**
- [x] `specs/shared/` byte-identical to #8 except `test-matrix.md`.
- [x] No unrecorded deviation; no `SA-n` needed.
- [x] Inherited findings accounted for: #8 id 56 now in the record's §18 tally as recurred in round 1 and closed in round 2.
- [x] Effort honesty: the history entry records the reboot, the orphaned processes, both rounds and the duration cause.
- [ ] n8n, API script, README benchmark: n/a.

## R<n> → test mapping (delta from round 1)

Round 1's mapping stands (`src/` unchanged). Additions:

| Id | Test | Arm(s), round 2 |
|---|---|---|
| SO5 (back-off half, was open) | `test_saga_command_ledger.py::test_so5_a_parked_rows_backoff_is_enforced_on_both_claims_and_ends_exactly_at_next_attempt_at`, `::test_so5_a_parked_rows_backoff_ends_exactly_at_next_attempt_at_for_the_fast_path_claim` | b1, b2, b2', b3 (N1), b4 |
| SO11 (`sent` no-op claim, was open) | `test_saga_command_ledger.py::test_so11_a_sent_row_is_a_no_op_claim_for_both_claims_even_long_after_any_lease`; `test_saga_preconditions.py::test_credit_rejected_redelivered_with_a_new_event_id_mid_compensation_…` (exactly one `stock.release` request) | c1, c1', c2, c3, c4, c5, c6 |
| SO13 / SO16 / SO4 / SO5 settings reach (D1, was open) | `test_orders_host_lifespan.py::test_every_saga_setting_the_composition_root_reads_reaches_the_object_it_configures`, `::test_the_saga_enable_flags_decide_which_tasks_exist` | a1–a14 |

Each name has exactly one `def` (checked with `grep -n "def test_"` over the two modules).

**After the transition to `done` (13:39):** `./init.sh` now exits 1 on exactly one check, `progress/current.md claims a feature while none is active: "**Feature:** \`order_saga_orchestrator\` (id 16, phase 8)"`. All other checks are OK, including the backlog tripwire ("no feature lost, no done reverted"). `current.md` is the leader's to update; my bounds do not include it. `./init.sh` exited 0 before the status edit, as recorded above.
