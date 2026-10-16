# Brief — implementer, feature 29 `web_app`, **stage 1, fix round 1** (phase 16, full group: security)

**Task:** close the five blocking findings of the stage 1 review, plus advisories A1, A2, A5 and A6 (findings are fixed in the phase that detects them). The review is `progress/review_web_app.md` section "Stage 1 review" — read **"Blocking findings"**, **"Advisories"** and **"What must change before re-review"** in full; each finding names its file, line, probe and the required change. The reviewer's probe scripts and outputs are in `.arm/web29r1/` (`probe1.mjs`, `probe2.mjs`, `*.out`): reuse them to confirm each fix before and after. The stage 1 scope and its bounds are `progress/brief_impl_web_app_stage1.md`; the implementer's record is `progress/impl_web_app.md` "Stage 1".

## What must change (the review's list, with the leader's additions)

1. **B1 — CSRF bypassed by a percent-encoded path.** Check every non-safe method regardless of path, or on the decoded path the router uses; refuse a mutating request whose `Content-Type` is not `application/json` with the BFF's own 415 problem; correct the false comment at `middleware/csrf.ts:12-13`; add the encoded-path (`/%61pi/…`, `/ap%69/…`) and urlencoded/`text/plain` cases to `R-csrf`, **in-process and on the production build**, and arm them (delete each part of the fix; a named test must fail).
2. **B2 — the SSE upstream leaks when the client leaves before the upstream headers arrive.** Wire the abort to the request/response close **before** opening the upstream, and check `res.destroyed` after the await; add the contract case "client leaves before the upstream answers its headers: upstream aborted within the bound", in-process and on the production build; arm it by moving the listener back.
3. **B3 — the log guard is blind to objects.** Format captured console calls as console does (`util.format` / `util.inspect` with unlimited depth), or capture `process.stdout`/`stderr`; consider asserting the production server's own output too (`RunningServer.output()`). Re-arm with the review's object-argument mutation R_B19.
4. **B4 — generic text inside the problem's own text node.** For a node containing the sentinel, remove the sentinel and require the remainder (trimmed of whitespace and punctuation) to be empty or a reviewed label. Re-arm with R_G1inline (`Something went wrong. {{ errorText() }}` in the login alert).
5. **B5 — `..` ids.** Answer the BFF's own 400 problem for a path id that is empty, `.` or `..`, or contains `/` or `?` after decoding. Add the `..`, `%2E%2E`, `.` and `x%3Fy` cases. **Enumerate the class first:** the review's search (`grep -rn "getRequestURL\|event\.path\|getRouterParam\|\.pathname\|originalUrl\|node\.req\.url" src/server scripts`, tests excluded) gave 5 hits. Re-run it, classify every hit (including `lib/gateway.ts:109`'s raw `search`), and fix every one that is a site of the class.
6. **A1:** an unreadable/tampered session cookie is cleared, not replaced with a freshly minted session; extend the tampered-cookie test to assert no new session cookie is set. Arm it.
7. **A2:** the BFF-local 502/504 problem `detail` no longer contains the internal Gateway URL; the URL goes to a server log line. Test both sides; arm it.
8. **A5:** pin `h3` exactly (the version the lockfile resolves today, 1.15.11 per the review; confirm), since the BFF's security reasoning cites its internals by line.
9. **A6:** the Origin check compares full origins (scheme + host + port), not hosts; add the scheme-mismatch case.

**Not in this round:** A3 (runtime-recorded late-request bound) and A4 (the stale-label direction) are stage 2 work. Leave them, and do not build any page.

## Process

As in the stage 1 brief: `CLAUDE.md`'s arming protocol (grep it on disk); backups in `.arm/web29s1r2/` with `sha256`; restore by `cp` + `cmp`, then rebuild where `dist/` could serve old code; every run under `setsid --wait` with a process-group timeout; verdicts from a reporter artifact. Arming never deletes or moves a tracked path. Wait on a PID, never on `pgrep -f`. State which defeat-list rows apply to each new guard. Run the review's probes `probe1.mjs` / `probe2.mjs` against the production build after the fix and record their new output verbatim. Gates at the end: `quality.sh` section 7's commands (`npx --yes pnpm@12.8.1 -C apps/web …`: `install --frozen-lockfile`, `types:check`, `test:ci`, `build`), with the Vitest count reconciled against 18 files / 236 tests. The developer stack is not needed. Make sure no stray Nitro server is left (`ss -ltnp` before and after).

## Bounds

May touch: `apps/web/**`; `progress/impl_web_app.md`. **No edit to `progress/review_web_app.md`, `services/**`, `packages/**`, `tests/**`, `specs/**`, `.env.example`, `quality.sh`, compose, `feature_list.json`.** No git command that writes the index or working tree.

## Output

Append a section **"Stage 1 — fix round 1"** to `progress/impl_web_app.md`: one row per item above (finding, change, file:line, test, arm with verbatim failure message, `sha256`, `cmp`); the B5 class enumeration (command, full output, one classification per hit); the probes' new output; corrections to any earlier claim in the "Stage 1" section that a finding showed false (mark them in place as corrected, do not delete); gate results; `Packages installed:` (expected: none, apart from the h3 pin change). Return only "result in `progress/impl_web_app.md`" plus at most 5 lines.
