# Brief — reviewer (sonnet), feature 24 `projector_read_model`, round 3 (maintainer-approved, scoped)

**Task:** verify that round 3 closed exactly **B5, B6 and N9** of `progress/review_projector_read_model.md` ("Round 2 — what must change before re-review" items 1 – 3). The implementer's work is the "Round 3" section of `progress/impl_projector_read_model.md`; its brief is `progress/brief_impl_projector_read_model_round3.md`. Feature 24 is `in_review`. Read `CLAUDE.md` on disk first. Everything else in the feature was reviewed and closed in rounds 1 – 2; do not re-open it.

## Verified by the leader this session

- `specs/shared/test-matrix.md` vs `HEAD`: only column 5 of R50 – R55 and the Done/TODO cells of the §7 and Total rows differ (cell-by-cell parse); the round-3 edit is R50's column 5 sentence on the scrambled `eventId`s.
- `feature_list.json`: 24 `in_review`, 214 `pending`.

## What to check (each by running it, not by reading the record)

1. **B5:** run round 2's `S5` and `S6` (`.arm/p24-review2/shapes.py`) against the projector's real root: each must fail the guard. Confirm the five real roots pass. Run the new n = 1 sentinels (`one_holder`, `one_globals`, `one_alias`) and one arm of the new name clause of your own (e.g. make the terminal-identifier comparison always true): a named test must fail. The implementer states one gap — for a lambda handler only the message is checked — classify it.
2. **B6:** run `B3r-outermost` (`.arm/p24-review2/B3r-outermost.py`) and `S8` on the real root: each must fail. Check the record's premise list: each premise names an arm, and any premise not re-armed this round is said so.
3. **N9:** run `R50r-arrival-order` and `R50r-eventid-desc`: both must fail `test_r50_…`; the fixture's `eventId` order is neither ascending nor descending against `occurredAt`, and arrival order differs from both.
4. **Regression:** `tests/architecture` in full plus `services/projector` tests; confirm the record's `quality.sh` log (`.arm/p24-r3/`; claimed exit 0, 511 s, 4086 passed).

## Stopping rule (maintainer ruling 2026-10-11, binding)

This is the last round. If you bypass the registration guard with a further new shape, do **not** reject for it: record the shape as **ACCEPTED, NOT FIXED** with its proof and a re-open trigger, and name it for carrying to feature 25 `gateway_rest_auth` (the leader files it). Reject only if B5, B6 or N9 as specified is not closed, or a regression appears.

## Rules and output

Arming protocol as before (`.arm/p24-review3/`, sha256, `cp` + `cmp` restore, clear `__pycache__`/`.mypy_cache`, process-group kill on timeout; never `git checkout`). Read-only otherwise. Append a "Round 3" section to `progress/review_projector_read_model.md` with the verdict, each check's command and result, and any accepted shape. On approval set feature 24's status line to `done`; on rejection `in_progress`; that line only. Return only "result in `progress/review_projector_read_model.md`" plus the verdict and the count of blocking findings.
