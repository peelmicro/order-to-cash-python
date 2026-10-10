# Brief — reviewer, feature 19 `billing_credit`, round 2

**Task:** re-review feature 19 after the fix round. Round 1 (`progress/review_billing_credit.md` §§0–9) REJECTED it with three blocking defects (D1 – D3) and three non-blocking items (N1 – N3), all in tests; its §8 is the list of what had to change. The fix is recorded in `progress/impl_billing_credit.md` § Round 2 (from line 712). Feature 19 is `in_review`. **Append** your verdict to `progress/review_billing_credit.md` as "Round 2" below round 1; do not rewrite round 1.

- **On APPROVED:** set 19 to `done` (that line only) and append the effort entry to `progress/history.md` as round 1's brief (`progress/brief_review_billing_credit.md`, first bullet) describes, against #8 (`../order-to-cash-dotnet/progress/history.md` line 1215) and #7 (`../order-to-cash-nestjs/progress/history.md` line 882). Classification: full group. Add to the durations that brief lists: review round 1 ≈42 min (review §9), the fix round ≈77 min (4 633 s, leader-measured from the agent run), two more premise checks of under 1 min each, and your own. Name round 1's D1 as **recurred** (#7 W3/N5, #8 D3) and fixed in round 2. Name every other inherited finding of `design.md` §17 avoided or recurred.
- **On REJECTED:** set 19 to `in_progress` and write "What must change". This would be the second rejection: the leader stops and asks the maintainer, so make each item self-contained.

## What the leader established (with commands) — locate, do not trust

- No file under `services/*/src` or `packages/` is newer than the round-2 brief (`find … -newer progress/brief_impl_billing_credit_round2.md`: empty). The `.py` files changed in the fix round are exactly: `services/billing/tests/integration/test_credit_release.py`, `services/billing/tests/integration/test_credit_repository.py`, `services/billing/tests/unit/domain/test_credit_exposure.py`, `services/billing/tests/unit/domain/test_credit_ledger.py`, `services/billing/tests/unit/test_credit_release_service.py`, `tests/architecture/test_outbox_copy_parity.py`.
- Feature 19 is `in_review`; only `otcpy-n8n` runs. **Do not start the developer stack.**
- Reported, not verified by the leader: `quality.sh` exit 0 in 366 s, 3 154 passed (round 1: 3 111); arms U8 – U10, `Q1-code-on-docstring-line-plus-file-noqa`, the old text-match census (15 of 18 spelling cases red), `['notifications']`, R9a, `D6-mine-mapper-aware-local` and four arms on the new instruments seen red, then green after restore; one sentinel (P4, byte versus character) survived first and was fixed.

## Questions to rule on

1. **D1:** re-run U8, U9, U10 exactly as your round 1 wrote them, and confirm each is now killed by the test your §8 named. Do the new fixtures make available-after differ from **both** the limit and the pre-release value, in every case (the impl report says which three values each produces)?
2. **D2 — the parity instrument changed again.** Re-run your round-1 `Q1` mutation on the real tree. List the new instrument's premises (the allow-list literal of pre-docstring lines, `end_col_offset` on the closing line, the P4 byte-versus-character handling) and attack each one: a non-allow-listed directive before the docstring, code after the closing quotes on the same line, a multi-byte character before the closing quotes, a docstring opened with `'''` or with a prefix (`r"""`).
3. **D3 — the census now recognises what a module declares.** Re-run your round-1 §4 D3 forms (annotated, constant, Core `Table`, another module) and add one form the new instrument does not list. **The new `MIRRORS_NOT_OWNERS` exclusion** (`services/seed/src/otc_seed/infrastructure/tables.py`, a Core `Table("outbox")` mirror): is the seed truly a mirror and not an owner (does it write an outbox, and does #7's or #8's seed?), is the exclusion a literal with its reason, and does the real-tree test fail when the exclusion goes stale (the mirror removed) or when a second service's mirror is added?
4. **N1 – N3:** N1 and N2 as your §8 item 4 required. N3 was accepted, not fixed, because the fix needs a production change: rule on the acceptance, and if you accept it, word it as "ACCEPTED, NOT FIXED" with a re-open trigger.
5. **Unplanned mutations:** at least three of your own in the changed test files' subject code (the release path's available-credit computation and the two instruments), with verbatim results.
6. Run `./quality.sh` once with the stack down and report exit code, duration and pass count.

## Bounds

Read-only except your Round 2 section of `progress/review_billing_credit.md`, feature 19's status line and, on approval, `progress/history.md`. Arming backups in `.arm/review19r2/` with `sha256`; restore by `cp` + `cmp`, never `git checkout` / `restore` / `stash`; clear `__pycache__` and `.mypy_cache`; timeouts kill the whole process group. Return only "result in `progress/review_billing_credit.md` § Round 2" plus the verdict and at most 5 lines.
