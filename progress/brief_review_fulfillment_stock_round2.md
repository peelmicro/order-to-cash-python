# Brief — reviewer, feature 17 `fulfillment_stock` (phase 9, full group, round 2)

**Task:** re-review feature 17 after the fix round. Your round-1 verdict is `progress/review_fulfillment_stock.md` (REJECTED; §6 D1–D7, §7 items 1–8). The fix round's record is `progress/impl_fulfillment_stock.md` § Round 2. Feature 17 is `in_review`. **Append a "Round 2" section** to `progress/review_fulfillment_stock.md`.

- **On APPROVED:** set 17 to `done` (that line only) and append the effort entry to `progress/history.md` as round 1's brief specified (`progress/brief_review_fulfillment_stock.md`, first bullet), now with two review rounds and one fix round. Leader-measured agent run times: spec_author ≈27 min, implementer ≈1 h 57 min, review round 1 ≈91 min (5 463 s), fix round ≈10 min (574 s), premise checks ≈3.5 min in all; add your own.
- **On REJECTED:** set 17 to `in_progress` and write "What must change". This would be the second rejection; the leader then stops and asks the maintainer, so state for each item whether it is blocking or could be accepted with a disposition (evidence and a re-open trigger).

## What the leader established (with commands) — locate, do not trust

- Files changed by the fix round (by `find -newer` the round-2 brief): `services/fulfillment/tests/integration/test_stock_release_idempotency.py`, `services/fulfillment/tests/integration/test_stock_repository.py`, `services/fulfillment/tests/unit/test_stock_reservation_service.py`, `specs/fulfillment_stock/design.md`, `specs/fulfillment_stock/requirements.md` (plus the impl report and 17's status line). Every `src` backup in `.arm/fix17/bak/` is `cmp`-identical to the live file.
- Item 7 (D4) was done by the leader: feature 18's acceptance carries the SA-4 despatch half. Verify the wording covers your D4.
- Reported, not verified: `quality.sh` exit 0, 2690 passed; arms R1, M9, M1a, M1b red then green; I5 and D5a re-armed, I5 now failing with "the release never waited on the held stock row…". Not done by choice: D3's optional host-level `UNAVAILABLE` reply, and `test-matrix.md` (the implementer argues the new tests guard FS rows, not R rows). Rule on both.
- Only `otcpy-n8n` runs; the developer stack stays stopped.

## What to do

1. Re-run each new arm yourself (R1, M1 at `:115` and at `:170`, M9, I5) and confirm each failure names its claim. Ask of each new test "what fails if I revert this?" and confirm the answer is the arm.
2. Check that the D2 test asserts **equality** with the supplied ids in minting order (not inequality or type), and that `test_fs5_…`'s "no domain function ran" observable no longer depends on the id port.
3. Check that D5's corrected citations are right against the files, and that D7's record fixes are true (G8's description, §8.1, the id 49 / 79 dispositions).
4. Re-run `quality.sh` once (stack down) and report the count and duration.
5. Any new mutation of your own that survives in code the fix round touched or guards is a finding.

## Bounds

As round 1: read-only except the review file, 17's status line and, on approval, `progress/history.md`. Arm backups in `.arm/review17r2/` with `sha256`; restore by `cp` + `cmp`; clear caches; timeouts kill the process group; never two test runs against the same containers. Return only "result in `progress/review_fulfillment_stock.md` § Round 2" plus the verdict and at most 5 lines.
