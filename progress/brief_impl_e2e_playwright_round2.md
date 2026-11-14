# Brief — implementer, feature 32 `e2e_playwright`, round 2 (after one Opus rejection)

**Input:** `progress/review_e2e_playwright.md` (verdict REJECTED; D-1, D-2 blocking; N-1 – N-5 non-blocking). Your round-1 brief `progress/brief_impl_e2e_playwright.md` still binds (bounds, arming protocol in the repo-root `.arm/`, `setsid --wait`, never touch `kb-poc-*`, no git writes, no commit). The leader set nothing; feature 32 is `in_progress` (the reviewer set it); you set `in_review` at the end, status line only.

**Verified by the leader this session:** `specs/shared/test-matrix.md:74` reads `| 3. \`order_saga_orchestrator\` | R19 – R29 | 11 | 10 | 0 | 1 |` (D-2 is real). No file under `apps/web/src`, `services`, `packages`, `tests` differs from HEAD.

**First, before anything else:** compare every `.arm/e2e32/` and `.arm/e2e32r/` backup of a file that still exists with its live file (`cmp`) and record the result.

## Fix (every finding is fixed in this phase)

- **D-1 (blocking).** Make `apps/web/e2e/order-detail-lost-frames.spec.ts` **need the backstop**: it must fail when **only** the backstop branch is deleted (the reviewer's arm: `order-detail.ts:137` returning `false`, with R55's pending retry left intact), and pass on the real code. Design it so the pending retry cannot rescue the page (read the reviewer's timing: 202 ≈ 0.5 s, pending retry ≈ 2.5 s, backstop's first read ≈ 7.5 s), and say how. Arm it **two ways, separately**: (a) only the backstop branch deleted → red, its message naming the backstop claim; (b) only the pending retry deleted → state what happens and why that is or is not this spec's business. Then correct every claim the reviewer listed as false — ledger row 2's guard half, the spec's title and header, record §3 and §9, the README line — so each says what the spec now proves. If you conclude the backstop cannot be isolated in a browser test, stop and say why with evidence; do not fall back to weakening the claims silently.
- **D-2 (blocking).** `specs/shared/test-matrix.md:74` → `11 | 11 | 0 | 0`. Then recount every group row and the Total from the Status cells with a command, and show the group rows sum to the Total. Column 3 stays byte-unchanged (show `git diff -U0` of the file).
- **N-1.** The ordering assertion passes with `stock.reserved.v1` substituted for the ordering index; only the `href` assertion catches it. Either make the ordering assertion itself fail on that substitution (preferred: anchor the index on the exact event type) and arm it, or correct the record to call the `href` assertion load-bearing. Say which.
- **N-2.** README: drop the non-existent `down -v`, and state truthfully how stock is restored (the seed only inserts what is missing).
- **N-3.** `stop_process` in `scripts/dev-stack.sh`: wait on the whole process group (no member alive), not only the leader, with the same bounded timeout and a kill of the group on expiry. Prove it with a probe whose child outlives its leader.
- **N-4.** The fail-fast hint names the `*_HOST_PORT` variable of the service that actually needs the held port.
- **N-5.** README asks for the same `POSTGRES_HOST_PORT` (any override) on every `up` and `down`; alternatively `dev-stack.sh` records the overrides it started with and refuses a mismatched later `up`. Say which.

## Verify

Cold `up` (with `POSTGRES_HOST_PORT=5433` unless 5432 is free — check `ss -ltn` first), **three consecutive green full-suite runs**, the arms above, `down`, and teardown evidence (`docker ps`, `ss -ltn`, process check: only what was up before). `./init.sh` green. `./quality.sh` only if you touched anything outside `apps/web/e2e/`, `playwright.config.ts`, `scripts/dev-stack.sh`, README, the matrix and the records (you should not). Append a "Round 2" section to `progress/impl_e2e_playwright.md` with start and end clock times; return only a short summary and the path.
