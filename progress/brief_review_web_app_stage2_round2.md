# Brief — reviewer, feature 29 `web_app`, stage 2 **scoped re-review** after fix round 1 (phase 16; money is full group)

**Task:** approve or reject stage 2 after fix round 1. Scope: **only** the items of `progress/brief_impl_web_app_stage2_round2.md` (1–7) and the leader's item 8 (the keystroke scramble, sent to the implementer after its first return: `progress/current.md`, *Decisions*). The implementer's record is `progress/impl_web_app.md` section "Stage 2 — fix round 1" (lines 664–789, including "Item 8" from line 753). Your own stage 2 review is `progress/review_web_app.md` "Stage 2 review"; your probes and arm driver are in `.arm/web29r2/s2/`.

## Stopping rule (written by the leader before the review starts)

Reject only for: (a) a scoped item (B1 as a class over every `type="number"` input, B2, A1, A2, item 8) that is unmet, shown by a probe; (b) a live money or product defect **in the code those items changed**, shown by a probe; (c) a guard the record claims as armed that does not fail when its claim is broken. Anything outside these items, including anything new elsewhere, is an **advisory** carried to stage 3 as an acceptance item, not a rejection. A3/A4 are record corrections: check them, advisory only. A5 was accepted by the leader with a re-open trigger: not a ground. **This is the last round without the maintainer:** a rejection here stops the work and goes to the maintainer, so each blocking finding must carry a recommendation and the probe output.

## Probes the leader asks for

1. **B1.** Re-run your `.arm/web29r2/s2/live/bytes.mjs` against a fresh production build: the malformed unit price, discount and quantity texts send nothing and show the problem; the controls "19.99" → 1999, "0.29" → 29, BHD "1.005" → 1005 hold. Re-run the per-field `badInput` arms.
2. **B2.** Re-run V07, V07c (must fail, naming the app timer) and P18. Judge F08 (the record calls it an instrument control that survives by design).
3. **A1.** Re-run V09, N1_line_deleted, N1_prod and R03 (production).
4. **A2.** Re-run `live/listpoll.mjs`, plus the arm that removes the `isError` condition.
5. **Item 8 (the centre of this round).** The record says Chromium reports `"19"` for a typed `"19."`, and that a lagging `[value]` render reassigned it, resetting the caret. The fix is the directive `components/draft-value.ts` (assign only when `element.value !== text`) on the three number inputs. The guard `R-typing` in `place-order.spec.ts` asserts the **cause** (no redundant assignment), because jsdom cannot move a caret. Questions: is the mechanism true (reproduce the scramble yourself on the pre-fix code, from the record's backup, in the production build in Chromium)? Is the fix complete for every path that writes those inputs (a currency change resets the step, a catalogue price arriving, a line added or removed, a draft reset after a submit failure)? Is the cause-level guard sufficient, or does the property need a Chromium guard (the `src/build/` harness already drives a production build: could a test there type into the page)? Recommend one, with evidence. Cold-start: type without waiting for settling, at least five runs, and report each.
6. **Gates.** Section 7's four commands once, plus `uv run pytest packages/shared_kernel/tests/test_currency_exponent.py`. Reconcile 28 files / 466 tests.

## Process

Read-only, as in your stage 2 brief: backups in `.arm/web29r3/`, `setsid --wait` with a process-group timeout, verdicts from reporter artifacts, restore with `cp` and check with `cmp`, rebuild after a restore. Stop what you start. `git status --short` must equal `.arm/phase16/status_before_review3.txt` when you finish.

## Output

`progress/review_web_app.md`, new section "Stage 2 re-review (fix round 1)": verdict, findings under the stopping rule, the arms re-run (mutation, test, verbatim message, `cmp`), the item 8 recommendation, and the gates. Return only "result in `progress/review_web_app.md`" plus the verdict and at most 4 lines.
