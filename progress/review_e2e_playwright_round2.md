# Re-review (round 2): feature 32 `e2e_playwright` (phase 19, full group)

**Verdict: APPROVED.** Scope: D-1, D-2, N-1 to N-5 of `progress/review_e2e_playwright.md`, as fixed in round 2. Reviewer: Sonnet, one session. Start 2026-11-14T07:48:42Z, end 2026-11-14T07:52Z. Environment: `POSTGRES_HOST_PORT=5433` (5432 not free per `ss`), every run under `setsid --wait timeout -k`, logs and backup in `.arm/e2e32r3/`. Not re-run: `quality.sh` (no file outside `apps/web/e2e`, `scripts`, README, test-matrix changed; `git status --short apps/web/src services packages tests` empty before and after).

| Finding | Disposition | Evidence |
|---|---|---|
| D-1 | FIXED | `order-detail-lost-frames.spec.ts` green alone (7.6 s, `green1.log`). Arm: only `order-detail.ts:137` `return this.backstopMs;` -> `return false;` (pending branch intact, `diff` shown), `rebuild-web`: spec RED after 32.8 s, `Error: the backstop: a silent page showing a NON-TERMINAL status (invoiced) must re-read the order on its own timer and reach completed ... Expected "completed", Received "invoiced"` (`arm.log`). Restored from `.arm/e2e32r3/order-detail.ts.bak` (sha256 1682c5e5...), `cmp` ok, rebuilt. Spec design read: the order is placed and brought to `invoiced` on a second page, so the page under test's first read is a 200, never a 202; the retry branch cannot rescue it. Title, header, README line 254 now say "backstop re-read"; the record states no browser spec guards the pending retry (Db arm green, by design). |
| D-2 | FIXED | `awk` over the group rows: `SUM 63 63 0 0`; line 74 reads `11 | 11 | 0 | 0`. `git diff -U0` shows only line 74, Total, the scoped-rows paragraph and R28's Status cell (column 5) changed; column 3 untouched. |
| N-1 | FIXED | Substitution `indexOf('stock.reserved.v1')` for `releasedAt`: RED at `compensation.spec.ts:58` with `the ordering index must point at the stock.released.v1 entry / Expected "stock.released.v1" / Received "stock.reserved.v1"`. Restored, `cmp` ok. |
| N-2 | FIXED | README line 269 gives the real remedy (`docker compose -p otcpy -f docker-compose.infra.yml down -v`, stack down, then `up`) and says a fresh `up` does not restore stock. Line 131 still says "`down -v` wipes it" (generic, about the stack; harmless). |
| N-3 | FIXED | `stop_process` (`dev-stack.sh:164-185`) uses `group_alive` (`kill -0 -- -pid`), waits while any member lives, then KILLs the group. I re-ran `.arm/e2e32r2/probe-n3.sh` (leader exits on TERM, child ignores it): `returned after 3s`, `group members left: 0`, child gone. Real `down`: exit 0, "no process of this stack is left". |
| N-4 | FIXED (read) | `check_ports` takes `service:VAR` pairs; the hint is per service. Not re-probed by me (cosmetic); implementer's output recorded in the round-2 section. |
| N-5 | FIXED (README) | README line 266: "Give every `up` and every `down` the same overrides", with the reason. A README rule, not a script refusal; acceptable for a dev script. |

Final run: full suite `7 passed (10.0 s)` (`full.log`; lost-frames 8.0 s). Teardown: `down` exit 0; `docker ps` shows only the five `kb-poc-*` containers; no stack port listening (`ss` empty for 3010, 3001, 8101-8105, 5433, 9092, 4222, 27017); no `otc_` / `serve.mjs` process (the only `pgrep` hit was my own shell); no pid files. No `kb-poc-*` container touched.

**Ledger / inherited findings:** #8 C1 recurred in row 2's guard half in round 1 and is fixed and recorded as such in round 2; the property's guard is now armed against the exact branch it names. Nothing here is rooted in `specs/shared/`, so no `SA-n` or backlog entry is owed. The only `specs/shared` edit is `test-matrix.md` status cells (per-assessment part).

**Defects remaining:** none.
