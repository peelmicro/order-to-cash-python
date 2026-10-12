# Review: backlog 216 `operator_cancel_at_placed_strands_the_stock_reservation`, round 1 (full group: saga)

**Verdict: REJECTED.** One required change, a missing guard (D1). The production change is correct and I found no behavioural defect. All three acceptance items and every Must-hold item of the brief are met and armed. However, one plausible broadening of the new precondition survives the whole saga suite and changes behaviour that `saga.md` §6 specifies. The implementer's answer to the brief's own question about an existing operator release row is prose only. Status set to `in_progress` (line 904 of `feature_list.json`, nothing else).

Scope: `fact_handler.py`, `command_payloads.py`, `test_late_stock_reservation.py`, `test_command_payloads.py`. Files changed after the brief was written (13:57), found with `find services packages specs -newer <brief>`: in Orders, exactly these four. The Gateway and contracts files in that list belong to backlog 215. No `domain/**`, `alembic/**` or `step_table.py` change.

## What I ran (my own runs, not re-reads)

| # | Probe | Result |
|---|---|---|
| 1 | The original scratch scenario `.arm/r41/test_r41_stranded_reservation.py`, unmodified, against the fixed code (`.arm/r216/r41_original_rerun.out`) | `1 failed in 38.96s`: `timed out after 30s waiting for: stock.reserved.v1 reached the cancelled order and was ignored`. The scenario's premise (the late fact is ignored) is now false. |
| 1b | The same scenario, adapted to assert the fix (`.arm/r216/test_r216_scenarios.py::test_r216_r41_scenario_now_releases`, `.arm/r216/scenarios.out`) | passed. Command rows: `[('stock.reserve','sent'), ('stock.release','sent', '{"orderReference":"ORD-000101","reason":"order_cancelled"}', note None)]`. Release requests: exactly `[{'orderReference':'ORD-000101','reason':'order_cancelled'}]`. Ignored: `stock.released.v1` at `cancelled`. Outbox: `['order.cancelled.v1']`. `credit.hold` requests: `[]`. The reservation is now released. |
| 4 | Operator cancel from `stock_reserved` (note `$keep: café €`, release held), then `stock.reserved.v1` (a) while still `stock_reserved` and (b) after the cancel completed (`test_r216_cancel_from_stock_reserved_then_reserved_again`) | passed. (a) recorded `precondition_unmet`, observed `stock_reserved`; the row's id, payload and note are unchanged. (b) the late branch takes `ALREADY_OWED`: the same row id, payload and `operator_note` `$keep: café €`, release requests 2 → 2, exactly one `order.cancelled.v1` whose `note` is `$keep: café €`. **The interaction is correct and the note is preserved.** No committed test exercises it, though (D1 part b). |
| 7 | `./quality.sh` once at the end (developer stack down: only `otcpy-n8n` running; nobody else testing) | exit 0, "all gates passed", **4 768 passed in 565.57 s** (0.119 s / test), real 9 m 46 s, coverage TOTAL 98 %, import-linter `13 kept, 0 broken`. The previous full run (backlog 215) gave 4 762, and 4 768 − 4 762 = 6, the six new integration cases (the unit file is net 0: one case added, one parametrisation removed). This reconciles with the implementer's 4 768. |

I did not re-run the full suite beyond that one `quality.sh`. Each arm below ran only its named tests.

## My arming table (`.arm/r216/arm.py`; backups `.arm/r216/<arm>.bak`; restored by copy, `cmp` identical every time; `__pycache__` cleared; each run in its own process group, killed whole on timeout; pristine hashes re-checked with `sha256sum -c .arm/r216/pristine.sha256`: both OK)

`fact_handler.py` sha256 `da2914d08446712e2b00fd5276aee91a89a1f5a2ba69b1b3028cc07610e01e48`; `command_payloads.py` `784cf006dc17986f1ebab21bc8e38defd0d5c707e24fbfcaaa6cc63576527bd1`.

| Arm | Mutation | Family | Tests run | Result (first message) |
|---|---|---|---|---|
| R1 | Late path is non-idempotent: delete the order's `stock.release` row, then enqueue (each redelivery writes a fresh row) | delete idempotency (push 2, **direct**) | redelivery test | FAILED: `assert [UUID('9e9e11…')] == [UUID('94f0b6…')]`, a second row id |
| R2 | Late path re-issue re-sends: after enqueue, reset the row to `pending` | delete idempotency (push 2, the request half) | redelivery test | FAILED: `assert 2 == 1` (`len(requests_for(...))`, a second `fulfillment.stock.release` request) |
| R3 | Precondition broadened to also take `credit_rejected` | broaden | decoy (both params) | `[CREDIT_REJECTED]` FAILED: `timed out ... stock.reserved.v1 is recorded as a precondition_unmet fact`; `[STOCK_REJECTED]` passed |
| R4 | Precondition broadened to also take `stock_rejected` | broaden | decoy (both params) | `[STOCK_REJECTED]` FAILED (same message); `[CREDIT_REJECTED]` passed. Each decoy parameter is independently armed (the implementer's A5 ran with `-x` and saw only the first). |
| R5 | Precondition inverted | invert | whole file | 6 failed / 6, including the e2e with `timed out after 30s waiting for: the late reservation owes stock.release` (the pre-fix symptom) and the `placed` test (`the reservation moves the order to stock_reserved`) |
| R6a | Broadened to any `stock_reserved` | broaden | `test_saga_preconditions.py` + late file | FAILED: `test_r25_..._unmet...[stock.reserved.v1]`: `one precondition_unmet row for stock.reserved.v1` |
| **R6b** | Broadened to `stock_reserved` **with an accepted operator cancel** (the late-approval predicate's shape) | broaden | late-reservation, operator-cancel-flow, late-credit-approval, preconditions files | **SURVIVED: `42 passed in 51.86s`** (D1) |
| R6b-probe | R6b against my scratch probe `.arm/r216/test_r216_r6b_probe.py` | — | probe | green on real code (`1 passed`); armed FAILED: `stock.reserved.v1 at stock_reserved (accepted cancel) recorded precondition_unmet`. The mutation is not equivalent: it changes observable, specified behaviour. |
| R7 | `"note":"n"` appended to the late release's wire payload | corrupt (note) | payload test | FAILED: `the wire payload declares no note, so none is sent`, `Left contains 1 more item: {'note': 'n'}` |
| R8 | `operator_note='n'` stored on the late row | corrupt (note) | payload test | FAILED: `assert 'n' is None` |
| R9 | `build_operator_stock_release_payload` reason → `credit_rejected` | corrupt | payload test + 2 unit | all 3 FAILED, e.g. `{'reason': 'credit_rejected'} != {'reason': 'order_cancelled'}` |
| R10 | Builder reference → the next order's (`ORD-000102`, a real sibling in the test) | sibling substitution | payload test + 2 unit | all 3 FAILED: `{'orderReference': 'ORD-000102'} != {'orderReference': 'ORD-000101'}`; unit `'ORD-000008' == 'ORD-000007'` |
| R11 | Late payload reference taken from the fact | sibling (unit only) | `test_stock_release_owed_by_a_late_reservation_...` | **SURVIVED the unit test** (`1 passed`): the order and the fact share `ORD-000007` (N2). The integration payload test does catch it (the implementer's A3). |
| R12 | Feature 41 C4: late approval for any cancelled reason | (push 6) | late-credit decoy | FAILED both params: `credit.approved.v1 is recorded as a precondition_unmet fact` |
| R13 | Feature 41: late-approval `credit.release` emission deleted | (push 6) | `..._after_the_operator_cancellation_completed_...` | FAILED: `the credit.release row reaches sent` |

**Push 2 (A7 caveat), decided.** The redelivery test does see a second row (R1) and a second request (R2) **directly**. The implementer's A7 failed only because its injected `stock.release.dup` row poisoned the transaction. A7 is superseded by R1 and R2. The byte-identical redelivery (same event id) is absorbed by `FactConsumption` dedup before the branch runs. The new-event-id case is the one that exercises the ledger's `ON CONFLICT DO NOTHING`, and the test sends both.

## Defects

**D1 (required change). Two claims about the branch's boundary are unguarded, and one of them survives a plausible mutation.**

- **(a) The `stock_reserved` side.** The implementer's §2 decision rests on the claim that *"the reservation's only shape is `cancelled` / `operator_cancelled`"* (`fact_handler.py:151-160`, `_is_late_reservation`). That is the reason for the sibling branch: unlike the late-approval predicate (`fact_handler.py:140-149`), it does not take `stock_reserved` with an accepted operator cancel. `saga.md` §6's `stock.reserved.v1` row says that at `stock_reserved or later` the fact is *ignored, recorded as out-of-order* (R25). Mutation R6b gives the new branch exactly the late-approval shape, which is the generalisation the brief invited the implementer to weigh. It passes all 42 tests of the four relevant files. Its effect: the fact is no longer recorded in `saga_ignored_facts`; it is processed, and the operator's row is re-signalled (`ALREADY_OWED`). My probe shows the effect is observable, and a future refactor that unifies the two late branches would ship it unseen. A countable claim needs a guard that has been seen to fail (`CLAUDE.md`, "A countable claim … is a guard").
- **(b) The existing operator release row.** The brief asked: *"Note the existing case where a `stock.release` row already exists for the order (an operator cancel from `stock_reserved` owes one with the note): what does the new branch do then, and is that right?"* The record answers in prose (§2: *"`ALREADY_OWED`, the row is re-signalled and nothing new is written … Right"*). No committed test drives it. The redelivery test's existing row is the late branch's own, with no note. My scenario (4b) shows the claim is true today. It is still a claim about a row and a note that no guard covers.

**Must change (D1):** add integration test(s) to `services/orders/tests/integration/saga/test_late_stock_reservation.py` covering:

1. An order at `stock_reserved` with an accepted operator cancel (via `orders.cancel`, `stock.release` stand-in held). A `stock.reserved.v1` with a new event id is recorded `precondition_unmet`, observed `stock_reserved`. The operator's row is unchanged (id, payload, `operator_note`), there is no extra request, and the order stays `stock_reserved`. Arm it with R6b (it must fail and name the claim). My `.arm/r216/test_r216_r6b_probe.py` is a working draft.
2. The same order after the cancellation completes (stand-in released, `stock.released.v1` cancels it). A `stock.reserved.v1` with a new event id adds no row and sends no request. The operator's row keeps its `operator_note`, and `order.cancelled.v1` carries the note exactly once. Arm it by blanking `operator_note` or rewriting the payload on the `ALREADY_OWED` path (it must fail). My `test_r216_cancel_from_stock_reserved_then_reserved_again` is a working draft.

Re-review will re-run R6b, the new arm(s), and R1/R2, not the whole table.

## Non-blocking findings (fix in the same round; each is one line)

- **N2. The unit fixture satisfies the reference equality by accident.** `services/orders/tests/unit/saga/test_command_payloads.py`, `test_stock_release_owed_by_a_late_reservation_is_the_operators_order_cancelled_release`: the order and `make_fact` both use `ORD-000007` (unit `conftest.py:69`). So "the aggregate's reference, not the fact's" (SO12) cannot fail there (R11 survived). The integration payload test guards it. Disposition: fix (give the fact a distinct reference) or delete the reference assertion so it does not claim what it cannot see. The older `credit_rejected` sibling test has the same shape (pre-existing, not 216's).
- **N3. The baseline assertion is weaker than its comment.** `test_late_stock_reservation.py`, redelivery test: `assert (rows_before and requests_before) == 1  # the baseline is one, not zero` asserts *rows non-empty and requests == 1*, not *one row*. Write `assert len(rows_before) == 1 and requests_before == 1`.
- **N4. No baseline `quality.sh` before the change** (record §7, disclosed). Mitigated: 4 762 (215's run) + 6 = 4 768, which my run reproduces. Disposition: accepted as a process note.
- **N5. The failing-first run has no output file** (record §4 quotes it). Mitigated by R5: the inverted precondition reproduces the pre-fix path on the e2e test with the quoted message. Disposition: accepted.

## Must-hold list and acceptance items → tests (verified by arming, not by name)

| Item | Test | Armed by |
|---|---|---|
| Acc. 1 (SA-8 ruled, applied, recorded) | `cmp` of every `specs/shared/*` except `test-matrix.md` against #7 and #8: all identical. `SA-8` in #9 README:40, #8 README:48, all three `progress/history.md`. #7's README has no `SA-n` registry at all (not even `SA-1` – `SA-5`), so there is no row to add. | n/a (leader's spec half) |
| Acc. 2: e2e, one `stock.release` (`order_cancelled`), no transition, no `credit.hold`, `stock.released.v1` its own timeline fact (ignored at `cancelled`) | `test_an_operator_cancel_at_placed_then_the_late_reservation_issues_stock_release_and_nothing_else` | R5 (pre-fix message), A6 (implementer: `credit.hold`), probe 1b |
| Acc. 3: delete the emission | `test_the_late_reservation_release_carries_the_aggregates_reference_the_reason_and_no_note` | A1 (implementer), R5 |
| Acc. 3: corrupt a request field (reason, reference, note) | same | R7, R8, R9, R10, A2, A3 |
| Acc. 3: decoys `stock_rejected` / `credit_rejected` | `test_a_late_reservation_for_a_cancellation_the_saga_decided_is_ignored_and_releases_nothing[both]` | R3, R4 (each parameter separately), A5 |
| Acc. 3: redelivery adds no second row or request, counted against the baseline | `test_a_redelivered_late_reservation_adds_no_second_release_row_and_sends_no_second_request` | R1, R2 (direct) |
| Precondition, `placed` side | `test_a_reservation_for_a_placed_order_still_advances_it_and_asks_for_the_credit_hold` | R5 |
| Precondition, `stock_reserved` + accepted-cancel side | **none** | **R6b survived (D1)** |
| Feature 41's late-approval arms still hold | `test_late_credit_approval.py` | R12, R13 |

No `R<n>` is added by SA-8. R25's text ("SHALL issue no command") was weighed against SA-8 at the gate (`progress/proposal_sa8.md:50`, following SA-4's precedent), so the matrix needs no change. The record's §6 is correct.

## Ledger (record §3), claims checked

- "#7 / #8: none owed". I read the cited lines. #8 `CancelOrderCommandHandler.cs:157-169` cancels at `placed` with `compensationSteps: []`, and `SagaStepTable.cs:181-186` maps `stock.reserved.v1` only as an `Advance` from `Placed`. #7 `cancel-order.handler.ts:118-131` and `saga-steps.ts:173-178` do the same. Confirmed.
- "One owed command per (order, command): `ON CONFLICT DO NOTHING` (`command_queue.py:58`)": checked directly by R1 and R2. The fast path claims only `pending` / `parked` rows (`command_ledger.py:42`), so a re-signal of a `sent` row sends nothing.
- Python questions: no `/`, no JSON hand-built (the payload goes through `to_wire_json`), no new tasks. Confirmed by reading the two production diffs.

## CHECKPOINTS walked (applicable boxes)

- C2 [x] one feature `in_progress` (216, after this verdict); [x] statuses valid (`json.load` OK).
- C3 [x] `lint-imports` 13 kept / 0 broken (my `quality.sh`); [x] no domain change, no cross-service access; [x] no money arithmetic touched; [x] Kafka fact in, NATS RPC out (the `fulfillment.stock.release` request), per the matrix; [x] no stray debug, no TODO in the diff.
- C4 [x] `quality.sh` exit 0; [x] integration tests on testcontainers with the developer stack down; [x] coverage 98 % total; [x] no Jest.
- C5 [ ] history entry: not written (rejected); [x] `feature_list.json` reflects the state; [x] no commit.
- C6 n/a (`sdd: false`).
- C7 [x] `specs/shared/` byte-identical to #7 and #8; [x] SA-8 recorded (see Acc. 1); [x] inherited #8 id 104 avoided (runs with the developer stack down); [ ] effort record: the leader's, after approval.

## Effort so far (for the eventual history entry)

Brief and premise written 13:57. Implementation from ≈13:58 to the record at 14:34 (≈36 min; `progress/current.md` says "dispatched ≈14:20", which the file times contradict: the test file is stamped 14:18). Review round 1 from ≈14:36 to ≈15:00 (≈24 min, including one `quality.sh` of 9 m 46 s).

## Artifacts

`.arm/r216/`: `arm.py`, `arms.log`, `<arm>.bak` / `<arm>.out`, `pristine.sha256`, `test_r216_scenarios.py` + `scenarios.out`, `test_r216_r6b_probe.py` + `R6b-probe.out`, `r41_original_rerun.out`, `quality.log` / `quality.exit` / `q.start` / `q.end`.

## Round 2 (re-review, test-only; scope: D1 (a), D1 (b), N-a = N2, N-b = N3 only)

**Verdict: APPROVED.** D1 (a) and (b), N2 and N3 are each closed by a committed test, and I saw each test fail under my own mutation. No source file changed since round 1. `sha256sum -c .arm/r216/pristine.sha256` gives `fact_handler.py: OK` and `command_payloads.py: OK` both before and after my arms (`da2914d0…1e48`, `784cf006…27bd1`). 216 is set to `done` (`feature_list.json` line 904 only).

**What I ran.** I did not run `quality.sh` (the implementer's round 2 gave exit 0, 4 770 passed = 4 768 + 2 new, by their account). I ran only the two targeted files, with the developer stack down (only `otcpy-n8n` running) and no other test run alive. On pristine code: `test_late_stock_reservation.py` + `test_command_payloads.py` gave `28 passed in 22.88s` before the arms and `28 passed in 24.73s` after them, with `__pycache__` cleared (`.arm/r216r2/baseline.out`, `post.out`).

**Arms** (`.arm/r216r2/arm.py`; backup `.arm/r216r2/<arm>.bak` with its sha256; each run in its own process group, killed whole on timeout; restored by copy, `cmp` identical every time; `__pycache__` cleared; output `.arm/r216r2/<arm>.out`, summary `arms.log`)

| Arm | Mutation | Family | Test run | Result (first message, verbatim) |
|---|---|---|---|---|
| R6b (round 1's survivor, re-run unchanged) | late branch also takes `stock_reserved` with an accepted operator cancel | broaden | whole `test_late_stock_reservation.py` | **now FAILS**: `1 failed, 7 passed`. The failure is `test_a_reservation_at_stock_reserved_with_an_accepted_operator_cancel_is_still_ignored_as_out_of_order`: `timed out after 20s waiting for: stock.reserved.v1 is recorded as a precondition_unmet fact` |
| D1b-own-row | the late path deletes the order's `stock.release` row, then enqueues its own | delete idempotency / substitute the row | D1b test | FAILED: `At index 0 diff: (UUID('17bd31c8…'), 'stock.release', '{"orderReference":"ORD-000101","reason":"order_cancelled"}', None) != (UUID('ed4b146d…'), …, '$keep: café €')` |
| D1b-clear-note | after enqueue, the late path sets `operator_note = NULL` | corrupt (note) | D1b test | FAILED: the same row id `f51bd8e1…`, `None != '$keep: café €'` |
| D1b-rewrite-payload | after enqueue, the late path rewrites the row's payload reason to `credit_rejected` | corrupt (payload) | D1b test | FAILED: `'{"orderReference":"ORD-000101","reason":"credit_rejected"}' … != '…"reason":"order_cancelled"}'` |
| D1b-resend | after enqueue, the late path resets the operator's `sent` row to `pending` | delete idempotency (request half) | D1b test | FAILED: `assert 2 == 1` (`len(requests_for(...))`, a second `fulfillment.stock.release`) |
| N-a (round 1's R11, re-run) | payload reference taken from the fact | sibling substitution | the unit test | **now FAILS**: `AssertionError: assert 'ORD-000099' == 'ORD-000007'` |
| N-b | the late path also enqueues a `credit.release` row (two baseline rows) | add a row (under round 1's compound assert it passed) | redelivery test | FAILED: `AssertionError: the baseline is one row, not zero` / `assert 2 == 1` |

**Reading the tests (`test_late_stock_reservation.py:231-330`).**
- D1a drives the real `orders.cancel` responder from `stock_reserved` with the release stand-in held. It asserts the `saga_ignored_facts` row for that `event_id`: `observed_status` `stock_reserved`, `expected_status` `placed`. It also asserts the unchanged row-id set, the operator's row `(id, payload, operator_note)`, and that the status is still `stock_reserved`.
- D1a omits the "no extra request" count that round 1 asked for. The implementer's reason holds: the held stand-in is retried by the dispatcher, so the request count moves without any fact. I accept this. The ignored-fact record is the specified behaviour (`saga.md` §6), and R6b fails on it.
- D1b completes the cancellation through the real `stock.released.v1`, then publishes a `stock.reserved.v1` with a new event id. It asserts every row's `(id, command, payload, operator_note)`, the request count, and exactly one `order.cancelled.v1` whose `note` is the note.
- N2 (`test_command_payloads.py:126-144`) now uses a fact reference `ORD-000099`, distinct from the order's `ORD-000007`, and asserts the distinctness. N3 (`:149-150`) is two separate asserts.

**Non-blocking.** D1b's `assert requests_before >= 1` is a weak baseline, but the arm that matters for it (D1b-resend) fails on the equality after the fact. No change is required.

**CHECKPOINTS (delta from round 1):**
- C5: [x] `feature_list.json` reflects the state (216 `done`, line 904); [x] history entry with effort record appended (`progress/history.md`, backlog 216); [x] no commit.
- C7: [x] effort record written.

**Effort (round 2).** Brief written 15:00. Implementer 15:00 to 15:14 (record and `quality.log` stamped 15:14). Review round 2 15:15 to ≈15:21. **Backlog 216 total, from the brief to the approval: ≈13:57 → ≈15:21, ≈84 min wall-clock, in 4 agent sessions (2 implementer, 2 reviewer).**
