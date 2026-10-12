# Brief — implementer, backlog 216 `operator_cancel_at_placed_strands_the_stock_reservation` (phase 13, `sdd: false`, full group — saga)

**Task:** implement backlog 216 (`feature_list.json` id 216, **three** acceptance items) — #9's code half of the approved spec amendment **`SA-8`**. Backlog 216 is set `in_progress` by the leader at dispatch. Specification of record: the three items and the amended `specs/shared/saga.md` — §4.3's new paragraph *"A stock reservation that arrives after the cancellation"*, §5's `stock.reserved.v1` row, §6's `stock.reserved.v1` redelivery row (applied by the leader's `spec_author` and recorded in `progress/sa7_sa8_sa9_application.md`; read the applied text, not the proposal). Classification: **full group** (saga), so an Opus reviewer follows. The ledger lives in your impl record.

**The rule, as `SA-8` states it:** a `stock.reserved.v1` for an order already `cancelled` with reason `operator_cancelled` issues `stock.release` (reason `order_cancelled`) and **nothing else** — no transition, no `credit.hold`; that release reaches the timeline as its own `stock.released.v1` (which the saga then ignores at `cancelled`, R25).

## Inputs (found on disk by the leader)

- **The defect, reproduced:** the reviewer's scratch test `.arm/r41/test_r41_stranded_reservation.py` and its output `.arm/r41/stranded.out` (`1 passed in 12.48s`: `command rows: [('stock.reserve', 'sent')]`, `stock.release requests: []`, `outbox: ['order.cancelled.v1']`), described in `progress/review_orders_cancel_responder.md` N1. Acceptance 2 is that scenario **committed as a #9 test that fails before your fix** — show it failing first (record the verbatim failure), then passing.
- **The twin you mirror:** `SA-4`'s late credit approval, built by feature 41 — `services/orders/src/otc_orders/application/saga/fact_handler.py` (`handle` at line 68; the `LATE_APPROVAL_EVENT_TYPE` branch at line 84; `_is_late_approval` at line 128; `_enqueue` at line 140; `_ignore` at line 164), the step table `application/saga/step_table.py`, `map_release_reason`'s `order_cancelled` branch, and their tests (`progress/impl_orders_cancel_responder.md` §2 q6 and its arms F1 – F8). Decide whether the new branch is a second late-arrival branch beside it or a generalisation of it — and say why; do not weaken the existing branch or its guards (re-run its arms after your change).
- **Command idempotency:** the saga ledger is unique on (order, command) — a redelivered `stock.reserved.v1` after the release must add **no** second `stock.release` row (acceptance 3). Note the existing case where a `stock.release` row already exists for the order (an operator cancel from `stock_reserved` owes one with the note): what does the new branch do then, and is that right?
- **The decoys** (acceptance 3): a late `stock.reserved.v1` for an order cancelled `stock_rejected` or `credit_rejected` releases nothing (and say whether either is reachable; R26 / F3: a `stock.rejected.v1` means nothing was reserved).
- **#7 and #8 have no counterpart** (the defect is shared; their code is not changed — the maintainer's ruling keeps `SA-8` spec-only there): the ledger's "#7 relied on / #8 supplied" halves cite their absence (`../order-to-cash-dotnet/src/Orders/Application/Commands/CancelOrderCommandHandler.cs:157-169`, `src/Orders/Application/Sagas/SagaStepTable.cs:181-186`; `../order-to-cash-nestjs/apps/orders/src/application/cancel-order.handler.ts:118-131`, `saga-steps.ts:173-178`) and their nearest analogue (the late-credit rule).

## Must hold (each a guard; each armed)

- Acceptance 2's end-to-end test (real Orders host, real NATS / Kafka / PostgreSQL; the stand-in Fulfillment held, then released): after the late `stock.reserved.v1`, exactly one `stock.release` request with `reason: order_cancelled` reaches the responder; no transition, no `credit.hold` row, no `order.*` fact beyond the earlier `order.cancelled.v1`.
- The two mutation families on the new emission (delete it; corrupt a field of the `stock.release` request — the reason to `credit_rejected`, the order reference to another order's), plus inverting the precondition, and making it fire for any cancelled reason (the decoys must fail).
- Redelivery: a byte-identical redelivery of the late `stock.reserved.v1` adds no row and sends no second request (count against the pre-redelivery baseline, not zero).
- The note: the late release carries no note onto a wire payload that does not declare it.
- Every existing saga test still green, including feature 41's late-approval arms (re-run, do not re-read).

## Process

- Arming protocol (grep `CLAUDE.md` on disk): backups in `.arm/n216/` with `sha256`; one named test per arm; the failure message names the claim and arrives fast; restore by `cp` + `cmp`; clear caches; a timeout kills the whole process group. Defeat list: state which rows apply.
- Baseline `./quality.sh` first (developer stack down; exit code, pytest time and pass count), a second at the end (delta, time per test). Wait on the real PID; read the verdict from the log.
- `specs/shared/test-matrix.md` column 5 only if a row's named test changes (R25's ignore guard is unchanged; say whether any row needs the new test).
- Write `progress/impl_operator_cancel_at_placed_strands_the_stock_reservation.md` early.

## Bounds

May touch: `services/orders/src/otc_orders/application/saga/**`, `services/orders/src/otc_orders/infrastructure/saga/**` only if the enqueue needs it, `services/orders/tests/**`; `specs/shared/test-matrix.md` column 5 (as above); the impl record; backlog 216's status line in `feature_list.json`. **No** edit to `domain/**`, `alembic/**`, other services, `packages/**`, `specs/shared/` beyond column 5. No migration. No git command that writes the index or working tree.

## Output

The impl record: what was built (file:line); the branch decision and why; the ledger; the failing-first run; the arming table (mutation, test, verbatim message, `sha256`, `cmp`); defeat-list rows; the two `quality.sh` runs. Set 216 to `in_review` (that line only). Return only "result in `progress/impl_operator_cancel_at_placed_strands_the_stock_reservation.md`" plus at most 4 lines.

## Premise check

`progress/premise_impl_operator_cancel_at_placed_strands_the_stock_reservation.md`: nothing false; #8's `SagaStepTable.cs` path completed above.
