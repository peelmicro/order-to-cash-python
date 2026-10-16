# Brief — implementer, feature 29 `web_app`, **stage 1, fix round 2** (phase 16, full group: security) — scoped, approved by the maintainer after the second rejection

**Task:** close the stage 1 re-review's two items, and nothing else. The re-review is `progress/review_web_app.md` section "Stage 1 re-review (fix round 1)"; read **N1**, **The two disclosures** (B2b, B05) and **What must change before re-review**. The reviewer's driver and probes are in `.arm/web29r2/` (`armprod.sh`, the `R2_*` and `B05_*` arms, `probeW`); reuse them.

**Maintainer ruling (2026-10-15, at the gate after the second rejection):** a scoped fix round 2 with a short re-review of these items only. **No round 3:** anything new outside these items is carried to stage 2 as an acceptance item.

## What must change

1. **N1:** in `apps/web/src/server/routes/api/orders/stream.get.ts`, right after the close listener is attached (line 21 today), return without opening the upstream if the response is already destroyed: `if (res.destroyed) { res.off('close', onClientGone); return undefined; }`. The reviewer verified this by a temporary edit. Add the **same-tick disconnect** contract case: a raw socket writes the request and destroys at once, against a fake Gateway that never sends headers, and asserts no upstream connection is open within the bound. Run it **in-process and on the production build**. Arm it by deleting the line; the failure message must name the claim.
2. **B2b record correction:** in `progress/impl_web_app.md`, mark the fix round 1 paragraph about the post-await `res.destroyed` check as corrected in place. Before this round it was armable and load-bearing (reviewer arm `R2_B2b_check_deleted`: it leaked 3 of 3 without it). After N1's line it is defence in depth for a tick no test can drive; keep it, disclosed as unarmed, with that reason.
3. **B05:** add a cookie-less request carrying only the `x-otc_session-session` header to the test `R-session: h3's default session header (x-otc_session-session) is not an authentication path`. Arm it with the reviewer's `B05_header_fallback` mutation (`getCookie(...) ?? header`); it must fail by name.

## Process, bounds, output

- `CLAUDE.md`'s arming protocol (grep it on disk); backups in `.arm/web29s1r3/` with `sha256`; `cp` + `cmp`; rebuild after restore; `setsid --wait` with a process-group timeout; verdicts from a reporter artifact; never `pgrep -f`; leave no stray server (`ss -ltnp` before and after).
- Gates: `npx --yes pnpm@12.8.1 -C apps/web …` `install --frozen-lockfile`, `types:check`, `test:ci` (reconcile with 18 files / 251 tests), `build`.
- **Bounds:** `apps/web/src/server/**` and its tests, `apps/web/src/build/**` (the production contract), `progress/impl_web_app.md`. Nothing else; no git command that writes the index or working tree.
- **Output:** append **"Stage 1 — fix round 2"** to `progress/impl_web_app.md`: the change (file:line), the new tests, each arm (mutation, test, verbatim failure message, `sha256`, `cmp`), the B2b correction, gates. Return only "result in `progress/impl_web_app.md`" plus at most 3 lines.
