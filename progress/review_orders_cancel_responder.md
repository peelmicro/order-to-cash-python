# Review — feature 41 `orders_cancel_responder` (phase 13, `sdd: false`, full group: saga), round 1

**Verdict: APPROVED.** No blocking finding. Fifteen reviewer mutations across both mutation families (delete, corrupt a field on the wire) and sibling substitution: all fifteen failed the named tests, and every file was restored (`cmp` identical, sha256 matched). The stranded reservation is **reachable** (proved below with a scratch test against the real Orders host). It is spec-rooted and shared with #7 and #8. Feature 41 did not make it reachable. It is routed below as `SA-8` plus backlog `216`, not left as a sentence.

Feature 41 is set to `done` in `feature_list.json` (that line only, as the brief says). The `progress/history.md` effort entry is the leader's, as it was for features 25 and 40. C5's effort-record box stays open until the leader writes it.

## What I ran (and what I did not re-run)

- I read: `progress/impl_orders_cancel_responder.md` (200 lines), its brief, the premise check, every new or changed source file under `services/orders/src/otc_orders/**`, the migration `0002`, and the new tests.
- I ran the targeted tests through my own arms: 15 arms, the output of each in `.arm/r41/<arm>.out`, plus `.arm/r41/arms.jsonl`.
- I ran two scratch tests in `.arm/r41/` (not committed). `.arm/r41/conftest.py` loads the Orders integration and saga conftests by path.
- I ran `./init.sh` (exit 0), plus `cmp` of `specs/shared/*` (except `test-matrix.md`) against #7 and #8: all 6 files are identical.
- I ran `./quality.sh` once at the end, with the developer stack down (`docker ps`: `otcpy-n8n` only, before and after):
  - exit **0**;
  - **4 675 passed in 549.24 s**, the same count as the implementer's 4 675 (543.68 s);
  - coverage 97.53 % overall and 98 % on the domain layer;
  - import-linter "13 kept, 0 broken";
  - `quality.sh: all gates passed`.
- I did **not** re-run the implementer's 50 arms. I re-ran the ones the brief singled out in my own form: C1 (lock removed from the cancel) and C3 (D1, with both arms transposed in one mutation).
- I did **not** do a live walkthrough. The implementer's §9 is the live record, and the live `otc_orders` at `0002` is registered in `progress/current.md:27`.

## Blocking findings

None.

## Non-blocking findings, each with a disposition

**N1 — The stranded reservation (spec-rooted, shared with #7 and #8): REACHABLE. Route it as `SA-8` plus backlog `216`. Do not narrate it.**

Scratch test: `.arm/r41/test_r41_stranded_reservation.py`, output in `.arm/r41/stranded.out`, `1 passed in 12.48s`. It ran against the real Orders host, real NATS, Kafka and PostgreSQL, with stand-in Fulfillment.

Steps:

1. Order `ORD-000101` is planted at `placed`, and `order.placed.v1` is published.
2. The saga owes `stock.reserve` (row `pending`). The held Fulfillment is silent, so the row is sent and times out.
3. The operator cancels through `orders.cancel`. The reply is `{"status":"cancelled","cancellationReason":"operator_cancelled","compensationPlanned":[]}`.
4. Fulfillment comes back. **The same `stock.reserve` row is dispatched again after the cancel** (requests: 1 before the cancel, 2 in total), and the row ends `sent`.
5. Fulfillment reserves and emits `stock.reserved.v1`. Orders records it in `saga_ignored_facts` as `precondition_unmet` (`observed_status cancelled`, `expected placed`).

At the end of the test:

- the only command row is `('stock.reserve', 'sent')`;
- `stock.release` requests: `[]`;
- outbox: `['order.cancelled.v1']`.

Why it happens: the dispatcher never reads the order's status (`infrastructure/saga/command_dispatcher.py:20`: "The order is never loaded or written here").

**The residue in Fulfillment** (read from its code; not measured against the real Fulfillment):

- `reserve_order` (`services/fulfillment/src/otc_fulfillment/domain/order_stock_reservation.py:96`, called at `application/stock_reservation.py:80`) leaves the order's reservations `reserved`. `reserved_units` rises by the ordered units: 3 × `SKU-A` and 2 × `SKU-B` in the scratch order.
- Only two paths ever undo that:
  - `release_order` (`order_stock_reservation.py:174`, reached only from `stock.release` at `application/stock_reservation.py:129`);
  - `StockItem.consume` (`domain/stock_item.py:183`, reached only from `despatch.create` at `domain/order_despatch.py:58`).
- Neither is ever requested for an order that is cancelled.
- There is no expiry (`grep -rn "expir\|ttl"` over Fulfillment's `domain` and `application`: no hits).
- So the units stay reserved for good, and `available_units` falls by the same amount.

**#7 and #8 behave the same in this window:**

- #8:
  - At `placed`, `CancelOrderCommandHandler.cs:157-169` (the `default:` branch) calls `order.Cancel(...)` and saves. It does not touch the pending `stock.reserve`.
  - `SagaStepTable.cs:181-186` gives `stock.reserved.v1` a single variant (precondition `Placed`), so it is ignored at `cancelled`.
- #7:
  - `apps/orders/src/application/cancel-order.handler.ts:118-131` cancels in place in the same way.
  - `apps/orders/src/application/saga-steps.ts:173-178` gives `stock.reserved.v1` precondition `placed` only.
- Neither build withdraws the row, and neither releases on a late `stock.reserved.v1`.

Feature 41's `placed` branch (`cancel_order.py:123-140`) is a faithful port, so **this does not count against feature 41**.

**Root cause** (`specs/shared/saga.md` §4.3, generalisation table row *"Operator cancels while `placed` | (nothing) | (nothing)"*): the "nothing acquired" premise is false once `order.placed.v1` has been processed. §4.3 already has the exact counterpart for credit (*"A credit approval that arrives after the cancellation"*) and none for stock.

**Routing** (the leader files both; I do not write `feature_list.json` beyond feature 41's status line):

- **`SA-8` proposal.** `SA-7` is taken by `progress/proposal_sa7.md`, backlog 213. In `saga.md` §4.3, after the late-credit paragraph, add *"A stock reservation that arrives after the cancellation"*. Its content: a `stock.reserved.v1` for an order already `cancelled` with reason `operator_cancelled` issues `stock.release` (reason `order_cancelled`) and nothing else (no transition, no `credit.hold`). The release reaches the timeline as its own `stock.released.v1`. Also amend §5's `stock.reserved.v1` row to match. Withdrawing the pending row at cancel time alone is not enough, because a `sent` row is already in flight (step 4 above).
- **Backlog `216`** (`operator_cancel_at_placed_strands_the_stock_reservation`), phase 13 (findings are fixed in the phase that detects them):
  - Attach it to the Orders saga code it changes: `application/saga/fact_handler.py` (a branch mirroring `_is_late_approval`) and `step_table.py`.
  - Acceptance:
    - this scratch scenario, committed as a test that fails today;
    - the two mutation families on the new emission;
    - a decoy proving that a `stock_rejected` / `credit_rejected` cancellation does not release.
  - Whether #7 and #8 get the code half is the maintainer's call at the `SA-8` gate. The spec half lands in all three repositories byte-identically.

**N2 — "No status filter" in `find_accepted_operator_cancel` is right for every reachable case. ACCEPTED, NOT FIXED, with evidence.**

The brief's worry was this: a `rejected` operator release (the despatch won) would still mark the cancel accepted, so a later `credit.approved.v1` would release the hold of a shipping order.

- **Traced.** The query has two call sites, `fact_handler.py:109` (the note lookup on an `operator_cancelled` `Cancel`) and `fact_handler.py:136` (`_is_late_approval`). The second is consulted **only at `stock_reserved`**. A despatch exists only after `credit.approved.v1` has confirmed the order, so at the moment the despatch can win the order is `confirmed` or `despatched`, and `_is_late_approval` returns `False` for both.
- **Probed.** Scratch test `.arm/r41/test_r41_rejected_release_no_status_filter.py`, output in `.arm/r41/rejected.out`, `3 passed`. A rejected operator `stock.release` row is planted and a distinct `credit.approved.v1` is published:
  - at `confirmed`: the approval is ignored (`precondition_unmet`), and no `credit.release` is issued;
  - at `despatched`: the same;
  - at `stock_reserved`: `credit.release` is issued and the order stays `stock_reserved`.
- **The residual.** That last case would leave an order parked at `stock_reserved` with its hold released. It is not reachable with the real Fulfillment, which answers a `reserved` reservation's release with success (F5, `order_stock_reservation.py:90`). It refuses only a `consumed` one (F4), and consumption needs a despatch, which needs `confirmed`.
- **Arming.** B5, a status filter added, fails `test_a_row_in_any_status_still_means_the_cancel_was_requested[rejected]`, so the decision is pinned.
- **Re-open trigger:** Fulfillment gains a terminal refusal of a `reserved` reservation's release.

**N3 — The record's §10 understated N1.** It says *"I did not reproduce it"*; it is now reproduced (N1). This is a record correction, not a code finding. Disposition: superseded by this review.

**N4 — The implementer's arm runner weakened a warning gate for its arms.** `.arm/n41/arm.py` passes `-W ignore::pytest.PytestUnraisableExceptionWarning`, which turns off a gate `pyproject.toml` sets to `error`. My arms ran without it, and all 15 failed on assertions, never on warnings. Disposition: accepted. It concerns the arming method only; no committed file is affected.

## My arming table (`.arm/r41/arm.py`; backups `.arm/r41/<arm>.bak`; restored by `cp`, checked with `filecmp` plus sha256; `__pycache__` cleared; process group killed on timeout)

| Arm | File (sha256 prefix) | Mutation | Family | Failed (first message) |
|---|---|---|---|---|
| B1 | `command_queue.py` (`d2755c016eb7`) | command token → `stock.reserve` | sibling | 7 tests, e.g. `assert None == AcceptedOperatorCancel(note="the target's note")` |
| B2 | same | command token → `despatch.create` | sibling | 7 tests, same message |
| B3 | same | `json_extract_path_text` reads `operator_note` instead of `payload` | sibling column | 7 tests, `AssertionError: an accepted cancel with no note is still an accepted cancel` |
| B4 | same | `order_id ==` → `!=` (another order) | sibling | 9 tests, incl. `AssertionError: decoy (another order) was taken for an accepted cancel` |
| B5 | same | add `status != 'rejected'` | corrupt narrowing | `test_a_row_in_any_status_still_means_the_cancel_was_requested[rejected]`: `AssertionError: rejected` |
| C1 | `cancel_order.py` (`ff9fb9e3…`) | `get_by_id_for_update` → `get_by_id` | delete (#8 id 62) | both race tests: `timed out after 20s waiting for: the cancel is waiting on the order row lock (SO17)` |
| C2 | same | `credit.release` ALSO enqueued at cancel time (credit_approved/confirmed) | wrong order | SA-4 test ×2: `AssertionError: credit.release is owed by the stock.released.v1 fact, not issued at cancel time` |
| C3 | `command_payloads.py` (`c6dc8f24…`) | BOTH release reasons transposed (#8 D1) | corrupt wire field | 4 tests: the stock_reserved and SA-4 ×2 operator paths (`{'reason': 'credit_rejected'} != {'reason': 'order_cancelled'}`) and `test_r27_issues_stock_release_…` on the credit-rejected path |
| C4 | `fact_handler.py` (`3e80f714…`) | late approval for ANY cancelled reason | inverted precondition | `test_a_credit_approval_for_a_cancellation_the_saga_decided_…[CREDIT_REJECTED / STOCK_REJECTED]`: `timed out … credit.approved.v1 is recorded as a precondition_unmet fact` |
| C5 | `cancel_order.py` | stored note `lstrip('$')` (PR47) | corrupt supplied field | `test_sa4_from_stock_reserved_…`: `'set: the pal…' == '$set: the pa…'` |
| C6 | Gateway `nats_rpc_client.py` | `NoRespondersError` → `RpcTimeoutError` | sibling (item 6) | `test_a_gateway_route_whose_subject_nobody_serves_…`: `assert (503, 'UPSTREAM_TIMEOUT') == (503, 'UPSTREAM_UNAVAILABLE')` |
| C7 | `orders_cancel.py` | reply always carries `cancellationReason` | corrupt wire field (#8 D2) | 3 tests (unit ×2, integration key-set): `Left contains 1 more item: {'cancellationReason': 'operator_cancelled'}` |
| C8 | `fact_command_handlers.py` | sibling `STOCK_RESERVE` dispatch event deleted | delete (brief point 9) | 2 unit tests: `KeyError: <SagaCommandKind.STOCK_RESERVE…>` |
| C10 | `step_table.py` (`92e2244a…`) | `stock.released.v1` at `confirmed` owes nothing (stock only) | wrong order | SA-4 [CONFIRMED]: `timed out after 20s waiting for: an order.cancelled.v1 outbox row exists` |
| C11 | `command_payloads.py` | `credit.release` retailer and company codes swapped | corrupt wire field | 3 unit tests: `'…"RET-01"}' == '…"CMP-01"}'` |

Brief point 9 (siblings hidden by the sweeper): C8 shows that the sibling dispatch-event entries are guarded by the parametrised unit test and the literal set test (`test_fact_command_handlers.py:161-205`). The composition registrations of all seven events are guarded by `test_order_sagas.py:61-86`, the implementer's R5/R6 plus the pre-existing rows. The implementer's fix for R10 (R10b unit test plus the sweeper-off integration tests R10c, H5b, R5b, R6b) is the right guard: it removes the sweeper from the path the claim is about.

## The six acceptance items → tests (verified)

| # | Item | Test(s) | Armed |
|---|---|---|---|
| 1 | 202 through the Gateway | `test_cancel_through_gateway.py::test_post_cancel_is_202_for_each_cancellable_status_…` (×4; real Gateway, real Orders host, real NATS) | impl R2, R8 |
| 2 | terminal → domain error, not 503 | `…::test_a_terminal_order_is_a_409_order_not_cancellable_problem_not_a_503` (×5), `…::test_an_unknown_order_is_a_404` | impl R2, R9 |
| 3 | SA-4 ordering; late approval releases and advances nothing | `test_operator_cancel_flow.py::test_sa4_from_credit_approved_and_confirmed_…` (shared arrival list across the six stand-ins), `…despatch_wins…` ×2, `test_late_credit_approval.py` (8) | C2, C3, C4, C10, C11; impl W1, F1–F8 |
| 4 | note on the timeline | `test_cancel_note_end_to_end.py` ×3 (Gateway → Orders → Kafka → Projector → `GET /orders/{id}`), plus flow tests at all four statuses | C5; impl Q7, H3, H4, F5, R8, R12, plugin arms |
| 5 | query on real PostgreSQL with decoys; race in both outcomes | `test_accepted_operator_cancel_query.py` (14), `test_operator_cancel_race.py` (2, held lock, `pg_stat_activity`) | B1–B5, C1; impl Q1–Q7, H1b, H11 |
| 6 | the retired Gateway 503 test is replaced | `test_cancel_through_gateway.py::test_a_gateway_route_whose_subject_nobody_serves_answers_503_upstream_unavailable_at_once` (real Gateway lifespan, real NATS, no Orders host, < 3 s) | C6; impl `arm_gateway_unavailable_mapping_deleted` |

**Migration `0002`:**

- It is additive: one nullable `text` column.
- It is reversible: `downgrade` drops the column, and `test_upgrade_downgrade_reupgrade_lifecycle` covers it at head `0002`.
- It does not collide with feature 27: 27's planned columns are `triggering_event_envelope`, `triggering_event_topic` and `dead_lettered_at` (`specs/order_saga_orchestrator/design.md:605`), and 27's acceptance item 12 names `0002`.
- The live `otc_orders` at `0002` is registered (`progress/current.md:27`).

**Backlog 213, item 2.** `grep -rn "saga.md" services/orders progress/impl_orders_cancel_responder.md | grep -n "§2\|section 2"` gives **one hit**: `progress/impl_orders_cancel_responder.md:182` *"(section 2, question 5)"*. Classification: it refers to the record's own §2, not to `saga.md` §2. A wider search, `grep -rn --include=*.py -E "§ ?2\b|section 2\b|saga\.md ?,? ?2[^0-9]" services/orders tests/architecture`, gives no hits. Item 2 holds.

## Ported-idiom ledger (impl record §3; `sdd: false`)

The ledger is present, with file and line on both halves. I probed the row most likely to be assumed, the lock: #8 `EfCoreOrderRepository.cs:106` takes `UPDLOCK, ROWLOCK`, and #8's `CancelOrderCommandHandler.cs:135` calls `GetByIdAsync`, which takes it. In #9, C1 proves the cancel waits on the lock. I also probed the envelope-content query row: #8 `EfCoreSagaCommandStore.cs:342-353`, `eventType == "orders.cancel.requested"`. The rows hold.

## Inherited findings

| Finding | Status | Evidence |
|---|---|---|
| #8 D1 (release-reason arms transposed, all green) | **avoided** | C3 fails on both paths, at the observed request |
| #8 D2 (schema-required reply field missing) | **avoided** | generated models; schema both ways (`test_the_reply_models_fields_are_exactly_…`) and the observed reply keys; C7 |
| #8 id 62 (cancel races forward progress) | **avoided** | held-lock race, both outcomes; C1 |
| #8 id 63 (readiness race, unpaced retries) | **avoided** | `flush()` after the last subscribe (impl R7); `wait_then_assert` paced (impl P1); `grep` for `asyncio.sleep` / `time.sleep` over the 10 new test files: no hits |
| #8 id 71 (note lost on async branches) | **avoided** | note at four statuses, three end to end; C5 |
| #8 id 91 (query unguarded against a real DB) | **avoided** | 14 cases with one-identifier decoys; B1–B5 |

## CHECKPOINTS.md

- **C1:**
  - [x] files exist;
  - [x] `progress/` files exist;
  - [x] the seven agents exist;
  - [x] every agent declares its model (4 by `model:`; leader, reviewer and spec_author state that they inherit it);
  - [x] `./init.sh` exits 0.
- **C2:**
  - [x] at most one `in_progress` (none);
  - [x] valid statuses;
  - [x] done features have passing tests;
  - [x] `current.md` is current;
  - [x] no `blocked`.
- **C3:**
  - [x] `lint-imports` 13 kept, 0 broken (no `domain/` edit);
  - [x] no cross-service DB access or import;
  - [x] no new shared package;
  - [x] no `otc_cqrs` in domain;
  - [x] kernel and cqrs `dependencies = []` (unchanged);
  - [x] no money arithmetic added;
  - [x] `orders.cancel` and `credit.release` are NATS-RPC, the completing facts are Kafka;
  - [x] no stray debug output or context-free TODO in the diff.
- **C4:**
  - [x] `quality.sh` exit 0;
  - [x] domain tests pure (unchanged);
  - [x] testcontainers, dev stack down;
  - [x] coverage 98 % domain / 97.53 % overall;
  - [x] no Jest, Karma or Jasmine (`grep -c` on `apps/web/package.json`: 0).
- **C5:**
  - [x] no suspicious untracked files (`.arm/` is git-ignored);
  - [ ] **effort record in `progress/history.md`: the leader's to write** (as for 25 and 40);
  - [x] `feature_list.json` id 41 → `done`;
  - [x] human told: the leader's;
  - [x] no commit.
- **C6:** n/a (`sdd: false`).
- **C7:**
  - [x] `specs/shared/` byte-identical to #7 and #8 except `test-matrix.md` (`cmp`, 6 of 6);
  - [x] no silent fork: N1 is routed to `SA-8` / 216;
  - [x] no R ids claimed;
  - n/a n8n;
  - n/a API script;
  - [x] inherited findings accounted for (table above);
  - [ ] effort honesty: the leader's entry;
  - n/a README.

## What the leader must do

1. Write feature 41's `progress/history.md` effort entry, naming D1, D2, 62, 63, 71 and 91 as avoided.
2. File backlog `216` and the `SA-8` proposal for N1. The text is in N1 above; the evidence is `.arm/r41/stranded.out`.
