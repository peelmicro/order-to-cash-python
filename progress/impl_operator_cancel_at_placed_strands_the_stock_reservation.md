# Implementation record - backlog 216 `operator_cancel_at_placed_strands_the_stock_reservation` (phase 13, `sdd: false`, full group)

Status set to `in_review` (that line only). #9's code half of SA-8 (`saga.md` 4.3 "A stock reservation that arrives after the cancellation", 5, 6).

## 1. What was built

- `services/orders/src/otc_orders/application/saga/fact_handler.py`: `LATE_RESERVATION_EVENT_TYPE`; in `work`, a branch BEFORE `step_for_status` (beside the late-approval one): `stock.reserved.v1` and `_is_late_reservation(order)` -> `_enqueue(STOCK_RELEASE)` and return (no transition, no `credit.hold`). `_is_late_reservation`: status `cancelled` and reason `operator_cancelled`.
- `.../saga/command_payloads.py`: `STOCK_RELEASE` built from `stock.reserved.v1` is `build_operator_stock_release_payload(order)` (aggregate's reference, reason `order_cancelled`, no note: the wire payload declares none); any other non-`credit.rejected.v1` trigger still raises.
- `step_table.py`, `infrastructure/**`, `domain/**`: untouched. `DISPATCH_EVENTS[STOCK_RELEASE]` (`CreditRejectionRecorded`) only signals the `stock.release` row, which is the right signal (name is historical).
- Tests: new `services/orders/tests/integration/saga/test_late_stock_reservation.py` (6 cases); `tests/unit/saga/test_command_payloads.py`: `stock.reserved.v1` removed from the "raises" parametrisation (it is now owed) and a positive test added.

## 2. Branch decision

A SIBLING branch, not a generalisation of the late-approval one. The approval's late shapes include `stock_reserved` with the operator release under way (found through `find_accepted_operator_cancel`); the reservation's only shape is `cancelled`/`operator_cancelled` (a `stock_reserved` order already holds the stock and the cancel owes the release). Different fact, command and predicate; sharing would have forced the approval's guards onto a different rule. The late-approval branch is unchanged (its tests are in the green run).

Existing `stock.release` row for the order: `enqueue` is `ON CONFLICT (order_id, command) DO NOTHING`, so `ALREADY_OWED`, the row is re-signalled and nothing new is written; this is saga.md 6's "(re-)issued, idempotent". Right for an operator cancel from `stock_reserved` (which owes the row with the note and whose release already covers the reservation). Reachability of the decoys: `credit_rejected` cancellation is reachable only after a `stock.reserved.v1` was processed (so a second one is a redelivery/duplicate), `stock_rejected` only from `placed` after a rejection (a late `stock.reserved.v1` for it would mean a second answer to one `stock.reserve`; contract-wise unreachable, the test drives it anyway).

## 3. Ledger (ported idioms)

| Idiom | #7 relied on | #8 supplied | #9 |
|---|---|---|---|
| Stock reservation after an operator cancel at `placed` | none owed: no branch (`../order-to-cash-nestjs/apps/orders/src/application/cancel-order.handler.ts:118-131`, `saga-steps.ts:173-178`) | none owed (`../order-to-cash-dotnet/src/Orders/Application/Commands/CancelOrderCommandHandler.cs:157-169`, `src/Orders/Application/Sagas/SagaStepTable.cs:181-186`) | `fact_handler.py` late-reservation branch; armed A1-A6 |
| Nearest analogue, late credit approval | `credit.release` branch | same | feature 41's `_is_late_approval`, unchanged, sibling |
| One owed command per (order, command) | unique ledger | unique ledger | `ON CONFLICT DO NOTHING` (`command_queue.py:58`); redelivery test counts against the one-row baseline |
| Python: `/` on `int`, JSON, loops, cancellation, `Any` | | | none touched; payload serialised by `to_wire_json` as for every command |

Inherited-finding bookkeeping: #8 id 104 (developer infra hiding) avoided: runs below with the developer stack down.

## 4. Failing first (before the fix)

`pytest .../test_late_stock_reservation.py -k operator_cancel_at_placed` against the unfixed code:
`AssertionError: timed out after 30s waiting for: the late reservation owes stock.release` (log: `saga fact ignored`), `1 failed, 5 deselected in 38.98s`. After the fix: `6 passed in 16.75s`.

## 5. Arming (backups in `.arm/n216/*.bak`, outputs `*.out`, driver `.arm/n216/arm.py`; each restored by `cp`, `cmp` identical, caches cleared)

| Arm | Mutation | Test that failed | Message (first line) | sha256 of the backed-up file (16) |
|---|---|---|---|---|
| A1 | delete the emission | `test_the_late_reservation_release_carries_...` | timed out after 20s waiting for: the stock.release row reaches sent | a6103dcaf2a7f959 |
| A2 | reason -> `credit_rejected` | same | `the wire payload declares no note, so none is sent` (dict diff: `credit_rejected` vs `order_cancelled`) | 784cf006dc17986f |
| A3 | reference from the fact (a sibling order's) | same | same message (dict diff on `orderReference`) | 784cf006dc17986f |
| A4 | precondition inverted | same | timed out ... stock.release row reaches sent | a6103dcaf2a7f959 |
| A5 | fires for any cancelled reason | `test_a_late_reservation_for_a_cancellation_the_saga_decided...[CREDIT_REJECTED]` | timed out ... stock.reserved.v1 is recorded as a precondition_unmet fact | a6103dcaf2a7f959 |
| A6 | also enqueue `credit.hold` | `test_an_operator_cancel_at_placed_then_...` | `assert <Record ... command='credit.hold' status='sent'...> is None` | a6103dcaf2a7f959 |
| A7 | a second ledger row on the late path | `test_a_redelivered_late_reservation_adds_no_second_...` | timed out ... the second stock.reserved.v1 was consumed | a6103dcaf2a7f959 |

Caveats: A2/A3's message names the note claim, the diff names the break; A7 fails because the injected row poisons the transaction (consumption never completes), so it proves the redelivery test notices extra rows only indirectly; the unique-ledger claim itself is also covered by the existing `test_saga_command_ledger.py`. Not armed: the "ignores at cancelled, R25" half of the timeline claim beyond the e2e `stock.released.v1` ignored-row assertion.

Defeat-list rows applied: 1 (A1), 2 (A2, A3), 3 (A3: the fact's reference is a decoy order's), 8/9 (the redelivery baseline is one, not zero; the decoy test needs both rejected reasons), 12 (the e2e drives the real host path, not the handler). Rows 4-7, 10, 11 are syntax-guard rows: no syntax guard was added (behaviour is tested).

## 6. Matrix

`specs/shared/test-matrix.md` column 5: no row changed. R25's named test is unchanged and still green; R26/R34 rows are unchanged (their tests are not replaced). The new tests extend SA-8 only; no `R<n>` is added by the spec for it.

## 7. quality.sh

Baseline before the change was NOT taken (the dispatch gave no earlier slot and the code was already edited when I realised; reported as a gap). One run after: first run failed at ruff E501 (a docstring line, fixed); second run `exit 0`, "all gates passed": pytest `4768 passed in 562.52s (0:09:22)`, total real 9m55s, coverage 97.59%. The Gateway 215 work was in the tree and green in that run.

## 8. Surprises

- The existing unit test `test_stock_release_owed_by_any_fact_but_credit_rejected_raises` listed `stock.reserved.v1`; it had to change (in bounds, `tests/**`).
- The stand-in `stock.release` with `emit=True` publishes `stock.released.v1` with the request's reason, which lets the e2e prove the timeline fact reaches the saga and is ignored.

## Round 2 (test-only; D1 a/b, N-a, N-b of `progress/review_operator_cancel_at_placed_strands_the_stock_reservation.md`)

No source change (`fact_handler.py` sha256 `da2914d0…1e48` and `command_payloads.py` `784cf006…27bd1` unchanged, confirmed after the arms).

**What changed**
- `services/orders/tests/integration/saga/test_late_stock_reservation.py`: adds `test_a_reservation_at_stock_reserved_with_an_accepted_operator_cancel_is_still_ignored_as_out_of_order` (D1a: recorded `precondition_unmet`, observed `stock_reserved`, expected `placed`, no new row, order stays `stock_reserved`) and `test_a_reservation_after_an_operator_cancel_from_stock_reserved_adds_no_second_release_and_keeps_the_note` (D1b: same row id, payload and `operator_note`, request count unchanged, one `order.cancelled.v1` carrying the note). N-b: the redelivery baseline is now two asserts, `len(rows_before) == 1` and `requests_before == 1`.
- `services/orders/tests/unit/saga/test_command_payloads.py`: N-a, the fact carries `ORD-000099`, the order `ORD-000007`.
- Design note: D1a does not assert a request count, because the held (silent) stand-in is retried by the dispatcher, so the count is not a stable baseline (first run failed on exactly that); the row set and the stored row are asserted instead.

**Arms** (`.arm/n216r2/arm.py`; backups `.arm/n216r2/<arm>.bak`; each restored by copy, `cmp` identical, `__pycache__` cleared; `.out` files beside)

| Mutation | Test | First message | sha256 of the original |
|---|---|---|---|
| D1a: late branch also takes `stock_reserved` with an accepted cancel (R6b) | D1a test | `timed out after 20s waiting for: stock.reserved.v1 is recorded as a precondition_unmet fact` | fact_handler `da2914d0…1e48` |
| D1b: late path clears `operator_note` before enqueue | D1b test | `At index 0 diff: (UUID('c769fac7…'), 'stock.release', '{"orderReference":"ORD-000101","reason":"order_cancelled"}', None) != (…'keep: café €')` | same |
| D1b: late path deletes the operator row and writes its own | D1b test | same shape, row id differs (`5c321295…` != `87166df9…`) | same |
| N-a: payload reference taken from the fact | unit test | `AssertionError: assert 'ORD-000099' == 'ORD-000007'` | command_payloads `784cf006…27bd1` |
| N-b: late path also enqueues a `credit.release` row (two rows at baseline) | redelivery test | `AssertionError: the baseline is one row, not zero` / `assert 2 == 1` | fact_handler `da2914d0…1e48` |

**Gate:** `./quality.sh` exit 0, "all gates passed", **4 770 passed in 605.29 s** (0.128 s per test), real 10 m 32 s, coverage 98 %, import-linter 13 kept 0 broken; developer stack down (only `otcpy-n8n` running). 4 768 + 2 new = 4 770. An earlier attempt stopped at ruff PT018 (compound assert) before any test ran; fixed. Log `.arm/n216r2/quality.log`.

**Status:** 216 set to `in_review` (`feature_list.json` line 904).
