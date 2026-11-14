# Current session

**Feature:** none active. Next is phase 19 (Playwright end-to-end tests): `e2e_playwright` (id 32, `sdd: false`).
**Status:** Phase 18 is closed and committed at the full wrap-up (2026-11-14); Phase 19 has not started.
- **Feature 31** `api_tests` is **done**. It was approved at the Sonnet re-review (`progress/review_api_tests_round2.md`) after one Opus rejection (`progress/review_api_tests.md`, D1–D6).
- **Entries 217** (`mongo_container_ready_before_its_real_server`) **and 218** (`booted_predicate_fires_before_the_socket_listens`) are **done**: light, closed by the leader.
- Effort entries are in `progress/history.md` (the last three).

**Session started:** 2026-10-18 (Phase 18's work); wrap-up on 2026-11-14.

## Goal

Phase 18: feature 31's seven acceptance items. Done.

## Decisions taken this session

- **Acceptance item 7 (R61's API half) was added to feature 31 at dispatch.** The matrix named feature 31 as R61's closer, and the acceptance list did not carry it (#8 id 72's class). Five rows moved: R1 (scoped → green), R24, R48, R49 and R61. Matrix: **62 green / 0 scoped / 1 not yet green** (R28's e2e half, feature 32).
- **Two harness races were found while getting `quality.sh` green, and each was fixed in the phase:**
  - 217: `mongo:8.3.8` with root credentials logs "Waiting for connections" twice, 5.2 s apart, and testcontainers waits for the first;
  - 218: uvicorn logs "Application startup complete." before it binds the socket.
- **Review model.** The round-2 re-review ran on Sonnet, scoped to D1–D6, because every change was test or record only (the Opus reviewer's own recommendation).
- **Process.** The first implementer run was cut when the Claude Code process exited in the middle of an arm, and a test helper was left armed. The leader found it, by comparing every backup with `cmp`, before resuming. Lesson for later briefs: after any interrupted agent, compare every `.arm/*/backups` file with its live file before anything else.

## Blockers

None.

## Notes

**Committed:** see `git log`: 217, 218 and 31, one commit each, then this file's closing commit; pushed with `peelmicro`'s per-command token.

**Resume point.** The developer stack is down. `otcpy-n8n` crash-loops while the stack is down: it restarts for ever because it cannot resolve `postgres`. This is pre-existing; stop it, or start the stack. Check `docker ps` and `ss -ltn` first: another project's `kb-poc-*` containers held 5432 and 8080 during Phase 18, and its `llama-server` held about 7 of 16 cores.

**Brief for phase 19: Playwright end-to-end tests (Plan step 24).** One feature: **32** `e2e_playwright`, **`sdd: false`**, **four acceptance items**. Count them with `python3 -c "import json;print(len([f for f in json.load(open('feature_list.json'))['features'] if f['id']==32][0]['acceptance']))"`.
- **The four items:**
  1. an order reaches `completed` in the UI;
  2. a `.99` order reaches `cancelled` with its causal link visible (R28's e2e half: it flips R28, the last row not yet green);
  3. re-run against the composed stack in phase 23: a **carried** item. Its buildable half is now; the composed stack is feature 36's;
  4. the Chromium keystroke check carried from feature 29 stage 2, item 8: typing "19.99" and "0.29" into a cold `/orders/place` with a render lag shows and sends 1999 and 29; armed by restoring `[value]`, which must show 9919 and 290. Evidence: `progress/review_web_app.md`, `.arm/web29r3/s2r1/live/`.
- **Classification: full group?** Ask before dispatch; settle it by reading #8's choice. #8 ran it full (`../order-to-cash-dotnet/progress/history.md:3109`). It touches no `src/` if the app is right, so light may be defensible; decide with evidence, not by default.
- **Start from what exists:**
  - #8's `apps/web/e2e/{global.setup.ts,happy-path.spec.ts,compensation.spec.ts}` and `playwright.config.ts`, driven by `scripts/dev-stack.sh` (#8 had no composed stack until phase 23). #7's are the same three files.
  - #9 has **no** `scripts/dev-stack.sh` and no `@playwright/test` in `apps/web/package.json`; Chromium 1243 is cached in `~/.cache/ms-playwright`. Ask whether to port #8's script (the leader may write `scripts/`) or drive the stack another way. Read `npm view @playwright/test time` before naming a version (Phase 17's release-age lesson).
- **Baselines:**
  - #8: `../order-to-cash-dotnet/progress/history.md:3109`, about 1 h 23 min of agent work, approved first time with conditions C1/C2. Those were ledger rows false in both halves; ask for every row with a file and line.
  - #7: `../order-to-cash-nestjs/progress/history.md:1201`, rejected once for D1, a page that went stale after a lost SSE frame. Ask whether #9's order-detail page already carries #7's D1/D2/D7 fix, and where.
- **Inherited #8 findings to name avoided or recurred:**
  - #8 id 106: a label's `htmlFor` disagreeing with its `<select>` id, from a module-scope counter. Ask whether #9's place-order form has the shape.
  - #8 N1: each run consumes stock from one product; check the threshold.
  - #8 N2: the `install chromium` and `--with-deps` notes belong in README.
- **Process lessons carried:**
  - Integration suites pass with the developer infrastructure down. For e2e, which needs a stack, the brief states which stack, and a teardown leaves only what was up before.
  - Every run goes under `setsid --wait`, waiting on a PID.
  - Arm backups go in the ROOT `.arm/`.
  - **After an interrupted agent, compare every backup with `cmp` first.**
  - A test that fails once on a green tree is a finding until its mechanism is shown (both of Phase 18's harness races came from exactly that).
- **`quality.sh` time.** Phase 18: 5 288 pytest passed in 1 625.85 s (0.307 s per test, under the other project's load; Phase 17 was 0.161 s on a quiet machine); web 35 files / 687 tests.
- **Commits:** one per feature; an amendment is always on its own and before the code that depends on it.

---

## Template (reset to this on session close)

```markdown
# Current session

**Feature:** `<name>` (id <n>, phase <n>)
**Status:** <status>
**Session started:** <date>

## Goal

## Decisions taken this session

## Blockers

## Notes
```
