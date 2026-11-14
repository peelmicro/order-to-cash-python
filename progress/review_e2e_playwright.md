# Review: feature 32 `e2e_playwright` (phase 19, `sdd: false`, full group)

**Verdict: REJECTED.** Two blocking defects: D-1, the added lost-frames spec does not run the backstop it says it guards, so ledger row 2's guard half is false (the #8 C1 class has recurred); and D-2, the coverage table's group-3 row was not updated, so its own rows add up to 62 / 0 / 1 under a Total of 63 / 0 / 0. Items 1, 2 and 4 are met and well armed, and item 3's buildable half is met. Both fixes are small. Feature 32 is set back to `in_progress` (only its status line changed).

Reviewer: Opus, one session. Start 2026-11-14T07:25:50Z (08:25:50 CET), end 2026-11-14T07:38:05Z. Machine load at the start: 0.31 / 0.85 / 2.11, much lower than during the implementer's runs.

## What I ran (verification, not repetition)

I did not re-run `./quality.sh`: no Python, `apps/web/src` or service file changed (`git status --short` shows the same 11 paths as the brief), and I found no reason to. I did not re-run the implementer's own arms either, apart from H2, which I re-ran because #8 failed on exactly that arm. Here is what I ran instead, each run under `setsid --wait timeout -k`, with logs in `.arm/e2e32r/`:

| Step | Result |
|---|---|
| Baseline before anything | `docker ps`: only the five `kb-poc-*` containers. **`kb-poc-postgres-1` no longer publishes 5432** (it shows `5432/tcp`, and `ss` lists no :5432), so the environment differs from the brief's. No `otcpy-*` container running, no `otc_` / `uvicorn` / `serve.mjs` process. |
| Fail-fast probe, a different family from the implementer's (two ports held, by a container and by a process) | `POSTGRES_HOST_PORT=5433 WEB_PORT=8080 MONGO_HOST_PORT=7070 scripts/dev-stack.sh up` exited 1 with `[FAIL] port 7070 (needed by mongodb) is held by an unknown holder ...` and `[FAIL] port 8080 (the web app) is held by container kb-poc-proxy-1`. `docker ps` unchanged; no pid file and no `infra-started` written. |
| Cold `up` (`POSTGRES_HOST_PORT=5433`) | exit 0 in 45 s. Every PID file names a session and process-group leader (`ps -o pgid=,sid=` equals the pid; each group has 2 members). `infra-started` = `postgres mongodb kafka nats`. |
| Full suite, first run on the cold stack | **7 passed (5.4 s)**, 9 s wall (`run1.log`) |
| Three more consecutive full runs | 7 passed (8.2 s), **7 passed (5.2 s) with `E2E_BASE_URL=http://127.0.0.1:3010 WEB_PORT=3999`** (item 3: the wrong `WEB_PORT` would have been refused), 7 passed (5.3 s) (`run2-4.log`) |
| A second `up` while the stack is running | every process `[SKIP]`, `infra-started` unchanged (no duplicates) |
| `down` | exit 0 in 8 s; `pgrep -g` finds no member left in any of the seven recorded groups |
| Teardown evidence | `docker ps` names identical to the baseline (`diff` empty: the five `kb-poc-*` containers). `comm` of `ss -ltn` against the baseline: no port opened. None of 5433/5432/27017/9092/4222/8222/3001/3010/8101–8105 listening. `pgrep`: only kb-poc's own uvicorn (pid 714465, there before I started). No pid files. No `otcpy-*` container running. |
| `./init.sh` | exit 0; 5d: shared spec byte-identical to #8 and #7 across 6 files, test-matrix exempt |
| `uv run lint-imports` | 13 kept, 0 broken |
| `tsc --noEmit -p e2e/tsconfig.json` | exit 0 |
| Jest / Karma / Jasmine in `apps/web/e2e`, `playwright.config.ts`, `package.json` | `grep -rln "jest\|karma\|jasmine"`: no hits (exit 1) |

## My probes (mutation families the implementer did not use)

Each one followed the arming protocol: a backup in `.arm/e2e32r/` with matching `sha256`, one exact replacement asserted to occur once, the one spec run, a restore by `cp` confirmed with `cmp`. After each `apps/web/src` arm, and again after its restore, I ran `dev-stack.sh rebuild-web`. At the end all four backups compare equal to their live files, `grep -rn "ARM e2e32r"` over `apps/web/src` and `apps/web/e2e` returns nothing (exit 1), and `git status --short apps/web/src` is empty.

| Id | Family | Arm | Result |
|---|---|---|---|
| R1 | delete **only the property the row is about** (the narrower version of the implementer's D1) | `src/app/lib/order-detail.ts:137`: the non-terminal branch of `RefetchPlan.interval` returns `false` instead of `this.backstopMs`. The `pending` branch (R55's retry) is left alone. | **`order-detail-lost-frames.spec.ts` PASSED 3 of 3** (2.9 s, 3.0 s, 2.9 s; `arm-R1-{1,2,3}.log`). See D-1. |
| R1 evidence | timing the reads the page makes, with the stream held open as the spec does (`scratchpad/reads.mjs`) | armed build | `420ms GET 202 projection_pending`, `2459ms GET 200 invoiced`, then no further read in 13 s. This also proves the arm was in the served bundle. |
| R1 evidence | same | restored build | `552ms GET 202`, `2569ms GET 200 invoiced`, `7567ms GET 200 invoiced`, `12587ms GET 200 invoiced`. The backstop exists, but it first fires at about 7.5 s, five seconds after the spec's assertion has already passed. |
| R2 | corrupt a field **on the wire only** (the DOM stays right) | `place.page.ts:355`: `wire.unitPrice = unitPrice + 1` | both keystroke tests FAILED: `Error: unitPrice on the wire is 1999 minor units / Expected: 1999 / Received: 2000` (`arm-R2.log`). The wire half is a real guard on its own, separate from the DOM half (the implementer's A1b showed the same from the other side). |
| R3 | substitute a sibling event type **in the ordering input** | `compensation.spec.ts`: `types.indexOf('stock.reserved.v1')` for `releasedAt` | FAILED, but **only on the `href`**: `toHaveAttribute ... Expected: "#timeline-entry-c6714be1-…" Received: "#timeline-entry-a35a6b14-…"` (`arm-R3.log`). The ordering assertion was satisfied by the wrong entry (reserved, index 1, comes before cancelled). See N-1. |
| R4 | re-run of #8's `paid`-for-`completed` substitution against the final spec | `happy-path.spec.ts`: the reloaded badge's expected text set to `paid` | FAILED: `Expected: "paid" / Received: "completed"` (`arm-R4.log`). #8's weakness is closed: the order does pass through `PAID` (`services/orders/src/otc_orders/domain/state_machine.py:35-36`), and the reload is what removes that transient. |
| R5 | does the keystroke guard place anything? | `PRD-0006` stock read through the BFF before and after `money-keystrokes.spec.ts` alone | `(437, 0)` before and after. The `page.route` 503 really does intercept the POST. |

## Defects

**D-1 (blocking): `apps/web/e2e/order-detail-lost-frames.spec.ts` does not run the D1/D2/D7 backstop it claims to guard, so ledger row 2's guard half is false.**

- **Where:** the spec's title (line 14, "still reaches invoiced **by its own backstop re-read**") and its header (lines 6–9, "every status change has to arrive by the interval's re-read"); `progress/impl_e2e_playwright.md` §4 row 2 ("wiring: `order-detail-lost-frames.spec.ts` (armed D1, fails with the wiring deleted)"), §3 ("#7 D1/D2/D7"), and §9 ("C2 avoided ... the missing page-level guard was added"); and the README sentence "the order page's recovery when its event stream is silent".
- **What happens:** the page's first read is a `202 projection_pending`. Its retry, at the Gateway's suggested interval (R55, the `pending` branch of `RefetchPlan.interval`), already returns `invoiced` at about 2.5 s, because the saga has rested by then. The backstop (`STALE_STATUS_BACKSTOP_MS = 5_000`, the non-terminal branch, which is the #7 D1/D2/D7 fix) first fires at about 7.5 s, after the assertion has passed. With that branch deleted the spec passed three times out of three (R1).
- **Why the implementer's arm missed it:** D1 made the whole `refetchInterval` return `false`. That also kills R55's pending retry, so the arm was too broad a unit and its failure did not name the claim. This is defeat-list row 12 (a path the population never drives), the same class the implementer found and fixed in the spec's first version (the "gave-up" re-check), now recurring through a second route.
- **Why it matters:** CLAUDE.md's ledger rule says "does the named guard execute the code the row is about?" Here it does not. The row is #7's rejection D1 and #8's condition C2, so a false guard in exactly this row is the inherited finding recurring, not being avoided. The *property* is supplied (`order-detail.ts:114-143`, wired at `[id].page.ts:178`, rule unit-tested at `order-detail.spec.ts:25,32,41`). The *end-to-end proof* the record claims does not exist.
- **What must change (either option):**
  - (a) Make the spec need the backstop. For example, keep the stream silent, let the page's first live read be a non-terminal status that only a later read can move on from (open the order page once the order is already `invoiced`, register the payment from another page or context, and assert that the silent page reaches `completed`). Arm it by deleting **only** the non-terminal branch, as in R1, and record a failure that names the backstop.
  - (b) Correct the claim everywhere it is made (the title, the header, ledger row 2, §3, §9, the README line) to say what the spec actually guards (R55's pending re-read on a silent stream), and state that the backstop branch is guarded only by the unit test.
  - (a) is recommended: it is about one spec, and #7 was rejected for exactly this property.

**D-2 (blocking): the coverage summary no longer adds up.**

- **Where:** `specs/shared/test-matrix.md:74` still reads `` | 3. `order_saga_orchestrator` | R19 – R29 | 11 | 10 | 0 | 1 | ``, while the Total row (line 81) was changed to `63 | 63 | 0 | 0`.
- **Evidence:** `awk -F'|' '/^\| [0-9]/{r+=$4;g+=$5;s+=$6;n+=$7} END{...}'` over the group rows gives `SUM rows 63 green 62 scoped 0 notgreen 1`.
- **My own recount of column 5:** a script over all 63 `**R<n>**` rows, tallying each Status cell's opening words with no filter, finds 63 cells and none containing `TODO` or "scoped". So 63 / 0 / 0 is right, and line 74 must read `11 | 11 | 0 | 0`. Column 3 and columns 1–4 of every row are unchanged against `git show HEAD:` (script: only row R28 differs, and only in column 5). R28's new Status cell cites a title that occurs literally in `compensation.spec.ts` (`grep -c`: 1).
- **Why it matters:** the brief asked for the totals to be recounted with a command. A Total that disagrees with its own rows is a countable claim that was never checked, and CLAUDE.md says "a number that does not reconcile ... is a finding". It is a one-line fix in the per-assessment part of the file.

## Conditions

None beyond D-1 and D-2.

## Non-blocking (N)

- **N-1:** R3 shows that the ordering assertion alone cannot tell `stock.reserved.v1` from `stock.released.v1`. Only the `href` assertion (`compensation.spec.ts:66-68`, the implementer's own strengthening) catches it. The record's defeat-list row 7 calls the `href` optional and not separately dropped. It is in fact the only guard against a `releasedAt` taken from the wrong entry, so keep it and say so in the record.
- **N-2:** `README.md`'s stock note says "or `down -v` and seed again", but `dev-stack.sh` has no `-v`. Also, the seed is insert-if-absent, so a fresh `up` does **not** restore stock. That is unlike #8's N1 observation; I read 437 units at the start of my session against the implementer's 450 → 447. Name the real command (`docker compose -p otcpy -f docker-compose.infra.yml down -v`, then `up`).
- **N-3:** `stop_process` (`scripts/dev-stack.sh:164-180`) waits on the group leader only and sends `KILL` only if the leader survives. A child that outlives its leader is left to the port-leak warning (`down` returns 1). This was not observed: `down` took 8 s and left no group member. Signalling the group with `kill -0 -- -$pid` in the wait loop would close it.
- **N-4:** the fail-fast hint always reads "e.g. POSTGRES_HOST_PORT=5433", even for mongodb (seen in my probe). Cosmetic.
- **N-5:** a repeat `up` without the same `POSTGRES_HOST_PORT` override would recreate `otcpy-postgres` on 5432 under a running stack. `check_ports` skips running containers and compose recreates a container whose port changed. The README asks for the same prefix on `down`; it should say the same for every `up`.
- **`typecheck:e2e`: accepted.** The brief asked "is `e2e/` type-checked?", and without a mechanism the honest answer was "no". The script is armed (T1) and green (`tsc` exit 0, my run). Note that it is not a gate: `quality.sh` runs `types:check`, `test:ci` and `build`, and neither `typecheck` nor `typecheck:e2e` (grep), so the existing `typecheck` script is equally manual. No change required.

## Items → tests (verified)

| Item | Test | Verified by |
|---|---|---|
| 1. order reaches `completed` in the UI | `happy-path.spec.ts` › `an order with a non-.99 total reaches completed, and the invoice explicitly flips to paid` | green ×4; R4 (paid for completed fails); implementer's H1/H3/H4 read |
| 2. `.99` → `cancelled` with the causal link (R28 e2e) | `compensation.spec.ts` › `a .99 order is cancelled with credit_rejected, ...` | green ×4; R3 (sibling type in the ordering input fails on `href`); implementer's C1–C4b read |
| 3. base URL for another stack (the run itself is carried to feature 36's last item, verified in the `feature_list.json` diff) | `playwright.config.ts:12` | green with `E2E_BASE_URL=http://127.0.0.1:3010 WEB_PORT=3999` |
| 4. keystrokes shown **and sent** | `money-keystrokes.spec.ts`, both configurations | green ×4; R2 (wire-only corruption fails with Received 2000); R5 (no order placed); implementer's A1 (9919/290) and A1b read |
| R28 Status cell | as item 2 | literal title match; column 3 unchanged (D-2 concerns the summary table only) |

## Ported-idiom ledger: citations spot-checked against the checkouts

Every #7 and #8 citation in rows 1–11 resolves to what the row says, read with `sed -n` this session:

- **Row 1:** #7 `global.setup.ts:12,37`, `playwright.config.ts:53` (`./e2e/.auth/`); #8 `:22,47`, `:59` (`./test-results/.auth/`).
- **Row 2:** #7 `useOrderDetail.ts:112` (`refetchInterval`, with `STALE_STATUS_BACKSTOP_MS` and D7 at 116–127); #8 `use-order-detail.ts:59-71`.
- **Row 3:** #7 `place.vue:317-328` (comment), `:331`, `:345`; #8 `place-order-form.tsx:67` (`useId()`), `happy-path.spec.ts:44-63`.
- **Rows 4–7:** #8 `happy-path.spec.ts:32,41-42`; #7 `:46,55,60,65,100`; #8 `:70,82,90,127`; #7 `compensation.spec.ts:14,80`; #8 `:26,91`.
- **Rows 8–9:** #7 `playwright.config.ts:17,36`; #8 `:20,40`.
- **Row 10:** #7 `playwright.config.ts:4-5`, `package.json:17`.
- **Row 11:** re-run of the "none owed" grep: the only hit is a session token inside #7's `e2e/.auth/operator.json` (a regex `.` matching digits), not a test. The claim stands.
- **#9 halves:** `place.page.ts:89,146,153,160,227-230,272`, `tests/api/api_support.py:172` (`assert_causal_order`, used at `test_black_box_api.py:114`).

**The one false half is row 2's guard column (D-1).**

## Inherited findings

- **#8 id 106: avoided.** `fieldId` is one function for `[for]` and `[id]`. I read the spec and the implementer's B2 arm; I did not re-arm it.
- **#8 id 96: avoided.** The Gateway runs through `python -m otc_gateway` and answers `/health/ready` on 3001 (my `up`).
- **#8 C2: avoided.** The row exists.
- **#8 C1: RECURRED** in row 2's guard half (D-1). The record's §9 must say so after the fix.
- **#8 N1:** measured. See N-2 for the restore remedy.
- **#8 N2: avoided** (README section).
- **#7 D1:** the property is avoided; its guard has recurred (D-1).

## CHECKPOINTS.md

**C1, the harness is complete:**

- [x] The files exist (`ls`).
- [x] `.claude/agents/` holds the seven agents. Model declarations are unchanged by this feature: four have `model:`, and leader, reviewer and spec_author state that they inherit.
- [x] `./init.sh` exit 0.

**C2, state is coherent:**

- [x] At most one `in_progress` (after my edit: 54 done, 6 pending, 1 in_progress).
- [x] Every status is valid.
- [x] Every `done` feature has tests (unchanged).
- [x] `progress/current.md` holds the Phase 19 brief.
- [x] No feature is `blocked`.

**C3, architecture** (no backend change):

- [x] `lint-imports` 13 kept.
- [x] No cross-service access.
- [x] Shared runtime unchanged.
- [x] No `otc_cqrs` in domain (unchanged).
- [x] `dependencies = []` (unchanged).
- [x] Money: the e2e asserts are integers (`toBe(1999)`); no domain change.
- [x] Every interaction classified (no new interaction).
- [x] No debug logging or context-free TODO in the new files.

**C4, verification is real:**

- [x] `quality.sh`: implementer's run, exit 0, 5 288 pytest, web 35/687. Not re-run (no backend or src change).
- [x] Domain tests pure (unchanged).
- [x] Integration tests on testcontainers (unchanged).
- [x] Coverage (implementer: 96.38%).
- [x] No Jest, Karma or Jasmine (grep, exit 1).

**C5, the session closed cleanly:**

- [x] No suspicious untracked files (`test-results/`, `dist/` and `logs/` are ignored).
- [ ] History entry with effort record: not written, because the feature is rejected.
- [x] `feature_list.json` true (`in_progress`).
- [ ] Human told: for the leader at close.
- [x] Claude did not commit.

**C6:** not applicable (`sdd: false`). The matrix box is covered under D-2.

**C7, second reuse:**

- [x] `specs/shared/` byte-identical to #7 and #8 except `test-matrix.md` (init 5d).
- [x] No deviation needing an SA-n. Nothing in this feature is rooted in `specs/shared/`, so no SA or backlog entry is needed.
- [x] The R28 id is #7's, and the e2e half proves its wording.
- [ ] Inherited findings accounted for: C1 is recorded as avoided but recurred (D-1).
- [ ] History effort record: not yet (rejected).

## What must change before re-review

1. **D-1:** strengthen `order-detail-lost-frames.spec.ts` so that only the non-terminal backstop can satisfy it, armed by deleting that branch alone, with the failure recorded verbatim. Or, failing that, correct every claim listed under D-1. In both cases, update ledger row 2 and §9 (C1 recurred, then fixed).
2. **D-2:** `test-matrix.md:74` → `11 | 11 | 0 | 0`, with the recount command and its output in the record.
3. Optional in the same pass: N-1 (record wording), N-2 (README remedy), N-5 (README prefix on every `up`).

Re-review scope: D-1's new arm (run, not read) and D-2's sum. The rest of this review stands unless those changes touch it.
