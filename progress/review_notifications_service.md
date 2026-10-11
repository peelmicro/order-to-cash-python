# Review — feature 23 `notifications_service` (phase 11, `sdd: false`, full group, round 1)

**Verdict: APPROVED** — **0 blocking findings**. There are 4 non-blocking findings, all FIX NOW (light: test and text changes, plus a one-parameter wiring change in N1), and 1 nit. No finding has its root cause in `specs/shared/`, so no SA-n is proposed and nothing is left for a later feature.

Reviewer: Opus. Started 2026-10-11 05:10 CEST (the brief was born at 05:09:55); verdict 05:29. All my raw outputs are in `.arm/n23-review/` (git-ignored): the harness `rarm.py`, `results.md`, one `<arm>.out` per arm, backups in `bak/<arm>/`, and `sweep_all.log`.

## What I ran, and what I did not

- **I did not re-run `quality.sh` in full.** The claim "3781 passed" is about the full suite. The leader read `.arm/n23/final.log` (ends `EXIT 0 DURATION 433s`, `3781 passed in 411.77s`) and I re-grepped it. I then checked that no file under `services/`, `tests/`, `packages/`, `specs/`, `scripts/`, `pyproject.toml` or `uv.lock` is newer than 19:30 on 2026-10-10, except `scripts/notification-template-sweep.py` (19:31:40). The run started ≈19:33:14 (19:40:27 minus 433 s), so the run tested the tree as it is now. The record's late sections (§11 to §14, written after the ≈9 h stall) describe that same code. I checked §2, §3, §10 and §13 against the sources below.
- **What I ran instead:**
  - the Notifications unit suite, its health test, the Orders parity guard and `tests/architecture`: **832 passed in 36.07s**;
  - `uv run lint-imports`: **11 kept, 0 broken**, including `otc_notifications: presentation > infrastructure > application > domain KEPT`, R14's Kafka-client confinement and the independence contract;
  - `uv run mypy`: `Success: no issues found in 650 source files`;
  - `ruff check` and `ruff format --check` on every touched path: clean;
  - `./init.sh`: exit 0, with section 5d confirming `specs/shared/` is byte-identical to #8 and #7;
  - the template sweep's `--sentinels` and `--all`;
  - **28 mutation arms** of my own (table below), 5 of them integration arms against real PostgreSQL, Kafka and Mailpit containers, with only `otcpy-n8n` running, before and after.
- **Tree restored after every arm:** `git status --short | md5sum` = `5e2d7b15…` before and after all arms, and every backup is `cmp`-equal to its file. The one file I changed is `feature_list.json` line 412 (`in_review` → `done`).

## Findings

### Non-blocking (FIX NOW, light)

**N1 — The 30 s grace-then-cancel in `_stop_tasks` has no guard that fails fast. Its stop-path half has no test at all.**
- **Where:** `services/notifications/src/otc_notifications/composition.py:197-214`.
- **The claim:** record §13 says the stuck-`start()` hang was "fixed with a grace period then cancellation, and a test". The arming table (§10) has no row for it.
- **Arm R20:** I replaced `task.cancel()` with `pass`. `test_a_consumer_that_never_joins_its_group_times_out_the_boot_and_leaves_no_task` then **hangs**: it was killed by my 180 s process-group timeout with no assertion message. The control run of the same test passes in 8.11 s. The project's pytest has no timeout plugin (`grep timeout pyproject.toml`: none), so in `quality.sh` this regression is an indefinite hang, not a failure that names the claim. The rule is Phase 10 N1 (`progress/current.md`: "a guard's failure must name its claim and arrive fast").
- **A second gap:** `start_runtime`'s `stop_grace_seconds` reaches only the boot-failure path. `NotificationsRuntime.stop()` (line 194) calls `_stop_tasks` with the module default of 30 s. So the docstring's "a send that never answers" case on shutdown cannot be tested in reasonable time, and no test exercises it.
- **Fix:**
  - bound the test's own wait with `asyncio.timeout(...)`, so the mutation fails in seconds with a message naming "cancelled after the grace period";
  - thread `stop_grace_seconds` into `NotificationsRuntime`;
  - add one stop-path test: a sender that never returns, then `runtime.stop()` returns after the grace, with the task cancelled and the ledger row forgotten;
  - arm both tests with the R20 mutation.
- **Unit:** the one `_stop_tasks` function, on its two call paths.

**N2 — `test_r18_a_redelivery_after_a_process_restart_sends_nothing_more` restarts the runtime, not the process.**
- **Arm R19a:** the duplicate decision moved into a **module-level** `set` (process-wide, so it survives a runtime rebuild in the same interpreter). The test **passed** (`1 passed in 9.84s`).
- **The mutation is still killed elsewhere. Arm R19b:** the same mutation fails `test_delivery_ledger.py::test_forget_removes_exactly_the_pair_and_the_event_can_be_recorded_again` with `assert <LedgerOutcome.DUPLICATE: 'duplicate'> is <LedgerOutcome.RECORDED: 'recorded'>`.
- **A true process restart was shown live:** record §11 used two host PIDs (`otc_notifications.log` [2689861] and `otc_notifications_2.log` [2703138]), and the inbox and ledger stayed at 8 and 8.
- **So the property holds and is guarded. The test's name and docstring over-claim it.**
- **Fix:** text only. Say "runtime restart within one process". Name R19b's test as the guard against a process-wide cache, and the live record as the real-process evidence.
- **Unit:** one test's name and docstring.

**N3 — Ported-idiom ledger (record §3): citations are missing, two departures have no rows, and §2 misstates both departures.**

CLAUDE.md (grepped on disk): "The '#7 relied on X' and '#8 supplied Y' halves are read from the checkouts, with a file and line. 'None owed' needs the same citation."

Rows whose #7 or #8 half carries **no file:line**:
- Durable ledger (#8 `ProcessedEventLedger.cs`, no line);
- Offset after the handler ("kafkajs crash-loop", "re-entry after 2 s");
- Money text;
- HTML escaping;
- Classification;
- Envelope copy;
- Consumes only. This row says "none for Notifications (Projector only)". I verified it: the only #8 hit is `tests/Projector.UnitTests/ProjectorConsumesOnlyTests.cs`. The row still needs that citation.

The two departures named in §2 have **no ledger row**:
1. **Instants.** §2 item 1 says "#7 and #8 render the raw/`O` form". #7 actually interpolates the payload's JSON string: `order-to-cash-nestjs/apps/notifications/src/infrastructure/templates/order-placed.template.ts:15` reads `` `Order date: ${payload.orderDate}` ``, and that string is already the wire form. So #9's `format_instant` text **matches #7** and departs only from #8's `{payload.OrderDate:O}` (`OrderPlacedTemplate.cs:24`).
2. **Environment names.** §2 item 4 says #9 "names its own" variables. In fact `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `NOTIFICATIONS_KAFKA_CLIENT_ID` and `NOTIFICATIONS_CONSUMER_GROUP` are #7's names (`smtp.config.ts`; `order-to-cash-nestjs/.env.example:136-137`). #8 used `NOTIFICATIONS_SMTP_*` (`order-to-cash-dotnet/.env.example:139-141`). Only `NOTIFICATIONS_SENDER` (#8's explicit `NotificationSenderKind`, `NotificationsOptions.cs:59`) and `SMTP_START_TLS` are #9's own.

`specs/shared/` decides neither choice: `domain-model.md` §6 and §7.3 say nothing about message text or configuration names (`grep -in "subject|template|recipient|email|smtp|mailpit" specs/shared/*.md specs/shared/*.yaml`: no hit about notifications). Both are therefore free choices, and the ledger is the place to record them.

I probed the ledger's **claims**, not just its existence, and every mechanism claim I probed held:
- record-first: R12, R13, R13i;
- durability: R19b;
- the envelope parsed whole (#8 id 58): R06, R11, X-P03;
- the filter: R01 to R03;
- degrade: R13i.

The defect is citation and completeness. **Fix:** text only, in `progress/impl_notifications_service.md`. **Unit:** 7 rows lacking a citation, 2 missing rows, and 2 sentences in §2.

**N4 — Routed to the leader (root config is outside the implementer's bounds): `.env.example` documents none of the service's own variables.**
- Missing: `NOTIFICATIONS_SENDER`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_EMAIL`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_START_TLS`, `NOTIFICATIONS_KAFKA_CLIENT_ID`, `NOTIFICATIONS_CONSUMER_GROUP`. `grep -n "NOTIFICATION|SMTP|MAILPIT" .env.example` returns only `POSTGRES_DB_NOTIFICATIONS` and the `MAILPIT_*` ports. #7 documents the Kafka pair, with a warning that changing the group re-emails from the new position (`.env.example:129-137`). #8 documents its SMTP triple.
- This matters because the live walkthrough needed `NOTIFICATIONS_SENDER=smtp` on the command line (§11). The default `console` silently sends nothing to Mailpit.
- **Fix:** the leader edits `.env.example`, which the leader owns under CLAUDE.md. **Unit:** 9 variables.

### Nit

**X1 — Arm R13i's failure message names nothing.** I made the degrading sender re-raise after the fallback, so the forget runs on the permanent path. The real-SMTP test does fail, but on `ValueError: too many values to unpack (expected 1, got 2)` at the destructuring `[only] = await inbox.full_messages()`. Its intended message ("the refused fact is not retried") is never reached. Asserting the count with that message would fix it (#8 id 82's class).

## Answers to the brief's nine questions

1. **Ledger and send order.**
   - **Byte-identical:** `diff` of Orders' and Notifications' `idempotent_consumer.py` prints nothing. `consumer_name.py` is identical too.
   - **Order:** `delivery_ledger.py:54-61` runs the canonical consumer with a no-op `work`, and the INSERT commits alone. `dispatch.py:48-63` renders and sends outside any transaction. A `BaseException` from the send triggers `forget` and is re-raised.
   - **Transient leaves no row:** the real 451 test asserts `ledger_rows() == []` mid-retry. I re-armed it as implementer I04 and saw it in the record.
   - **Permanent keeps the row:** the real 550 test asserts both event ids in the ledger.
   - **Forget deleted:** killed by D02 and I04. I did not re-run those two; my R12 (forget run after a **successful** send) was killed by 12 tests, first `a duplicate must not even render the message`.
   - **Forget on the permanent path:** R13 failed 2 unit tests. R13i failed the real-550 test (see X1).
   - **Crash between commit and send:** loses the email and never duplicates it, by construction (record, then send). The "lose one" side is pinned by `test_a_render_failure_after_the_record_is_not_forgotten_by_dispatch` (the row is kept, so the redelivery is a duplicate). The ordering is pinned by D03 and `test_r17_the_ledger_row_is_recorded_before_the_message_is_sent`.
   - **Residual, accepted:** a send cancelled or timed out *after* the server accepted DATA is forgotten and could be re-sent. That is the at-least-once boundary #7 and #8 share (`notification-dispatch.service.ts:12-19`, verified). The Message-ID `<eventId>@order-to-cash` gives the receiving side a handle for it.
2. **Parity guard, case 3 (two-service literal).**
   - R14: a one-character divergence in the copy's body (`"processed_eventz"`) fails case 1 (`['services/no...e the banner'] == []`).
   - R15: the copy deleted fails cases 1 and 3.
   - **Instrument premise (R16):** I made the detection lose Notifications by renaming every `AIOKafkaConsumer` in its subscriber. Case 3 fails on the literal, `{'otc_orders'} == {'otc_notific... 'otc_orders'}`. So the literal, not the detection, carries the population, as Phase 10 D2 and D3 require.
   - The implementer's N03, N04, N05 and N08 are in the record. Case 1's new population literal `{otc_orders, otc_notifications}` closes #8's n = 1 finding.
   - The detection's own premises (a `processed_events` table in `models.py`, and the text `AIOKafkaConsumer`) are now protected on both sides by the two literals.
3. **The filter.**
   - R01 deleted `order.despatched.v1` and failed `test_the_filter_is_exactly_the_seven_notified_types` (`missing ['order.despatched.v1'], extra []`) plus the consumer test, in 1.3 s.
   - R02 added `stock.reserved.v1` and failed 3 tests, among them the behavioural `test_a_well_formed_non_notified_fact_produces_no_email_and_no_ledger_row`, in 1.4 s.
   - R03 added `credit.released.v1` and failed 2 tests, in 1.3 s.
   - The fourteen-fact literal is checked against `asyncapi.yaml`'s `notificationsConsume*` operations (`test_the_literal_equals_the_spec_s_notifications_operations`), and against `FACT_MODELS` for completeness.
4. **Template sites (#8 ids 58, 59, 60).**
   - **Independent census:** my own AST walk (`/tmp/claude-1000/rv/site_census.py`) counts every `Attribute` whose receiver is a `Name` in the 7 templates, excluding `format.py`. The only receivers present are `event` (28), `payload` (85), `step` (1) and `line` (2), so no alias escapes the population. The excluded nodes are `event.payload` ×7 and `str.join` ×16. **Population: 109**, and the per-file counts equal the tool's (16, 17, 14, 14, 18, 14, 16).
   - **Sentinels:** baseline green, wrong target NOT-APPLIED, comment-only SURVIVED, known kill CAUGHT. The comment-only case is the must-not-detect one.
   - **`--all`:** `109 sites, 198 mutations: 198 caught, 0 not caught`, in 76 s.
   - **Hand mutations the tool does not generate**, all killed in about 1.2 s by named goldens:
     - R04: a nested list element pinned to `lines[0].units`;
     - R05: compensation steps in reverse order;
     - R06: `causation_id` transposed for `correlation_id` in the payment text body only;
     - R07: the payment recipient taken from `paymentReference`;
     - R08 and R09: HTML escaping without `&`, and without `'`;
     - R10: instants truncated to whole seconds (14 tests failed);
     - R21: the payment reference dropped, killed through the **real Mailpit inbox** by `test_notification_mailpit_inbox.py` (`'Payment has ...' == 'Payment PAY-...'`).
   - **Collisions:** I recomputed the leaves of the `order.cancelled.v1` fixture myself (`collisions(...) == []`). The steps' summaries are "released stock" and "released credit again", so neither contains the other. The fixtures' ids come from `uid(base+k)`, all distinct, so a transposition is visible (R06 proves it).
5. **Departures from #7 and #8.** Both are free choices: `specs/shared/` is silent on email text and configuration names (see N3). Neither changes a wire contract or a requirement. Both are departures from #8, and the instant one is *not* a departure from #7. Each needs a ledger row (N3).
6. **Lifespan.**
   - **Awaited on shutdown:** `test_the_lifespan_starts_the_fact_consumer_and_awaits_it_on_shutdown` asserts every task is done and not cancelled. Implementer arm B06.
   - **A dead task takes readiness to 503:** X-B07, re-run by me, failed with `'transport task fact-consumer is not running' in [...]` in 10.7 s.
   - **Cancellation propagates through `dispatch`:** D06 and `test_a_cancelled_send_forgets_the_row_and_cancellation_propagates`.
   - **Grace and cancel removed:** the test **hangs**, it does not fail (R20, N1).
7. **Acceptance 5 (feature 43 carry-over).**
   - **Zero handlers, two handlers, an unregistered new command, an unbuildable handler, an unbound port:** each is a named test against this service's root.
   - **R22 (my sibling-identifier arm):** validating against `otc_notifications.application.ports` instead of `otc_notifications.application` failed the zero-handler test (`the boot opened an engine before validating the registry`) and the new-command test.
   - **F-g + F-j as one pipeline in the real root (R18):** `__init_subclass__` self-registration in `handlers.py`, drained through a helper loop `_drain` → `_one` in `composition.py`. It failed `test_a_service_registers_only_from_its_composition_root_and_its_tables_match[notifications]` with `["WIRE: 2 reg...medCommand']"] == []`, in 4.7 s.
   - The implementer's B04 armed only the helper loop (F-g). R18 completes the F-g + F-j row against this root. The F-a, F-b and F-i shapes are the generic fixtures of the same test file (`test_sentinel_*`, passing in my 832).
8. **Live record (§11).**
   - `.arm/n23/live/k3_inbox.txt` holds **8 messages** (`grep -c "^To     :"` = 8) covering **all 7 notified types**: `order.placed.v1` ×2, one per order. Each has the asserted subject, recipient, Message-ID and body fields. The payment message goes to `ord-000011@…`, the order-reference fallback.
   - `k3_ledger.txt` has 8 rows.
   - `k4.txt`: before 8/8; 8 facts republished with key, value and headers copied (`republish.py` reads the original records and re-sends them); group lag 0 on every committed partition; after 8/8.
   - `k5_restart.txt`: after a real host restart (a second PID), 16 facts republished, then 8/8.
   - Both host logs end `Application shutdown complete`, with 0 `Traceback`. `docker_before` and `docker_after` show only `otcpy-n8n`.
9. **Avoided / recurred.**
   - **#8 backlog population re-enumerated:** the leader's regex over `../order-to-cash-dotnet/feature_list.json` returns exactly the 23 ids in the record's table (69 included). A broader regex (`notif|e-?mail|degrad|mailkit|inbox`) adds only id 77, an `inotify` false match that is not applicable.
   - **Verified avoided:**
     - 58: X-P03, R06, R11;
     - 59: R10, and 7 instant sites in the sweep;
     - 60: Q01, Q02 and my recomputation;
     - 73: R13, R13i;
     - 56 and 68: settings to adapter reach, N06;
     - 76: lint-imports KEPT;
     - 85: Docker-held ports via `get_exposed_port`, no free-port picking (`grep socket|free_port` empty);
     - #8's population-of-one parity guard: R15, R16;
     - #7's in-memory ledger: I05, R19b.
   - **Recurred:** 82, partly (B03's probe traceback, as the record says, plus my X1).
   - **Owned by feature 27:** 74, 75, 104 and 94.
   - **New this run:** N1 (a claimed mechanism whose guard fails only by a hang; Phase 10 N1's class) and N3 (the ledger citation class of the Phase 8 gate, ported-idiom ledger: claims held, citations missing).

## Reviewer arms (28)

The protocol is CLAUDE.md's: backups in `.arm/n23-review/bak/<arm>/`; each run in its own process group; restored by `cp` and checked with `cmp`; `__pycache__` cleared; no `-x`. The `sha256` column shows the first 16 hex digits of the file before the mutation.

| Arm | Mutation | Test(s) | First failure line | Verdict | sha256 (16) | cmp |
|---|---|---|---|---|---|---|
| R01 | filter: delete `order.despatched.v1` | filter literal + consumer | `missing ['order.despatched.v1'], extra []` | KILLED 1.3 s (2 failed) | 5f122a260ecb0e1e | True |
| R02 | filter: add `stock.reserved.v1` | literal, not-routed, behavioural | `missing [], extra ['stock.reserved.v1']` | KILLED 1.4 s (3 failed) | 5f122a260ecb0e1e | True |
| R03 | filter: add `credit.released.v1` | literal, behavioural | `missing [], extra ['credit.released.v1']` | KILLED 1.3 s (2 failed) | 5f122a260ecb0e1e | True |
| R04 | despatched: every line renders `lines[0].units` | template goldens | despatched text golden differs | KILLED 1.2 s (3 failed) | c652b4a59c0ff6aa | True |
| R05 | cancelled: steps reversed | template goldens | cancelled text golden differs | KILLED 1.2 s (2 failed) | 7a60308e73771771 | True |
| R06 | payment text: `causation_id` for `correlation_id` | template goldens | `...8566b0' == '...8547c1'` | KILLED 1.1 s (2 failed) | 9d2e6ddc3eec5c99 | True |
| R07 | payment recipient from `payment_reference` | recipient test | `not the invoice or payment reference` | KILLED 1.1 s | 9d2e6ddc3eec5c99 | True |
| R08 | escape map drops `&` | templates | `'A&amp;B…' in '…A&B…'` | KILLED 1.2 s | 77bade41478ed1cf | True |
| R09 | escape map drops `'` | templates | `…&#39;…` not found | KILLED 1.2 s | 77bade41478ed1cf | True |
| R10 | instants truncated to seconds | template goldens | text golden differs | KILLED 1.3 s (14 failed) | 77bade41478ed1cf | True |
| R11 | payment handler dedups by `correlation_id` (sibling id) | consumer tests | `'0000044f…' == '0000044d…'` | KILLED 1.4 s | 7b96a6a55e1792e1 | True |
| R12 | forget also after a successful send | dispatch + consumer | `a duplicate must not even render the message` | KILLED 1.5 s (12 failed) | 5400d3019b0e4868 | True |
| R13 | degrade re-raises after the fallback | degrading unit | `SMTPSenderRefused: (550, …)` | KILLED 1.1 s (2 failed) | 57e1f497b69991c4 | True |
| R13i | same, real Mailpit 550 | `test_a_permanent_550_…` | `ValueError: too many values to unpack` (X1) | KILLED 12.2 s | 57e1f497b69991c4 | True |
| R14 | copy body differs by one character | parity case 1 | `['services/no...e the banner'] == []` | KILLED 0.9 s | 088382845224d9b4 | True |
| R15 | copy deleted | parity cases 1, 3 | `[PosixPath(…orders…)]` population | KILLED 1.0 s (2 failed) | 088382845224d9b4 | True |
| R16 | subscriber stops naming `AIOKafkaConsumer` | parity case 3 | `{'otc_orders'} == {'otc_notific... 'otc_orders'}` | KILLED 0.9 s | de50784f4b3e0a45 | True |
| R17 | `NOTIFICATIONS = "notification"` | ledger-name test | `'notification' == 'notifications'` | KILLED 1.5 s | fb8bc9ad58115380 | True |
| R18 | F-g + F-j pipeline in the real root | registration behaviour [notifications] | `["WIRE: 2 reg...medCommand']"] == []` | KILLED 4.7 s | 7b96a6a55e1792e1 | True |
| R19a | process-wide memory set decides duplicates | restart test alone | `1 passed` | **SURVIVED** (N2) | abde49706e101a0d | True |
| R19b | same mutation | `test_forget_removes_exactly_the_pair…` | `DUPLICATE is RECORDED` | KILLED 4.1 s | abde49706e101a0d | True |
| R20 | no cancel after the grace | `test_a_consumer_that_never_joins…` | `TIMEOUT` (hung; control 8.11 s) | KILLED ONLY BY HANG 180 s (N1) | 1e7185a632bbbd76 | True |
| R21 | payment body drops the reference | real Mailpit inbox suite | `'Payment has ...' == 'Payment PAY-...'` | KILLED 17.2 s (1 of 7) | 9d2e6ddc3eec5c99 | True |
| R22 | root validates a sibling package (`application.ports`) | zero-handler, new-command boot tests | `the boot opened an engine before validating the registry` | KILLED 16.0 s (2 failed) | 1e7185a632bbbd76 | True |
| X-V03 | implementer V03 re-run | seek-back test | `assert [] == [(('otc.order...s.v1', 3), 7)]` | reproduced | de50784f4b3e0a45 | True |
| X-T02 | implementer T02 re-run | partial-credential test | `DID NOT RAISE ValidationError` | reproduced | 2a5e34dd914d75d1 | True |
| X-P03 | implementer P03 re-run | envelope-correlation test | `'(correlationId: 00000067…)' in '…00000066…'` | reproduced (7 failed) | c1fb0d290d0d13c8 | True |
| X-B07 | implementer B07 re-run | readiness-dies test | `'transport task fact-consumer is not running' in [...]` | reproduced 10.7 s | 1e7185a632bbbd76 | True |

Both mutation families were used on the payload, not only deletion:
- **delete:** R01, R12, R15, R20, R21;
- **corrupt a field on the wire path:** R06, R10, R11, X-P03;
- **substitute a sibling:** R02, R03, R07, R11, R16, R17, R22.

## Requirement and acceptance → test mapping (verified)

| Item | Test(s) | Verified by |
|---|---|---|
| Acceptance 1 (real email, 7 facts, via the Mailpit HTTP API) | `integration/test_notification_mailpit_inbox.py::test_a_real_email_for_the_notified_fact_lands_in_the_mailpit_inbox` ×7 | R21 killed through the inbox; live §11 |
| Acceptance 2 (console via the same port; degrade on permanent, #8 id 73) | `unit/test_degrading_sender.py`, `unit/test_notification_sender_binding.py`, `integration/test_notification_send_failure_real_smtp.py` | R13, R13i; implementer G01–G05, B01, B02 |
| Acceptance 3 / R17 / R18 (durable ledger; byte-identical redelivery leaves inbox and ledger unchanged) | `integration/test_notification_idempotency.py` (×7 + restart + filter-refused), `integration/test_delivery_ledger.py`, `unit/test_notification_dispatch.py` | R12, R19b; N2 (restart scope); the matrix rows R17 and R18 name these tests (column 5 only changed, counts unchanged) |
| Acceptance 4 (filter + every recipient and field; #8 ids 58, 59) | `unit/test_notified_facts.py`, `unit/test_notification_facts_consumer.py`, `unit/templates/*` | R01–R11, sweep 198/198, census 109 |
| Acceptance 5 (explicit registration, boot validation, behavioural guard, F-g + F-j) | `integration/test_notifications_host_lifespan.py` (5 boot cases), `tests/architecture/test_registration_behaviour.py[notifications]` | R18, R22 |

## CHECKPOINTS.md

**C1 — The harness is complete**
- [x] `AGENTS.md`, `CLAUDE.md`, `CHECKPOINTS.md`, `feature_list.json`, `init.sh` exist (`init.sh` passed).
- [x] `progress/current.md` and `progress/history.md` exist.
- [x] `.claude/agents/` holds all seven roles (`ls`).
- [x] Every agent declares its model: four with `model:`, three with "inherits the session model".
- [x] `./init.sh` exits 0.

**C2 — State is coherent**
- [x] At most one feature `in_progress`: zero. Before my edit: 37 done, 18 pending, 1 in_review.
- [x] Every status is in `rules.valid_status`.
- [x] Every `done` feature has passing tests (23's: 832 targeted tests here, plus the leader-verified final run).
- [x] `progress/current.md` describes the active session (feature 23, Phase 11).
- [x] No `blocked` feature.

**C3 — Architecture is respected**
- [x] No framework import in `domain` or `shared_kernel` (`lint-imports`: 11 kept). Notifications' `domain` is empty.
- [x] No cross-service database access or import (independence contract KEPT; the ledger is the service's own `otc_notifications`).
- [x] No new shared runtime code: `packages/` untouched (`git status`).
- [x] No `domain` imports `otc_cqrs`.
- [x] `shared_kernel` and `cqrs` still declare `dependencies = []` (untouched).
- [x] No float, `Decimal` or `/` in money: money text goes through `format_money`, integer `divmod` (SA-5). Notifications has no domain arithmetic.
- [x] Every interaction is Kafka-fact (consume only). No NATS, no outbox, no producer (`test_notifications_consumes_only.py`; implementer N01).
- [x] No stray debug logging or context-free TODO (`grep "print(\|TODO\|FIXME" services/notifications/src`: empty). Stdlib `logging` without structlog is repo-wide (`grep -rln structlog services/*/src packages`: empty) and owned by feature 27 ("correlationId in every log line").

**C4 — Verification is real**
- [x] `./quality.sh` passes (the final log, verified by the leader; the tree is unchanged since, by mtime). Not re-run by me.
- [x] Domain tests pure: there is no Notifications domain; the unit tests use in-memory ports.
- [x] Integration tests use real containers: PostgreSQL, Kafka, and Mailpit via `DockerContainer` with Docker-held ports. They passed with the developer stack down (only `otcpy-n8n`).
- [x] Coverage gates: 97.56 % overall (final log).
- [x] No Jest, Karma or Jasmine (`grep` of `apps/web/package.json`: empty).

**C5 — The session closed cleanly**
- [x] No suspicious untracked files. The untracked set is the feature's sources, tests, sweep script and progress files; `.arm/` is ignored.
- [x] `progress/history.md` entry with its effort record: appended by me with this verdict.
- [x] `feature_list.json` reflects the true state (23 → `done`, line 412 only; `git diff` read).
- [ ] The human has been told what was done and how to test it: the leader's step, after this verdict.
- [x] Claude did not commit (HEAD is still `8042008`).

**C6 — Spec-Driven Development:** not applicable (`sdd: false`). R17 and R18 are covered by named tests in `test-matrix.md`.

**C7 — Second-reuse fidelity**
- [x] `specs/shared/` is byte-identical to #8 and #7 (`init.sh` 5d `cmp`); only `test-matrix.md` column 5 changed.
- [x] No deviation needing an SA-n (N3's two departures are free choices `specs/shared/` does not decide).
- [x] The R17 and R18 ids are #7's: the Notifications tests prove one delivery per `(eventId, consumer)`, with the record-first ordering #7 and #8 also use.
- [n/a] n8n workflows: not touched by this feature.
- [n/a] Black-box API script: feature 31's.
- [x] Every inherited #8 finding is accounted for (question 9: 23 ids, plus 77 not applicable).
- [x] Effort record complete, with the stall stated rather than hidden (history entry).
- [n/a] README benchmark section: the wrap-up's.

## What must change

Nothing blocks approval. FIX NOW, in this phase, as a light change:
- N1: a fast, named failure for grace and cancel; `stop_grace_seconds` threaded into the runtime; one stop-path test, armed.
- N2: the restart test's wording.
- N3: ledger citations, two rows, and §2's two sentences.
- N4: the leader edits `.env.example`.
- X1, optional: the count assertion message.
