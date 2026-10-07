# Review: feature 14 `outbox_and_idempotency` (phase 8, `sdd: true`, full group: persistence, wire contract)

**Verdict: REJECTED** (round 1). The outbox, the relay, the publisher and the canonical consumer are correct on every path I attacked (17 of my 21 mutants killed, the claim measured, the full suite green). Rejected on four guard gaps, all test-side (the code under them is correct), three of them on properties the ported-idiom ledger says #9 hand-builds: the relay loop's **cancellation during the inter-cycle sleep** (L8), the loop's **pacing** (L18, acceptance item 3 "self-scheduled"), the **deadlock-retry backoff** (L17), and a **dynamic-import blind spot** in A1's case 2. Each one is a survivor I produced with a one-line mutation. The fix is four small tests or test edits, and no `src` change. Status set back to `in_progress` (`feature_list.json` line 262 only).

## What I ran, and what I did not

- **The feature's 21 new test modules** (every new file of `design.md` §11.1 plus `test_kafka_fixture.py`, `test_system_clock.py` and the seed sentinel): `139 passed in 34.81s`, with testcontainers and the developer stack down (`docker ps`: only `otcpy-n8n`; `ss -ltn` on 5432/9092/4222/27017/29092: nothing listening).
- **`./quality.sh`, once, after A1**, because the implementer's run predates A1 and A1 changed `src`: `quality.sh: all gates passed`, **EXIT 0, ELAPSED 154 s**, `1648 passed in 130.98s`, total coverage **98.44 %** (gate 60), domain + kernel TOTAL **98 %** (gate 80), stack down. This full run was justified because the claim under test (green after A1) is about the full suite.
- `uv run lint-imports`: `Contracts: 11 kept, 0 broken.`. `uv run mypy`: `Success: no issues found in 292 source files`. `ruff check`: `All checks passed!`. `ruff format --check`: `361 files already formatted`. `./init.sh`: exit 0.
- **21 mutation arms of my own** (ids A1–H2 below are mine, unrelated to amendment A1). Each used `scratchpad/arm.py`: backup, exactly one textual mutation (the script aborts if the text matches 0 or ≥2 times), run the named test(s), restore, `cmp`, delete `__pycache__`. After all of them, a sha256 snapshot of the 290 `.py` files under `services packages tests conftest.py` taken before the first arm was identical to one taken after the last (`diff before.sha after.sha` printed nothing).
- **Not re-run:** the implementer's own arming table (I re-armed each item a different way instead) and the 214-mutant constructor sweep (I probed the sites outside its census instead, Q3).

## Answers to the brief's questions

### 1. Re-armed, not re-read (each one differs from the implementer's mutation)

| # | Item | My mutation | Named test | Result |
|---|---|---|---|---|
| A1 | SKIP LOCKED | claim `with_for_update(skip_locked=True, read=True)` (`FOR SHARE SKIP LOCKED`: share locks do not exclude each other) | `test_oi4_two_concurrent_relays_take_disjoint_batches_and_publish_every_record_exactly_once` | killed: `AssertionError: a record went to both relays` |
| A1b | skip versus block | same mutation | `test_oi13_a_claim_skips_rows_another_relay_holds_and_returns_without_waiting` | killed: `Failed: relay B BLOCKED on rows relay A holds` (B takes the same rows under a share lock, then its stamp blocks on A; the diagnosis text says "does not skip", the true block is on the stamp. Cosmetic, no action) |
| — | skip versus block, measured | (none) | same test, `-s`, run twice | `relay B returned in 0.038s` and `0.037s` while A held its claim (implementer: 0.033 to 0.038 s). Reproduced |
| B1 | deadlock retry, exhaustion | after `DEADLOCK_ATTEMPTS` victims, return `RelayResult(0,0,None)` instead of raising | `test_run_once_retries_a_deadlock_victim_up_to_the_bound_then_lets_it_escape` | killed: `Failed: DID NOT RAISE DBAPIError` |
| B2 | deadlock retry, **pacing** | delete `await asyncio.sleep(DEADLOCK_BACKOFF_SECONDS)` | `test_deadlock_classifier.py` + `test_outbox_relay_deadlock.py` | **SURVIVED: `8 passed`** (finding F3) |
| P1 | poison: no silent drop | `row_ids.append(row.id)` moved before the conversion, so the poison row is **stamped** without being published | both OI18 tests | killed: `{...97023: True} != {...97023: False}` |
| P2 | poison: loud | the poison log demoted `log.error` → `log.warning` | same | killed: `one ERROR record, naming the poison row / assert 0 == 1` |
| P3 | poison: payload of the log | the log's `eventId` written from `correlation_id` (corrupt a field) | same | killed: `assert 'a34d127e-…' == 'd5e08cfc-…'` |
| D1 | dedupe, corrupt field | the dedup insert writes `event_id=uuid4()` | `test_r18_acknowledges_a_redelivered_fact_…` | killed: `PROCESSED is DUPLICATE` |
| D3 | dedupe, corrupt field | `consumer=consumer.name` (`ORDERS_SAGA`, not `orders.saga`) | `test_r17_records_the_event_id_and_consumer_name_…` | killed: `'ORDERS_SAGA') != (…, 'orders.saga')` |
| M1 | 205, agreement on a WRONG value | `wire_instant` truncates to 10 ms (store, envelope and payload would all still **agree**) | `test_oi19_a_sub_millisecond_instant_is_stored_enveloped_and_written_in_the_payload_as_the_same_millisecond` | killed: `…5, 120000 … == …5, 123000` (the test asserts the literal millisecond, not just agreement) |
| M2 | 205, UTC | `wire_instant` drops `.astimezone(UTC)` | `test_wire_instant_truncates_and_agrees_with_format_instant` | killed: `timedelta(seconds=7200) == timedelta(0)` |
| E1 | 203 item 2 | `to_wire_json` loses its top-level `model_validate` (the JSON-mode re-dump still refuses) | `test_oi20_a_payload_copied_past_validation_is_refused_by_model_dump_json_and_by_to_wire_json` | killed, but by exception type (`PydanticSerializationError` where the test expects `ValidationError`). Belt and braces: the second check still refuses, as designed |
| E2 | 203 item 2 | `to_wire_json` loses **both** validations | same | killed: `Failed: DID NOT RAISE ValidationError` |

### 2. Ordering: can a later fact of one order go out ahead of an earlier one (R15, OI8)?

- **Retry (OI8, OI14, OI17): no.** A failed or timed-out batch rolls back and is reclaimed in `seq` order. A record already acknowledged is published again after it (at-least-once, deduplicated by R17/R18), never ahead of an earlier one. A synchronous `send` failure marks `facts[index:]` failed and stops issuing sends (`kafka_publisher.py`, the `break`), so no later record is sent after an earlier one failed to enqueue. Cancelling `gather` on timeout does not withdraw records aiokafka already batched. They are delivered and then republished in the same order. aiokafka mutes a partition while a batch of it is in flight (`producer/sender.py:141-150, 290`, verified on disk).
- **Poison (OI18): no**, for one relay. `build_prefix` stops at the first unconvertible row, and only the prefix's ids are stamped. Arm P1 shows the poison row cannot be stamped silently.
- **A second relay: YES, by construction.** Relay B skip-locks past A's held claim and publishes later `seq`s, which may belong to the same order. The OI13 test itself is the demonstration (B returns rows disjoint from, and later than, A's while A holds). `design.md` §5.2 declares this ("ordering between two relays is not claimed … `R15` is a single-relay guarantee"), as #8 did (`design.md` §5.2). → **N1** (accepted here; the enforcement half is routed to feature 15).

### 3. Field mapping: sites outside the 214-mutant census

I enumerated the call sites with two or more arguments (`scratchpad/sites.py`, an AST walk) in the new `src` files the census table does not list: `settings.py` (11 `Field`s with aliases), `event_envelope.py` (4 `_require_id(name, value)`), `publisher.py`, `relay_task.py`, `unit_of_work.py` (2 constructors, both in the census), `errors.py`. I also probed two sibling substitutions inside census files that the census reports as a whole:

| # | Mutation | Result |
|---|---|---|
| F1 | `wire.py` key `str(row.aggregate_id)` instead of `str(row.correlation_id)` (siblings that are equal for every real order) | killed by `test_oi1_every_column_and_envelope_field_comes_from_its_own_event_field`: `keyed by the correlation id` |
| F2 | `wire.py` header `x-event-type` fixed to `b"order.placed.v1"` | killed: `('x-event-type', b'order.placed.v1') != ('x-event-type', b'order.confirmed.v1')` |
| G1 | `_require_id("correlation_id", aggregate_id)` (kernel guard, sibling value) | killed: `DID NOT RAISE …[correlation_id-none]` |
| G2 | `poll_interval_ms` alias → `"OUTBOX_PUBLISH_TIMEOUT_MS"` (sibling alias) | killed: `Extra items in the right set: 'OUTBOX_POLL_INTERVAL_MS'` |

No mapping site the census missed survived.

### 4. Python-specific

- **Loop affinity:** `KafkaFactPublisher.__init__` builds nothing, `start()` builds the producer in the running loop (arm 4.4b, implementer's). Every engine, sessionmaker, publisher and test consumer fixture is `loop_scope="function"` and is disposed in the same loop (`services/orders/tests/integration/conftest.py:80-95, 143-146, 277-288, 322-372`). The Kafka container is a sync session fixture, and its admin client lives inside one `asyncio.run`. Holds.
- **Cancellation of the relay loop: the code is correct, the guard is not.** `test_relay_task_propagates_cancellation` cancels only while `run_once` blocks. A cancellation during the inter-cycle sleep, which is where an idle relay spends almost all its time, is never driven → **F1**.
- **Exception propagation out of `run_once`:** a non-`40P01` `DBAPIError` escapes after one cycle (unit case `other.cycles == 1`). A publish failure or timeout becomes a result. Anything else propagates to the loop, which logs it and continues (arm 5.3). Holds.
- **`Any` from aiokafka:** `grep -rn "\bAny\b"` over `outbox/`, `messaging/`, the three persistence modules, `application/` and `envelope.py` finds 2 code hits, both in `outbox/wire.py` (`:17` import, `:25` `Envelope[dict[str, Any]]`, the designed pass-through). The other 2 hits are docstrings in `envelope.py`. `kafka_publisher.py` assigns the `Any` `AIOKafkaProducer` to a `_Producer` Protocol variable. There is no `type: ignore` in `services/orders/src` or `packages/*/src` (empty search), and the only `[[tool.mypy.overrides]]` is `aiokafka.*` (`pyproject.toml:98-100`). Holds.
- **Serializer:** one `to_wire_json` (compact separators, `ensure_ascii=False`, `allow_nan=False`, `.mmmZ` via `_default`/`format_instant`). Byte parity is armed by the implementer's 4.14a–c, and the header by my F2. **`json` not `jsonb`:** `grep -rn "jsonb\|JSONB" services/orders/src services/orders/alembic` finds 3 hits, all prose saying "not `jsonb`" (`types.py:5`, `models.py:4`, `0001_initial_orders_schema.py:4`). There is no `jsonb` type.
- **`except BaseException` / bare `except:`** in `services/orders/src` and `packages/*/src`: the search returned nothing.

### 5. A1 and the §11 divergences

- **A1, the single allowed relative import, is sound.** The shape check compares `(module, names)` at `level == 1`, so widening the one import (`from .consumer_name import ConsumerName, Extra`, arm H1) is caught: `relative import .consumer_name is not allowed`. The whole body is scanned and the implementer armed the enum's return.
- **A1 does not see a dynamic import (arm H2, survived):** `import importlib; _DRIVER = importlib.import_module("redis")` added to the canonical leaves case 2 `1 passed`. The canonical's banner claims "imports only the standard library and `sqlalchemy`". This repository's own sibling instrument already closes this form: `tests/architecture/test_money_guard.py`'s docstring, "any reference to `__import__` / `import_module` … fails". → **F4**.
- **§11.4 (R15 precondition read from the broker):** a strengthening. Not a weakening.
- **§11.5 (`float` seconds in `OutboxRelay` / `OutboxRelayTask`):** `design.md` §5.1 (`publish_timeout: float`) and §5.6 (`poll_interval: float`) declare exactly these signatures. Task 8.4's search expectation was narrower than the design it implements. Timing, not money. Not a weakening.
- **§11.9 (arm 4.8a2 survived the first OI2 case):** the second OI2 case discriminates the ordering key (arms 4.8a, 4.8b), and the first still guards append order (arm 4.8c). Accepted.
- **§11.10 (the second R13 case fails by exception type under "commit on exception"):** PostgreSQL aborts the transaction on the `IntegrityError`, so no commit can persist anything there. The case's state assertion guards a different regression (a per-save commit). Accepted. **Re-open only if** the unit of work gains a savepoint (`begin_nested`) or any per-save commit.

### 6. The 153 s

- **My run, after A1: 154 s wall, pytest 130.98 s, 1648 passed, stack down.** That matches the implementer's 153 s pre-A1. A1 adds no measurable time.
- **What this feature costs:** its 21 modules run standalone in **34.8 s wall** (`--durations=0`, summed per module: setup 15.8 s, call 13.5 s, teardown 5.1 s). Within that:
  - Kafka container start: **4.5 s** once per session (`test_kafka_fixture.py` setup).
  - Postgres container start: **1.8 s**, shared with the rest of the suite in a full run.
  - Seed fixture: **1.9 s** setup plus 1.2 s teardown.
  - Two deadlock tests at **1.1 – 1.5 s** each. This is inherent: `deadlock_timeout = 1s` must expire.
  - A migrated database per integration test at about 0.15 s × ~95 tests.

  Per module: seed sentinel 5.94 s, kafka fixture 4.63, relay 4.32, deployed-server fixture 3.57, envelope 3.10, deadlock 2.89, wire parity 2.79, concurrency 1.97, repository 1.84, consumer 1.46, atomicity 0.75, partitioning 0.37, the unit modules < 0.3 each.
- **The ~125 s threshold:** Phase 7 measured 103 s for 1290 tests. Features 13 and 43 added 216 tests (their 142 s run had the stack up, so it is not comparable). This feature adds ~35 s of standalone wall time for 138 tests. The overrun against ~125 s is these two increments, not a regression.
- **Fixture scopes match their comments:** database, engine and publisher are per test (`loop_scope="function"`, as commented), and Kafka is per session, as commented. Nothing is scoped wider or narrower than its comment says.

### 7. Counts

- **1648 vs 1644, reconciled per file:** I collected (`uv run pytest --collect-only -q`, grouped per file, 123 files, sum 1648) and diffed against the implementer's 123-line list. Exactly one line differs: `13 → 17 services/orders/tests/unit/test_idempotent_consumer_parity.py`. These are A1's four new sentinels.
- **1644 = 1506 + 138:** the 21 new modules collect 139 now, 135 before A1. The other +3 are in census-parametrised existing files: `test_kernel_surface.py` has two tests parametrised over `MODULE_NAMES`, and `event_envelope` was added; `test_money_guard.py` has a per-file case and its census went 46 → 47. That +3 split was read from the parametrisation, not checked against a per-file list of the 1506 run (none is on disk).
- **Matrix column 5:** for every name in rows R11–R15, R17, R18 (parsed from the cells, not from the report), a `def <name>(` search in the cited file finds exactly one definition (11 names, each count 1). R16 is `TODO`. The derived counts are row 2 = 8/7/0/1 and Total = 63/16/1/46. Every file in `specs/shared/` except `test-matrix.md` is `cmp`-identical with #8's and #7's.

## Findings

Each finding below needs a test or test-instrument change only; no `src` change is asked for.

**F1 — blocking. Ledger L8's guard does not execute the code L8 is about.**
- **Where:** `services/orders/tests/unit/test_outbox_relay_task.py` (`test_relay_task_propagates_cancellation`) vs `services/orders/src/otc_orders/infrastructure/outbox/relay_task.py:42-43`.
- **Defeat list:** row 12, a path the population never drives.
- **The gap:** L8's #9 half says the loop suppresses only `TimeoutError` and `CancelledError` propagates. The only cancellation test cancels while `run_once` blocks.
- **Mutation:** `contextlib.suppress(TimeoutError, asyncio.CancelledError)` on the sleep → `5 passed`.
- **Behaviour under the mutant** (`scratchpad/cancel_probe.py`, poll interval 0.5 s, cancelled 50 ms into the sleep):
  - mutated: `task done: False … cycles: 5`. The cancellation is swallowed and the loop keeps polling, which would hang feature 15's shutdown.
  - real code: `task done: True cancelled(): True cycles: 1`.
- **Why it matters:** the brief's Q4 and CLAUDE.md's *Async* row ("cancellation propagated, never swallowed").

**F2 — blocking. The loop's pacing is unguarded.**
- **Where:** `relay_task.py:42-43`; the guard should live in `test_outbox_relay_task.py`.
- **Mutation:** `await asyncio.wait_for(stop.wait(), timeout=self._poll_interval)` → `await asyncio.sleep(0)` → `5 passed`. The relay becomes a busy loop.
- **What claims the pacing:**
  - acceptance item 3 ("relay loop self-scheduled");
  - L18 (guard 5.2);
  - `design.md` §5.8 ("the ERROR line repeats once per poll interval (paced by §5.6's sleep, so the retry rate is bounded)"), which is G1's loudness bound;
  - the Plan item in `progress/current.md:64` ("self-scheduled `asyncio.sleep`");
  - CLAUDE.md ("Retry loops: pace them explicitly, and prove the pacing with a change of kind, not of probability").
- **The gap:** no test runs a non-blocking `run_once` and observes the interval.

**F3 — blocking (same class, smaller). The deadlock-retry backoff is unguarded.**
- **Where:** `services/orders/tests/unit/test_deadlock_classifier.py`, `test_run_once_retries_a_deadlock_victim_up_to_the_bound_then_lets_it_escape`, which monkeypatches `asyncio.sleep` to `no_wait(_)` and discards the argument. The code is `relay.py:142-148`.
- **Mutation:** delete `await asyncio.sleep(DEADLOCK_BACKOFF_SECONDS)` → `8 passed` (unit and integration deadlock files).
- **Why it matters:** L17 states "3 attempts, 200 ms (#8's numbers)", and CLAUDE.md's retry-pacing rule applies.

**F4 — minor, fixed in this round because it is cheap. A1's case 2 does not recognise a dynamic import.**
- **Where:** `services/orders/tests/unit/test_idempotent_consumer_parity.py:81-108` (`adoptability_problems`).
- **Defeat list:** row 11.
- **Mutation:** arm H2 (`importlib.import_module("redis")` in the canonical) → `1 passed`.
- **Precedent:** `tests/architecture/test_money_guard.py` refuses any `__import__` / `import_module` reference for exactly this reason.

**N1 — accepted here, enforcement routed. R15 is a single-relay guarantee and nothing enforces a single relay.**
- **Why it holds:** `design.md` §5.2 and #8 `design.md` §5.2 say R15 is a single-relay guarantee, and the OI13 test demonstrates the out-of-order publication two relays can produce (Q2). The shared R15 text is not wrong: it binds the system, and one relay per write model satisfies it. So this needs no `SA-n` and no backlog entry. It is an enforcement item for the code that starts the relay.
- **Disposition:** ACCEPTED, NOT FIXED in feature 14 (the starter does not exist yet).
- **Route:** the leader should add an acceptance item to **feature 15** (`orders_acceptance`, which already carries "the orders lifespan starts the outbox relay task"). The item: *at most one relay task per orders process, and the service is run as a single process (no `uvicorn --workers > 1`) while `OUTBOX_RELAY_ENABLED=true`, or the second process is refused at boot; proven by a test, armed*.
- **Re-open trigger:** any compose, script or Dockerfile that starts more than one orders process or replica with the relay enabled.

**Accepted with evidence:** §11.9 and §11.10, as in Q5. §11.4 and §11.5 are not weakenings.

**Inherited findings (design §13):** I re-armed the relevant ones in a new way:
- #8 87: B1;
- #8 111: P1–P3;
- #8 D2/D3: D1;
- #7 D10: D3 plus the implementer's 6.2/6.3;
- #8 104: stack down for my full run.

All held. None recurred.

## What must change before re-review

Round 2: test-side only. No `src` file may change; if one must, say why.

1. **F1:** add `test_relay_task_propagates_a_cancellation_that_arrives_during_the_inter_cycle_sleep` to `test_outbox_relay_task.py`.
   - Setup: a non-blocking fake `run_once` that sets an event, and `poll_interval=10`.
   - Steps: wait for the first cycle, yield, then `task.cancel()`.
   - Assertions: the task is done within 2 s and `task.cancelled() is True`, and `run_once` was entered exactly once.
   - Arm: `contextlib.suppress(TimeoutError, asyncio.CancelledError)` at `relay_task.py:42`. Record the failure verbatim.
2. **F2:** add `test_relay_task_waits_the_poll_interval_between_cycles_and_stop_cuts_the_wait_short` to `test_outbox_relay_task.py`.
   - The pacing, as a change of kind: with a non-blocking fake and `poll_interval=10`, after the first cycle has returned and ≥ 0.2 s has passed, `run_once` has been entered exactly once.
   - The interruptible sleep: then `stop.set()` ends the task within 2 s, so it did not sleep the full 10 s.
   - Arm (a): `await asyncio.sleep(0)` in place of the `wait_for`; the entry count must fail.
   - Arm (b): `await asyncio.sleep(self._poll_interval)` (not interruptible); the 2 s bound must fail.
   - Record both failures verbatim.
3. **F3:** in `test_run_once_retries_a_deadlock_victim_up_to_the_bound_then_lets_it_escape`, make `no_wait` record its argument.
   - Assertion: the recorded sleeps equal `[0.2, 0.2]` for the exhausted case and `[0.2]` for the survivor. These are literals from design L17, not the constant compared with itself (defeat row 8).
   - Arm: delete the `asyncio.sleep` at `relay.py:148`; separately, change `DEADLOCK_BACKOFF_SECONDS` to `0`. Record both failures verbatim.
4. **F4:** in `adoptability_problems`, report any `importlib` import and any reference to `__import__` or `import_module` in the canonical body, as the money guard does.
   - Add a sentinel case with H2's two lines.
   - Arm by removing the new check (the sentinel must fail) and confirm the real canonical still passes.
5. **Afterwards:**
   - add the new test names to `requirements.md` §3's OI6 row (OI6's guard family) and OI17's row (F3's case is already listed there; no rename);
   - update the impl report's arming table and per-file counts (expected `test_outbox_relay_task.py` 5 → 7, `test_idempotent_consumer_parity.py` 17 → 18; reconcile against a real `--collect-only`);
   - run the four touched files and the orders unit suite. No full `quality.sh` is needed for a test-only round unless something outside these two files changes.

## CHECKPOINTS.md (walked for this feature)

**C1**
- [x] Harness files exist (`AGENTS.md`, `CLAUDE.md`, `CHECKPOINTS.md`, `feature_list.json`, `init.sh`).
- [x] `progress/current.md` and `history.md` exist.
- [x] `.claude/agents/` holds the seven definitions (listed).
- [x] Model declarations: not re-audited this feature; unchanged files.
- [x] `./init.sh` exit 0.

**C2**
- [x] At most one `in_progress` (after my edit: feature 14 only).
- [x] Statuses valid.
- [x] `done` features have passing tests (full run green).
- [x] `current.md` names this feature (`progress/current.md:3`).
- [x] No `blocked`.

**C3**
- [x] `lint-imports` 11 kept, 0 broken (domain purity, kernel, layers, independence, the new `fact-producer-confinement`).
- [x] No cross-service database access or import (independence contract kept; the canonical names no service, case 2).
- [x] No new shared runtime package.
- [x] No `domain` imports `otc_cqrs`.
- [x] `dependencies = []` unchanged for kernel and cqrs (not in the diff).
- [x] No `float`, `Decimal` or `/` in domain money (money guard green in my full run; the outbox path copies `int`).
- [x] Kafka carries facts only (the relay publishes facts; no RPC added).
- [x] No stray debug logging or context-free TODOs in the new `src` (read).

**C4**
- [x] `./quality.sh` passes (EXIT 0, 154 s).
- [x] Domain tests pure (the R11 test is a kernel unit test; `test_domain_tests_are_pure.py` green).
- [x] Real Postgres and Kafka via testcontainers, stack down.
- [x] Coverage 98.44 % overall / 98 % domain + kernel.
- [x] No Jest, Karma or Jasmine (unchanged).
- [ ] **Every guard on a hand-built property seen to fail:** F1–F4 are survivors. This is the reason for the rejection.

**C5**
- [x] No stray files (`find … -size 0` empty; no `*.tmp`, `*.bak` or arm leftovers in the tree; snapshot identical).
- [ ] History entry with effort record: not applicable on rejection.
- [x] `feature_list.json` reflects the true state (`in_progress`).
- [x] Manual test steps exist (impl report §15).
- [x] Claude did not commit (no git write by me).

**C6**
- [x] `specs/outbox_and_idempotency/` has all three files.
- [x] Requirements are EARS with `R<n>` / `OI<n>` ids.
- [ ] All tasks ticked **and true**: 5.4's "propagates cancellation" and the L18/L17 pacing are ticked but under-guarded (F1–F3).
- [x] Every R11–R15, R17, R18 has a named, existing, green test (R16 deferred to feature 27, decided).
- [ ] Spec commit precedes the implementation commit: nothing is committed yet. The leader's wrap-up must commit the spec first.

**C7**
- [x] `specs/shared/` is `cmp`-identical to #8 and #7 except `test-matrix.md`.
- [x] No silent fork (no `SA-n` needed; N1 is not rooted in `specs/shared/`).
- [x] The `R<n>` claims hold behaviourally (Q1 arms).
- [x] Inherited findings accounted for (impl §13, re-armed above).
- [ ] Effort record: written at approval, not now.

## R<n> → test mapping (verified)

| Id | Test(s) | Verified by |
|---|---|---|
| R11 | `test_event_envelope.py` › `test_r11_event_envelope_refuses_…`, `test_r11_event_envelope_accepts_…`; `test_outbox_wire_parity.py` › `test_r11_published_envelope_carries_…` | run green; my G1 kills the refusal case; the implementer's 4.14g kills the published case |
| R12 | `test_outbox_envelope.py` › `test_r12_stamps_every_fact_…` | run green; implementer's 3.12a/b, my F1 (key sibling) on the companion OI1 case |
| R13 | `test_outbox_atomicity.py` › `test_r13_persists_neither_…`, `test_r13_rolls_back_an_outbox_row_…` | run green; implementer's 3.10a/a2/b; §11.10 accepted |
| R14 | `test_outbox_relay.py` › `test_r14_stamps_a_record_only_after_…` | run green (real broker read-back); implementer's 4.7 |
| R15 | `test_fact_partitioning.py` › `test_r15_delivers_all_facts_…` | run green; implementer's 4.13a/b; my F1; N1 (single relay) |
| R16 | — | `TODO`, deferred to feature 27 (decided, `requirements.md` §1.2) |
| R17 | `test_idempotent_consumer.py` › `test_r17_records_the_event_id_…`, `test_r17_leaves_no_dedup_row_…` | run green; my D3 |
| R18 | `test_idempotent_consumer.py` › `test_r18_acknowledges_a_redelivered_fact_…` | run green; my D1 |

Local OI1–OI20 rows in `requirements.md` §3: names exist and run green. OI6 is short two cases (F1, F2) and OI17 one assertion (F3).

## Defeat list rows applied in my probes

- 1, delete: B2, C1, P2 (demotion).
- 2, corrupt a supplied field: D1, D3, P3, M1, F2.
- 3, sibling identifier: F1 (`aggregate_id` key), G1, G2.
- 5, dead region: not used.
- 8, literal against literal: F3's required fix avoids it.
- 11, unrecognised form: H2 (dynamic import), A1 (`FOR SHARE`).
- 12, unpopulated path: C2 (cancellation during the sleep).
- Rows 4 and 6 (comment or string shadowing) do not apply to behavioural tests, and the implementer recorded them for import-linter (7.2c).

---

## Round 2

**Verdict: REJECTED** (round 2, the last round before the maintainer decides).
- **F1–F4 are closed.** Every one of my round-1 mutations now fails a named test.
- **One new finding blocks approval: R2-F1.** My fresh probe found that the Kafka adapter's "stop sending after a failed send" behaviour has no test. That is the ordering clause of OI8 ("SHALL NOT … publish a later record ahead of them") at the adapter, and I relied on it myself in round 1's Q2 answer without arming it. That was my miss in round 1.
- **The fix is one unit test, with no `src` change.**
- Status set back to `in_progress` (`feature_list.json` line 262 only).

### What I ran

1. **No `src` change since round 1, confirmed by command.** A sha256 snapshot of all 290 `.py` files under `services packages tests conftest.py`, diffed against my round-1 closing snapshot, differs in exactly 3 files. All three are tests: `services/orders/tests/unit/test_deadlock_classifier.py`, `test_idempotent_consumer_parity.py`, `test_outbox_relay_task.py`. Nothing under `services/*/src` or `packages/*/src` changed.
2. **My round-1 mutations, re-run with `scratchpad/arm.py`:** backup, one exact mutation, run, restore, `cmp`, `__pycache__` cleared.

| Arm | Mutation | Result, verbatim |
|---|---|---|
| F1 | `contextlib.suppress(TimeoutError, asyncio.CancelledError)` at `relay_task.py:42` | killed: `AssertionError: the cancellation was swallowed during the sleep: the loop polls on` (`test_relay_task_propagates_a_cancellation_that_arrives_during_the_inter_cycle_sleep`) |
| F2a | `wait_for(...)` → `await asyncio.sleep(0)`, run against the pacing test alone (with `-x` over the whole file, the F1 test fails first) | killed: `AssertionError: a second cycle ran inside the poll interval: no pacing / assert 41436 == 1` |
| F2b | `await asyncio.sleep(self._poll_interval)` (not interruptible) | killed: `AssertionError: stop did not end the wait: the sleep is not interruptible` |
| F3a | `await asyncio.sleep(DEADLOCK_BACKOFF_SECONDS)` → `pass` | killed: `the backoff between deadlock retries is 200 ms, once per retry / assert [] == [0.2, 0.2]` |
| F3b | `DEADLOCK_BACKOFF_SECONDS = 0` | killed: `assert [0, 0] == [0.2, 0.2]` |
| F4 | `import importlib; _DRIVER = importlib.import_module("redis")` in the canonical (round 1's H2), against `test_case_2_the_canonical_is_adoptable_verbatim_naming_no_service` | killed: `Left contains 2 more items, first extra item: "imports 'importlib': a dynamic import hides its module"` |
| F4b | `_DRIVER = __import__("redis")` in the canonical (a form the implementer did not arm) | killed: `"references '__import__': a dynamic import hides its module"` |

F3 asserts the literals `[0.2, 0.2]` and `[0.2]`, not the constant against itself, so defeat row 8 is avoided.

3. **Counts and green runs.** `uv run pytest --collect-only -q` collects **1651**, which is 1648 + 3: `test_outbox_relay_task.py` went 5 → 7 and `test_idempotent_consumer_parity.py` 17 → 18. `uv run pytest services/orders/tests/unit` gives `208 passed in 1.80s`. A second full `quality.sh` was not run: the round changed three unit-test files and no `src`, and I ran all three.
4. **`requirements.md` §3 rows.**
   - OI6 (line 122) now lists both new relay-task tests; each name has exactly one `def` (`grep`).
   - OI17 (line 133) already lists `test_run_once_retries_a_deadlock_victim_up_to_the_bound_then_lets_it_escape`, the case F3 strengthened. Correct, and no rename.
   - OI12 lists its four cases; the new F4 sentinel is a sentinel of case 2 and is not listed, which is consistent with how the round-1 sentinels were handled. Correct.
   - No shared matrix row changed, as expected: R11–R18 are untouched by this round.
5. **After all probes:** the snapshot is identical to the round-2 starting snapshot, and no stray `pytest` process is left (`ps` count 0).

### Fresh, unrequested probes

| Probe | Mutation | Result |
|---|---|---|
| N1 | `relay_task.py`: `while not stop.is_set():` → `while True:` | **Detected only as a hang**, not as a named failure. With a `run_once` fake that never suspends and `stop` already set, the loop never yields, so no asyncio timeout in the test can fire. The orphaned pytest process reached 21 GB RSS and I killed it (PID 2931448), and `arm.py` restored the file (`cmp`-identical). The real code exits on `stop`, and the production `run_once` always awaits I/O. **Disposition: ACCEPTED, NOT FIXED** (the repository has no per-test timeout; that is a suite-wide policy question, not this feature's). **Re-open trigger:** any CI job that runs pytest without a wall-clock bound. |
| N2 | `kafka_publisher.py:78`: `failed = [... facts[index:]]` → `facts[index + 1 :]` (the failing fact drops out of its own error) | **SURVIVED:** `17 passed` (`test_kafka_fact_publisher.py` + `test_outbox_relay.py`) |
| N3 | `kafka_publisher.py:79`: `break` → `continue` (keep issuing sends after a send of an earlier fact raised) | **SURVIVED:** `17 passed` (same files) |

### R2-F1 — blocking. The adapter's ordering-on-failure branch is never driven

**Where:** `services/orders/src/otc_orders/infrastructure/outbox/kafka_publisher.py:74-80`, the `except Exception` around `await producer.send(...)`. Its intended guard file is `services/orders/tests/unit/test_kafka_fact_publisher.py`.

**The gap.** No test makes `producer.send` itself raise (defeat row 12, a path the population never drives). The existing tests cover the other failure routes:
- `test_a_batch_with_two_failed_records_…` fails the futures **after** they were sent;
- `test_publishing_before_start_…` fails before any send.

**Why it matters.** Under N3, a synchronous send failure on fact *k* (aiokafka raises from `send()` for, for example, a record over `max_request_size` or a full buffer at its timeout) no longer stops the batch. Facts *k+1…* of the same order are sent and may be acknowledged, while fact *k* is only republished on the next poll. That is a later fact published ahead of an earlier one, which OI8 forbids and R15 exists to prevent. The relay-level OI8 test cannot see it, because it uses a fake publisher. N2 shows the failed-id list is unasserted on the same branch. `FactPublicationError.event_ids` is read by no production code today (`grep -rn event_ids services/orders/src` finds only `publisher.py:27-29`), so N2 alone would be minor. It falls out of the same test for free.

**Required change — one unit test, no `src` change:**
- **Name:** `test_a_send_that_raises_stops_the_batch_and_names_that_fact_and_every_later_one`, in `test_kafka_fact_publisher.py`.
- **Setup:** a recording fake producer, injected the way the file's existing tests inject one. Its `send` returns a resolved future for fact 1, raises `RuntimeError("buffer full")` for fact 2, and would succeed for fact 3. Publish three facts with distinct event ids `UUID(int=1..3)`.
- **Assertions:**
  1. `FactPublicationError` is raised.
  2. `raised.value.event_ids == (UUID(int=2), UUID(int=3))`.
  3. `send` was called exactly twice, the topic's key list being `[key1, key2]`; fact 3 was **never sent**.
  4. The message carries `"send failed"`.
- **Arms (record each verbatim):**
  - (a) `break` → `continue` at `kafka_publisher.py:79`: assertion 3 must fail.
  - (b) `facts[index:]` → `facts[index + 1 :]` at `kafka_publisher.py:78`: assertion 2 must fail.
- **Paperwork:** add the name to `requirements.md` §3's **OI8** row, and update the per-file count (`test_kafka_fact_publisher.py` 7 → 8, total 1652 against a real `--collect-only`).

Nothing else is required. Everything else from round 1 stands, including the dispositions of §11.4, §11.5, §11.9 and §11.10 and N1 of round 1 (now routed to feature 15 by the leader).

### CHECKPOINTS, changes from round 1

**C4**
- [x] F1–F4 guards are now seen to fail.
- [ ] Every guard on a hand-built property seen to fail: still open, for R2-F1 (OI8's ordering clause at the adapter).

**C6**
- [ ] All tasks ticked **and true**: task 4.3 says "`publish` sends in order (guarded by 4.13)". The order of **successful** sends is guarded (4.13, plus `test_publish_sends_every_fact_…_in_order`); the stop-on-failure half is not.

All other boxes are as marked in round 1.

### For the maintainer's decision

If the maintainer prefers to close feature 14 now rather than run a third round, a defensible disposition exists:
- **Disposition:** ACCEPTED, NOT FIXED for R2-F1.
- **Evidence:** the production code is correct (`break` present; read and probed). The failure needs a synchronous `send()` error, which aiokafka raises only for an oversized record or a buffer that stays full for `request_timeout_ms`.
- **Re-open trigger:** any change to `KafkaFactPublisher.publish`, or feature 17/19 copying the adapter.

My recommendation is to **fix it**. It is one unit test of about 25 lines, it guards the clause of OI8 that the round-1 answer to Q2 depended on, and CLAUDE.md's "every branch that emits or suppresses a fact has a test that fails when the emission is deleted" covers exactly this branch.
