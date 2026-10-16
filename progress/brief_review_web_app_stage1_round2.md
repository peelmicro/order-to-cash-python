# Brief — reviewer, feature 29 `web_app`, **stage 1 re-review after fix round 1** (phase 16, full group: security)

**Task:** verify the fix round against the stage 1 review's list. Inputs: `progress/review_web_app.md` "Stage 1 review" → *What must change before re-review* (B1–B5) and *Advisories* (A1, A2, A5, A6 were folded into the round by the leader; A3, A4 are stage 2 work, not this round's); the fix brief `progress/brief_impl_web_app_stage1_round2.md` (nine items); the record `progress/impl_web_app.md` section "Stage 1 — fix round 1" (line 304 on). Your round 1 probes are in `.arm/web29r1/`.

## Stopping rule (written by the leader before the re-review)

Verify exactly the nine items. Reject only for (a) an item unmet, shown by a probe, (b) a live security or product defect **introduced by the fix round**, or (c) a new guard claimed as armed that does not fail when its claim is broken. Anything else is an advisory with a recommendation. Do not re-audit what round 1 already found sound. This is the last round before the maintainer is asked (CLAUDE.md: a second rejection stops the loop), so state for each blocking finding whether it is a one-line fix.

## What to re-run

- Your own round 1 arms **R_B19** (object-argument log leak) and **R_G1inline** (generic text in the problem's text node), and `probe1.mjs` / `probe2.mjs` against a fresh production build (the B1, B2 and B5 cases you quoted).
- A sample of the round's 32 new arms that covers every item, at least one each, plus the B1 encoded-path / urlencoded / `text/plain` cases in-process and on the production build.
- Judge the two disclosures: **B2b** (the post-await `res.destroyed` check in `stream.get.ts` survives deletion because the early listener already aborts; the implementer kept it as defence in depth and calls it unarmable): keep or remove? Untested code is the question. **B05** (the `sessionHeader: false` arm is now an equivalent mutant because A1 unseals the cookie directly): is the header-session property still guarded by a test that fails when the header *is* read?
- The B5 class enumeration (record line 324): re-run the search and check the classification.
- Gates once: `install --frozen-lockfile`, `types:check`, `test:ci` (record: 18 files / 251 tests = 236 + 15), `build`.

## Process

As in round 1: read-only; arms per `CLAUDE.md` (backups in `.arm/web29r2/`, `sha256`, `cp` + `cmp`, rebuild after restore, `setsid --wait` with a process-group timeout, verdict from a reporter artifact, never `pgrep -f`); leave `git status --short` and `ss -ltnp` as you found them. Nobody else is running tests.

## Output

Append "Stage 1 re-review (fix round 1)" to `progress/review_web_app.md`: verdict; one row per item (met / unmet, probe, verbatim output); arms re-run (mutation, test, verbatim message, `cmp`); the B2b and B05 judgements; gates; advisories. Do not edit `feature_list.json`. Return only "result in `progress/review_web_app.md`" plus the verdict and at most 4 lines.
