# Brief — reviewer, feature 13 `orders_aggregate` (phase 8, full group: money domain)

**Task:** approve or reject the implementation of `specs/orders_aggregate/` (approved at the human gate 2026-10-06). Write `progress/review_orders_aggregate.md`. On approval set feature 13 to `done`; on rejection set it to `in_progress`. Edit only that line of `feature_list.json`. Read-only otherwise: no source edits, no git command that writes the index or working tree. Return a verdict and at most 8 lines.

## Inputs

- Spec: `specs/orders_aggregate/{requirements,design,tasks}.md`. Implementation report: `progress/impl_orders_aggregate.md`. Implementer brief: `progress/brief_impl_orders_aggregate.md`.
- Change set (leader's `git status --short`, this session): new `services/orders/src/otc_orders/domain/{errors,events,instants,order,order_line,snapshot,state_machine,totals}.py` and `value_objects/{cancellation_reason,compensation_step,order_status}.py`; new `services/orders/tests/unit/domain/` and `services/orders/tests/unit/test_order_domain_contract_parity.py`; new `packages/shared_kernel/src/otc_shared_kernel/money_text.py` and `packages/shared_kernel/tests/test_money_text.py`; modified kernel `__init__.py`, `test_kernel_surface.py`, `services/seed/.../data/sagas.py`, `services/seed/tests/unit/test_money_text.py`, deleted `services/seed/src/otc_seed/domain/money_text.py`; modified `tests/architecture/test_money_guard.py`, `tests/architecture/test_write_path_population.py`, `specs/shared/test-matrix.md`.
- #8's review of the same feature, the bar to beat: `../order-to-cash-dotnet/progress/history.md` lines 629–675 (its one defect was an unrequested probe that survived: two `Rehydrate` checks deletable with the suite green). #7's code: `../order-to-cash-nestjs/apps/orders/src/domain/`; #8's: `../order-to-cash-dotnet/src/Orders/Domain/`.

## What the leader has already established (with a command, this session)

- `specs/orders_aggregate/design.md` changed during the implementer's run (mtime 09:13:57). Cause: ruff 0.16.10 formats fenced Python blocks in Markdown, and the repo-wide `uv run ruff format` / `ruff format --check` (quality.sh step 1) include `specs/**/*.md` — a probe `.md` with `x=[1,2 ,3]` was reported "would be reformatted". The pre-change content was untracked, so there is no diff; judge whether `design.md`'s code blocks still say what the spec meant (a formatting-only change is the expected outcome).
- `specs/shared/` contains no ```python blocks; its only diff is `test-matrix.md` (8 lines: summary counts 3/1/6 → 9/1/0 and 3/1/59 → 9/1/53, plus rows R5–R10).
- The implementer reported `./quality.sh` exit 0 in 131 s, 1433 passed, with the `otcpy` stack up; Phase 7's wrap-up was 103.24 s / 1 290 passed with the stack stopped. Do not stop or start the stack.

## Questions for you (research, do not assume)

1. Re-arm, do not re-read: pick guards the implementer did NOT arm the same way, including at least one on the five silent T-1 edges (a different edge from the implementer's), one on the rehydrate checks, one on the money/totals path, and one on `format_money` in the kernel. Use the CLAUDE.md arming protocol (cp backup, `cmp` restore, cache clear). Also probe something nobody asked for.
2. The implementer flagged two spec texts: task 3.12's arm "cannot bite as worded" (it armed an equivalent), and task 4.16's wording is false because `FACT_MODELS` also holds `order.despatched.v1`. Is each substitute/finding sound? Does either leave a property unguarded?
3. Do the ledger rows of `design.md` §2 each have a guard that executes the code the row is about (the report's §4 table)? Check both halves.
4. #8's findings mapped in the spec (Rehydrate defect, A1–A5): avoided or recurred? Give the answer per id with evidence. A1 applies to the report itself: do its counts reconcile with a run you do (per-file figures summing to the headline)?
5. Does `test-matrix.md`'s edit keep columns 1–4 and every other row byte-identical (task 6.6)? Do the named test files/cases in column 5 exist?
6. Domain purity and the money rules: no float, no `/`, no `round`/`pow`, allow-list edit (`enum`) justified by a census, `bigint`-safe ints; the seed still produces identical text after the `format_money` move.
7. Is the 131 s / 1433 figure explained by this feature, and do the integration suites still pass with the developer stack irrelevant (they must not depend on it)? Report, do not fix.

Run the defeat list (CLAUDE.md) against the guards you probe and state which rows apply. Disposition every finding: fix (reject), accept with evidence, or re-open only if X. Findings are fixed in this phase (CLAUDE.md), not deferred.
