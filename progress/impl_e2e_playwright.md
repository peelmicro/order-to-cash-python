# Implementation record: feature 32 `e2e_playwright` (phase 19, `sdd: false`, full group)

Implementer: one session. Start 2026-11-14 07:21:21 CET (`date` at the first command). End: see "Quality gate" at the bottom. Machine load during every timing below: 7 to 14 (load average, 16 cores), the other project's `llama-server` and four containers of another session running alongside.

## 1. What was built

| Artifact | What |
|---|---|
| `scripts/dev-stack.sh` | `up`, `wait`, `status`, `down`, `rebuild-web`, `env <cmd>`. Infrastructure containers the services need, Alembic for the four databases, the seed, the six services as `uv run --no-sync` host processes, `vite build` then `serve.mjs preview`. Readiness on every `/health/ready`, PID file and log per process under `logs/dev-stack/`, stop by process group. |
| `apps/web/playwright.config.ts` | `testDir ./e2e`, `retries: 0`, `fullyParallel`, base URL `E2E_BASE_URL` else `WEB_PORT` else 3010, a `setup` project and a `chromium` project that depends on it. |
| `apps/web/e2e/global.setup.ts` | Real UI login once, `storageState` under `test-results/.auth/` (already git-ignored). |
| `apps/web/e2e/happy-path.spec.ts` | Item 1. |
| `apps/web/e2e/compensation.spec.ts` | Item 2 (R28's e2e half). |
| `apps/web/e2e/money-keystrokes.spec.ts` | Item 4 (two lag configurations). |
| `apps/web/e2e/place-order-labels.spec.ts` | #8 id 106 on the live DOM. |
| `apps/web/e2e/order-detail-lost-frames.spec.ts` | #7 D1/D2/D7 on the live app (added: see section 3, question 1). |
| `apps/web/e2e/tsconfig.json`, `package.json` | `typecheck:e2e` and `test:e2e` scripts and `@playwright/test` `1.64.1` (exact pin). |
| `README.md` | New section "End-to-end tests (Playwright)": usage, N2 notes, ports, stock. |
| `specs/shared/test-matrix.md` | R28's Status cell, line 83, the totals row. |

Added: `@playwright/test@1.64.1` (npm, dev dependency of `apps/web`; pulled `playwright` and `playwright-core` 1.64.1 with it, 3 packages in the lockfile). `pnpm add` asked for no `minimumReleaseAgeExclude` and no `allowBuilds` decision; `pnpm-workspace.yaml` is untouched (`cmp` against `.arm/e2e32/pnpm-workspace.yaml`: unchanged, `git diff` empty). `playwright install chromium` downloaded revision 1248 (headless shell 156.0.8078.4) and launched without a missing system library. No `--with-deps`, no `sudo`.

One bound stretched, and why: the brief allows "the one dependency and the script" in `package.json`; I added a second script, `typecheck:e2e`, because the question "is `e2e/` type-checked?" needs a mechanism or the answer is "no". Arm in section 5.

## 2. Decisions, with citations

1. **Item 1: #8's shape, ported** (place a non-.99 order, `invoiced`, payment through the billing UI, invoice `paid`, order `completed`). #8's file: `../order-to-cash-dotnet/apps/web/e2e/happy-path.spec.ts:19`. Adapted: #9 has no success banner, `place.page.ts:227` (`onSuccess` navigates to `/orders/<id>`), so the banner and `accepted-order-link` steps are gone. The final `completed` is asserted by the timeline holding `order.completed.v1` and then by the badge on a **reloaded** page (section 5, H2): #8's reviewer substituted `paid` for `completed` and the test still passed because a live badge passes through `paid`.
2. **Item 2: ported from #8 and #7** (`compensation.spec.ts`), strengthened: the causal link's `href` must be `#timeline-entry-<data-event-id of the stock.released.v1 entry>`, so the link names the entry, not a text that happens to read the same. The test title is #8's and #7's, not column 3's; column 3 is untouched, the Status cell cites the real file and test (as line 128's integration half already did). `init.sh` section 5d exempts `test-matrix.md`: `SPEC_FILES="$(find specs/shared -maxdepth 1 -type f ! -name test-matrix.md ...)"`, `init.sh:322`, with the comment at `init.sh:320-321` reading "test-matrix.md is EXEMPT by design". `init.sh` was run after the edit (section 8).
3. **Item 3:** `E2E_BASE_URL` else `WEB_PORT` else 3010 (`playwright.config.ts:12`; #8's `playwright.config.ts:20`; #7's `:17`). Proven by one green run with `E2E_BASE_URL=http://127.0.0.1:3010` **and** `WEB_PORT=3999` (a wrong value that would win if the variable were ignored): 6 of 6 passed, `.arm/e2e32/baseurl-green.log`; and the substitution arm (section 5, B1). The composed-stack run itself is carried to feature 36's last acceptance item.
4. **Item 4:** `money-keystrokes.spec.ts`. Mechanism ported from `.arm/web29r3/s2r1/live/keys.mjs`: an init script adds `lag` ms to every `setTimeout` and `requestAnimationFrame`, `keyboard.type` with a per-key `delay`, typing the moment the box is attached (`waitUntil: 'commit'`), cold page. Both configurations type both fields on one page. "Sends" is the request body Playwright observes (`page.waitForRequest` on the POST to `/api/orders`); the POST is answered 503 by `page.route` so the guard never places an order and never consumes stock. Everything else (session, catalogue) is the real stack's.
5. **`dev-stack.sh`, not `webServer`** (brief; #8 did the same, `playwright.config.ts` header). `.env` is **never sourced** (unlike #8's script, which `source`d `.env.example` and `.env`): `.env.example` holds `GATEWAY_OPERATOR_DISPLAY_NAME=Order-To-Cash Operator`, unquoted with a space, which a shell runs as a command. A small `envval` helper reads the caller's environment, then `.env`, then `.env.example`.
6. **Seeding.** The catalogue and stock come from `services/seed` (`python -m otc_seed`, `services/seed/README.md`: "the databases must be at head", idempotent, writes 3 currencies, 12 products, 7 retailers, 22 companies, 154 credit lines, 215 stock rows and six sagas). `dev-stack.sh up` runs the four `alembic upgrade head` and then the seed on every `up`. (`scripts/seed_parity.py` is #8-vs-#9 parity tooling, not the seed.)
7. **`OTEL_EXPORTER_OTLP_ENDPOINT` is left empty** unless the caller sets it. First `down` took 1 m 42 s: the services retried their OTLP export against the closed collector port (`logs/dev-stack/orders.log`: "Failed to export metrics batch due to timeout"). With it empty, `down` took 8.6 s (`.arm/e2e32/down1.log`, `down2.log`).
8. **Kept out of the stack:** Redpanda Console (nothing a service or the suite talks to; it is the only other service on a contested port, 8080), Mailpit, the observability stack, kafka-exporter, n8n (crash-loops alone, brief). Started: `postgres mongodb kafka nats kafka-init`.

## 3. Questions answered

**Postgres DSN and the port override.** Every service builds its DSN from `POSTGRES_HOST_PORT`: `services/orders/src/otc_orders/infrastructure/settings.py:29` (`port: int = Field(default=5432, validation_alias=AliasChoices("POSTGRES_HOST_PORT"))`), the same at `services/billing/.../settings.py:29`, `fulfillment/.../settings.py:27`, `notifications/.../settings.py:28`, and the seed at `services/seed/.../settings.py:36` (`validation_alias="POSTGRES_HOST_PORT"`). The container publishes `"${POSTGRES_HOST_PORT:-5432}:5432"` (`docker-compose.infra.yml:96`). So **one variable moves both**: measured, `POSTGRES_HOST_PORT=5433 scripts/dev-stack.sh up` gave `otcpy-postgres 0.0.0.0:5433->5432/tcp` and six healthy services. `REDPANDA_CONSOLE_HOST_PORT` (`.env.example:97`, `docker-compose.infra.yml:234`) is not needed: the console is not started. `dev-stack.sh` fails fast: with the defaults, `up` printed `[FAIL] port 5432 (needed by postgres) is held by container kb-poc-postgres-1 — set the matching *_HOST_PORT, e.g. POSTGRES_HOST_PORT=5433`, exit code 1, and started nothing (`.arm/e2e32/failfast.log`; `docker ps` unchanged).

**#7 D1/D2/D7 and #8's omitted ledger row C2.** #9's order-detail page carries the fix: `apps/web/src/app/lib/order-detail.ts:104-143` (`RefetchPlan`, `STALE_STATUS_BACKSTOP_MS = 5_000`; its comment names "#7 review D2/D7, ported by #8"), wired at `apps/web/src/app/pages/(app)/orders/[id].page.ts:178` (`refetchInterval: ... this.plan.interval(query.state.data)`) with `plan.noteRead()` in `fetchDetail`. The rule is unit-tested at `apps/web/src/app/lib/order-detail.spec.ts:25, 32, 41` (pending / live / becomes-terminal / opened-terminal). I found **no test that executes the page's wiring** (the six `it` titles of `src/app/order-detail.spec.ts` grep clean of backstop and refetch), so I added one, `order-detail-lost-frames.spec.ts`. **[Corrected in round 2, D-1: the version described here did not need the backstop, because R55's pending retry brought the status in at ~2.5 s, before the backstop's first read at ~7.5 s. The spec now proves the backstop branch alone; see "Round 2" at the end. What follows is the round-1 text, kept as history.]** Round 1 claimed: with the page's stream request held open and never answered, the order still reaches `invoiced`. Arm D1 deleted the wiring (`refetchInterval` returns `false`): the test failed, `element(s) not found`. Note the first version aborted the stream request instead; with the wiring deleted it still passed after 16.6 s, because the page's separate "gave-up" re-check (`[id].page.ts`, the second `effect`) refreshed it. The held-open request removes that path; a measured weakness of the first version, fixed.

**#8 id 106.** **Avoided.** `fieldId(line, field)` is one function (`place.page.ts:272`), used for every label `[for]` (`:132, 145, 152, 159`) and every control `[id]`; the key is the form's own `lastLineKey`, restarting at 1 per component instance (`place.page.ts` DraftLine comment and `lastLineKey`), no module state. Live DOM, four hard loads, all four fields (`.arm/e2e32/pairs.log`): every load read `Product: for=line-1-product -> id=line-1-product`, `Quantity: line-1-quantity`, `Unit price override: line-1-unit-price`, `Line discount: line-1-line-discount` (`label.control.id` equals `for` each time). `place-order-labels.spec.ts` asserts it in five loads (a `goto` each) plus a second line on the last; armed by substituting a sibling field in a `[for]` (B2).

**#8 N1 (stock).** Measured: ALBIONFOODS `PRD-0006` was `units 500` at the start. One full suite run consumes **3 units** of it (2 in the happy path, 1 in the silent-stream test): `450 -> 447` over one run (`PRD-0001` `523 -> 523`: the compensation order reserves and releases, net 0; the keystroke guard's POST is intercepted and places nothing). Threshold 20 (`lowStockThreshold`, `GET /stock`). It crosses at `(500 - 20) / 3 = 160` runs. Decision: **no top-up, the product stays** (nothing the suite asserts depends on stock; the runs are about 20 s, 160 of them in one database is possible but slow-burning, and the README gives the remedy; round 2 corrected it: a fresh `up` does NOT restore stock, the seed only inserts what is missing). The README says so and gives the remedy.

**#8 N2.** `playwright install chromium`, the `--with-deps`-needs-`sudo` note and the stack usage are in `README.md` ("End-to-end tests (Playwright)"), not only here.

**#8 C1 (ledger rows false in both halves).** Every row below cites the #7 and #8 file and line read in this session, and the #9 file and line. A row naming a guard names the test that executes it. Where a half is "none owed" it is cited as such.

**Vitest still collects 35 files / 687 tests?** Yes: `pnpm test:ci` with the e2e directory present: `Test Files 35 passed (35)`, `Tests 687 passed (687)`, 9 m 8 s under load (`.arm/e2e32/vitest.log`). Why: Vitest's `include` patterns (`apps/web/vite.config.ts:36`, `:51`) are `src/**`, `scripts/**` and `src/app/**` only. `e2e/` is type-checked by `typecheck:e2e` (`tsc --noEmit -p e2e/tsconfig.json`, includes `e2e/**/*.ts` and `playwright.config.ts`); the existing `typecheck` (`tsconfig.spec.json:12`) does not include it. Armed (section 5, T1). Playwright itself only transpiles.

**#8's backlog population** (command over `../order-to-cash-dotnet/feature_list.json`, case-insensitive regex `e2e|playwright|dev-stack|place-order|place_order|order-detail|order detail|refetch|htmlFor|label` over each feature's JSON):

| #8 id | name | Classification |
|---|---|---|
| 28 | saga_e2e_verification | not applicable to 32: API-level saga verification, #9's is feature 31 (done) |
| 29 | web_app | owned by #9 feature 29 (done) |
| 30 | web_component_tests | owned by #9 feature 30 (done) |
| 32 | e2e_playwright | this feature |
| 38 | final_checkpoint | owned by #9's final checkpoint feature |
| 87 | outbox_relay_deadlock_victim_escapes_run_once | not applicable (SQL Server deadlock victim); outbox is #9 feature 14 |
| 96 | gateway_ignores_gateway_port | applies to 32 as a start-up property: `dev-stack.sh` starts the Gateway with `python -m otc_gateway` (`.env.example`'s Gateway block cites #8 id 96) and `status` shows it on 3001; **avoided** |
| 98 | expired_session_on_a_finished_order_shows_connection_lost | owned by feature 29 (`[id].page.ts` "gave-up" effect cites #8 id 98) |
| 99 | web_apps_name_their_stack | owned by feature 29 (`login.page.ts` `data-testid="stack-label"`) |
| 106 | place_order_line_key_is_module_scope_mutable_state | applies to 32; **avoided**, proven live (above) |

Ten hits, ten classified.

## 4. Ported-idiom ledger

| # | Idiom | #7 relied on | #8 supplied it with | In #9 it is supplied by | Guard that executes it |
|---|---|---|---|---|---|
| 1 | Real login once, reused as `storageState` | `e2e/global.setup.ts:12, 37` and `playwright.config.ts:53` in `../order-to-cash-nestjs/apps/web/` (path `./e2e/.auth/`) | `e2e/global.setup.ts:22, 47`, `playwright.config.ts:59` (path `./test-results/.auth/`, so no extra `.gitignore` entry) | `e2e/global.setup.ts:8, 28`, `playwright.config.ts:40`; `.gitignore:45` `test-results/` | the `setup` project runs before every spec; every spec starts authenticated (all 7 runs) |
| 2 | An order page that cannot stay stale after a lost SSE frame | `app/composables/useOrderDetail.ts:112` (`refetchInterval`, D1/D2/D7) | `src/hooks/use-order-detail.ts:59-71` | `src/app/lib/order-detail.ts:114-143`, wired `[id].page.ts:178` | rule: `src/app/lib/order-detail.spec.ts:25,32,41`; backstop (the non-terminal branch of `RefetchPlan.interval`), end to end: `order-detail-lost-frames.spec.ts`, armed in round 2 by deleting only that branch (arm Da2: red, "the backstop: ..."; round 1's arm D1 deleted the whole interval and so did not isolate it); R55's pending retry: unit test only (arm Db, round 2: the spec stays green without it, by design) |
| 3 | Label and control name each other | #7 gave each branch its own STATIC id/label pair (`app/pages/orders/place.vue:317-328`, `id="retailer-input"` at `:345`), so it had no counter and no per-line label e2e proof | `place-order-form.tsx` `useId()` per `OrderLineRow` (comment `:67`), fixing id 106; its e2e still avoided the labels (`e2e/happy-path.spec.ts:44-63`, structural locator) | `place.page.ts:132,145,152,159` (`[for]`) and `:272` (`fieldId`), one function for both sides, component-scoped key | `place-order-labels.spec.ts` (armed B2); `happy-path.spec.ts` also drives Product and Quantity through their labels |
| 4 | Wait for the real `<select>`, not the fallback `<input>` sharing its label | #7 used distinct ids per branch (`place.vue:331` `retailer-select`, `:345` `retailer-input`), so the two did not collide on one id; its locators could differ | `e2e/happy-path.spec.ts:32, 41-42` (role `combobox`) | `place.page.ts:89` (`@if (retailersUsable())` else a text `<input id="retailer">`); the specs use `getByRole('combobox', ...)` | every spec that selects (`happy-path`, `money-keystrokes`, `order-detail-lost-frames`) and `compensation`'s explicit `toHaveJSProperty('tagName','SELECT')` |
| 5 | Place an order, then reach its page | `e2e/happy-path.spec.ts:46-60`: success banner, an "order list" hop (`:55`), then the order page | `e2e/happy-path.spec.ts:70-82`: banner, `accepted-order-link` | `place.page.ts:227-230`: `onSuccess` navigates straight to `/orders/<id>`; no banner. **Different shape, adapted** | `toHaveURL(/\/orders\/[0-9a-f-]{36}$/)` in four specs |
| 6 | Terminal or monotonic waits only | `e2e/happy-path.spec.ts:65, 100` (`invoiced`, `completed`) | `e2e/happy-path.spec.ts:90, 127`, same, 30 s | `invoiced`, `order.completed.v1` entry, reloaded `completed`, `cancelled`; `expect.timeout` 30 s in `playwright.config.ts:18` | the specs themselves; arm H1 (never pays) fails at the payment outcome, not on a transient |
| 7 | Causal ordering of the two compensation facts is a probabilistic e2e guard, the deterministic one is the API suite's | `e2e/compensation.spec.ts:14` (D4), `:80` (D3) | `e2e/compensation.spec.ts:26, 91` (ported verbatim) | `compensation.spec.ts` header (ported); the deterministic guard is `tests/api/api_support.py:172` `assert_causal_order`, exercised by `tests/api/test_black_box_api.py` | arms C1, C2 |
| 8 | Base URL from `E2E_BASE_URL`, falling back to `WEB_PORT` | `playwright.config.ts:17` | `playwright.config.ts:20` | `playwright.config.ts:12` | green run with both set, arm B1 |
| 9 | `retries: 0` | `playwright.config.ts:36` | `:40` | `:24` | 3 + 3 + 1 consecutive green runs, none retried |
| 10 | The stack the suite drives | #7: the containerised stack, `docker compose -f docker-compose.infra.yml -f docker-compose.apps.yml` (`../order-to-cash-nestjs/apps/web/playwright.config.ts:4-5`), `test:e2e` = `dotenv -e ../../.env -- playwright test` (`apps/web/package.json:17`) | `scripts/dev-stack.sh` (267 lines, `start`/`stop`, `dotnet run`, `next build`) | `scripts/dev-stack.sh` (`up`/`down`, `uv run`, `vite build` + `serve.mjs`) | the runs below; the fail-fast and pre-running arms (section 7) |
| 11 | Money keystrokes under a render lag | **none owed**: no `keyboard.type` or `19.99` in `../order-to-cash-nestjs/apps/web/e2e/` (grep, empty) | **none owed**: same grep over `../order-to-cash-dotnet/apps/web/e2e/`, empty | #9 only: `DraftValue` (`src/app/components/draft-value.ts`) replaces `[value]` on the three number inputs (`place.page.ts:146,153,160`) | `money-keystrokes.spec.ts` (armed A1, A1b) |

Python / Angular questions of CLAUDE.md, for this port: integer division, JSON serialisation, event-loop affinity and task cancellation do not enter an e2e suite of browser code; the money claim of item 4 is carried as exact integers on the wire (`toBe(1999)`, `toBe(29)`, never a float). Typing gaps: `postData()` is parsed as a typed shape and `unitPrice`/`lineDiscount` read through `Record<string, unknown>`, checked with `toBe` on numbers.

## 5. Inventory of #7's and #8's e2e assertions

`grep -c "expect("`: #7 `global.setup` 2, `happy-path` 14, `compensation` 15 (31); #8 `global.setup` 2, `happy-path` 13, `compensation` 14 (29); #9 `global.setup` 2, `happy-path` 15, `compensation` 16, plus 7 + 10 + the stream test (new files).

| Assertion (both #7 and #8 unless noted) | Class |
|---|---|
| setup: `toBeEnabled` on Sign in, `toHaveURL(/\/orders$/)` | ported |
| happy: banner visible, `ORD-\d+` reference present | **not ported**: #9 has no banner (`place.page.ts:227`); the reference is read from the order page's `order-detail-reference` and asserted `^ORD-\d{6}$` instead (adapted) |
| happy: `accepted-order-link` visible; URL `/orders/<id>`; #7's `/orders$` hop | adapted (URL kept; link and hop not ported, no such elements in #9) |
| happy: `invoiced` 30 s | ported |
| happy: invoice row visible (30 s) | adapted: filtered by reference through the order filter, `toHaveCount(1)` plus `issued` before paying |
| happy: payment form visible, submit enabled, accepted outcome, row `paid`, view-order link visible, `completed` | adapted: submit by role and name (the button has no test id in #9), row `paid` by the badge's test id, `completed` by timeline fact and reloaded badge (not the live badge) |
| compensation: running total `249.99`, submit enabled | ported |
| compensation: banner, link, URL | adapted as above |
| compensation: `cancelled` 30 s, `credit_rejected` | ported; `credit_rejected` read from `order-detail-cancellation` instead of `getByText` (precise) |
| compensation: both facts present (D3), release before cancel (D4), causation visible / contains `caused by` / link reads `stock.released.v1` | ported; the link's `href` added |
| #8 not in #7: none | |

New in #9: `money-keystrokes` (item 4, no precedent), `place-order-labels` (id 106), `order-detail-lost-frames` (D1/D2/D7's backstop branch, round 2), the reload-based terminal read.

## 6. Arms (every backup in `.arm/e2e32/` with `sha256`, restored by `cp`, confirmed by `cmp`)

Baseline `sha256`: `place.page.ts` `342dac5e06a4...` (also equal to `git` HEAD: `git status --short apps/web/src` empty at the end); `[id].page.ts` `247503c3aaa6...`. Spec backups `*.bak` next to the logs; each arm's full output is `.arm/e2e32/arm-<name>.log`.

Instrument for spec arms: `.arm/e2e32/arm.sh` (backup, one exact replacement asserted to occur once, run the one spec, restore, `cmp`). For `apps/web/src` arms the served app was rebuilt with `dev-stack.sh rebuild-web` after the arm and again after the restore, and a green full run followed.

| Id | Family | Arm | Result (verbatim, shortened) |
|---|---|---|---|
| A1 | delete the fix (item 4's fixed arm) | `place.page.ts`: `[appDraftValue]` back to `[value]` on the three number inputs (diff shown in `arm-A1.log`) | both tests failed: `expect(locator).toHaveValue(expected) failed ... Locator: getByTestId('unit-price-input') Expected: "19.99" Received: "9919"` (150 ms / 60 ms) and `Locator: getByTestId('line-discount-input') Expected: "0.29" Received: "290"` (60 ms / 40 ms). Matches the brief's 9919 / 290. |
| A1b | same, DOM assertions removed from the spec (so only the wire can fail) | spec arm on top of A1 | `Error: unitPrice on the wire is 1999 minor units Expected: 1999 Received: 991900` and `Error: lineDiscount on the wire is 29 minor units Expected: 29 Received: 29000`. The wire assertion alone catches it. |
| A2 | substitute a sibling identifier | `place.page.ts`: the Unit price label's `[for]` names `fieldId(line, 'quantity')` | `place-order-labels` failed: `Locator: locator('[id="line-1-quantity"]') ... Expected: "unit-price-input" Received: "quantity-input"` (the label named another field's control). `happy-path` passed with it (it does not use that label), as expected. |
| D1 | delete the behaviour (wiring) | `[id].page.ts`: `refetchInterval` returns `false` | `order-detail-lost-frames` failed after 31.1 s: `expect(locator).toHaveText(expected) failed ... Expected: "invoiced" ... Error: element(s) not found`. First version (aborted stream): passed in 16.6 s with the wiring deleted, so it was replaced (section 3). |
| H1 | delete the behaviour (the payment) | `happy-path`: the Submit payment click removed | `expect(locator).toBeVisible() failed ... getByTestId('payment-form').getByTestId('payment-outcome-accepted') ... element(s) not found` |
| H2 | substitute `paid` for `completed` (#8's reviewer's arm) | `happy-path`: the reloaded badge's expected text | `Locator: getByTestId('order-detail-status') Expected: "paid" Received: "completed"`. **The first design survived this arm** (live badge, polling, `paid` passed, as in #8: `.arm/e2e32/arm-H2-sub-paid-for-completed.log` is the later, failing run; the earlier passing run is described here only); the spec was then rewritten around the timeline fact and a reload. |
| H3 | substitute a sibling fact | `happy-path`: `order.completed.v1` -> `order.cancelled.v1` in the timeline filter | `getByTestId('timeline-entry').filter({ hasText: 'order.cancelled.v1' }) Expected: 1 Received: 0` |
| H4 | corrupt a supplied field | `happy-path`: invoice status expected `issued` after the flip (the assertion after payment) | `Locator: ... getByTestId('invoice-status') Expected: "issued" Received: "paid"` (the earlier version; the arm was run on the pre-reload spec, whose payment-flip assertion is unchanged) |
| C1 | substitute a sibling identifier (#8's reviewer's arm) | `compensation`: link text `stock.released.v1` -> `stock.reserved.v1` | `Locator: ...timeline-entry').nth(4).getByTestId('timeline-causation-link') Expected: "stock.reserved.v1" Received: "stock.released.v1"` |
| C2 | reverse the input (#8's reviewer's arm) | `compensation`: `(await readEventTypes()).reverse()` | `stock.released.v1 must be rendered BEFORE order.cancelled.v1, got ["order.cancelled.v1","stock.released.v1","credit.rejected.v1","stock.reserved.v1","order.placed.v1"]` |
| C3 | corrupt a supplied field | `compensation`: expected reason `stock_rejected` | `Expected: "stock_rejected" Received: "credit_rejected"` |
| C4 | corrupt the premise (the total no longer ends in .99) | `compensation`: unit price typed `249.98` after the fill | `getByTestId('running-total') Expected substring: "249.99" Received string: "249.98 EUR"` |
| C4b | same, the sanity line removed | | `getByTestId('order-detail-status') Expected: "cancelled" Received: "invoiced"` (a non-.99 order completes the saga; it never compensates) |
| B1 | substitute a sibling identifier (the base URL) | `E2E_BASE_URL=http://127.0.0.1:3999`, `WEB_PORT=3010` (the right one) | `page.goto: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:3999/login`; `1 failed, 5 did not run` |
| T1 | typecheck | `global.setup.ts`: `const STORAGE_STATE: number = '...'` | `e2e/global.setup.ts(8,7): error TS2322: Type 'string' is not assignable to type 'number'.`, exit 2; restored, `typecheck:e2e` silent |

Restores: `cmp` printed `RESTORED` after each (`place.page.ts`, `[id].page.ts`, every spec); at the end `cmp` of `place.page.ts` and `[id].page.ts` against their backups was clean and `git status --short apps/web/src` was empty. Spec files: `sha256sum e2e/*.ts` after the last arm is `.arm/e2e32/sha256-final.txt` (taken before the `order-detail-lost-frames` title edit; the title edit is the only later change).

**Defeat list, applied to my own guards** (which rows apply): 1 delete behaviour: A1, D1, H1, C4b. 2 corrupt a field: C3, H4, T1. 3 sibling identifier: A2, C1, H3, B1. 4 comment/string shadow: the keystroke and ordering guards assert DOM and wire values, not source text, so a comment cannot satisfy them; `arm.sh` asserts the replaced text occurs exactly once. 5 dead region: not applicable (assertions run in the live page). 6 raw string: not applicable. 7 drop an optional element: A1b (the DOM half dropped, the wire half still fails); the `href` assertion on the causal link is NOT optional: the reviewer's R3 (the ordering index taken from `stock.reserved.v1`) passed the ordering assertion and was caught only by `href`. Round 2 (N-1) added two assertions that the indexed entries have exactly the expected types, armed (arm N1). 8 literal to literal: avoided, every comparison is an observed value to an expected literal. 9 closer half satisfied, premise stale: H2's first design (live badge) is exactly this, fixed. 10 build output or caches: every `apps/web/src` arm was followed by `rebuild-web`, and the restore by a rebuild and a green run; `test-results/` is wiped by each Playwright run. 11 a form the instrument does not recognise: the test drives behaviour in Chromium, not syntax. 12 a path the population never drives: the silent-stream test's first version (the "gave-up" re-check) is this; fixed.

## 7. Run log and stack evidence

All under `setsid --wait timeout -k 10 N`, one stack at a time. `E` = `.arm/e2e32/`.

| Run | Result | Time (Playwright / wall) |
|---|---|---|
| First full run (6 tests) | 6 passed | 6.0 s / 10.2 s |
| `E2E_BASE_URL` explicit + wrong `WEB_PORT` | 6 passed | 9.1 s / 15.4 s |
| 3 consecutive, 6 tests (`runs.log`) | 6 passed x3 | 9.4, 9.9, 10.1 s / 16.4, 16.8, 17.5 s |
| 3 consecutive, 7 tests (`runs-final.log`) | 7 passed x3 | 12.3, 10.9, 12.4 s / 19.3, 18.4, 20.2 s |
| 3 consecutive, 7 tests, after the `dev-stack.sh` OTLP change and a fresh `up` (`runs-final2.log`) | 7 passed x3 | 13.0, 10.9, 9.9 s / 19.6, 16.6, 15.6 s |
| 1 more, for the stock measurement | 7 passed | 7.9 s |

`retries: 0` throughout. No failure on a green tree occurred; every red run in this record was an armed one. `dev-stack.sh up` took 51.7 s the first time, 59.4 s and 75.7 s later (load).

`dev-stack.sh` arms: (a) fail-fast on a held port (section 3). (b) **pre-running container:** `otcpy-nats` was started alone before `up`; `up` recorded `postgres mongodb kafka` as started by it (`logs/dev-stack/infra-started`); `down` stopped those three and `docker ps` still listed `otcpy-nats` (`.arm/e2e32/down2.log`); I then stopped it by hand to restore the pre-run state. (c) the first `down` returned with every port free but took 1 m 42 s; fixed (decision 7).

**Teardown at the end:** `dev-stack.sh down` (8 s), `docker ps`: only `kb-poc-api-1`, `kb-poc-storage-1`, `kb-poc-proxy-1`, `kb-poc-ai-1`, `kb-poc-postgres-1` **and four containers I did not start and did not touch** (`lucid_solomon` samba, `affectionate_beaver` mssql, `quirky_mestorf` versitygw, `zealous_brahmagupta` pgvector; another session's, absent at my first `docker ps` and listed with `Up 13`–`15 minutes` at the first `down`). `ss -ltn`: none of 5433, 9092, 4222, 27017, 3001, 3010, 8101-8105, 8222 listening. `pgrep`: no `otc_`, `uvicorn`, `serve.mjs` or `dist/analog` process outside the `kb-poc` container's own. No pid files. `docker ps -a --filter name=otcpy`: every `otcpy-*` Exited. One side effect to know: the `otcpy-postgres` container was **recreated** with the 5433 mapping (compose recreates on a changed port); its volume is intact, and a later default `up` recreates it again.

## 8. Quality gate

`./quality.sh` once, with the stack down, under `setsid --wait timeout`, log `.arm/e2e32/quality.log`, started 07:59:42: **exit 0, "quality.sh: all gates passed", 1 489 s**. pytest **5 288 passed in 940.79 s** (Phase 18: 5 288 in 1 625.85 s; no pytest test was added, the e2e suite is Playwright's), total coverage 96.38% (gate 60%), domain coverage step passed (gate 80%); web **35 files / 687 tests** passed (Phase 18: 35 / 687). `./init.sh` exit 0 afterwards (`.arm/e2e32/init.log`), stack down, no `otcpy-*` container running. End of work: 2026-11-14 08:25 CET (about 3 h 4 min wall, of which the quality gate and the one standalone Vitest run were 25 + 9 minutes of waiting).

## 9. Inherited findings

| #8 id | Verdict |
|---|---|
| 106 (label `htmlFor` vs control id) | **avoided**, proven on the live DOM and armed |
| 96 (Gateway ignores `GATEWAY_PORT`) | **avoided** (start-up through `python -m otc_gateway`; `status` and `/health/ready` on 3001) |
| C1 (ledger rows false in both halves) | every row cites a #7 and a #8 file and line read in the session, but row 2's guard half was false in round 1: **recurred (D-1), fixed in round 2** |
| C2 (omitted D1/D2/D7 row) | **avoided**: row 2 exists; its guard half is true as of round 2 |
| N1 (stock consumption) | measured and decided (section 3) |
| N2 (README gap) | **avoided** (README section) |
| #8's harness lesson (a stray `.env` source overriding the caller) | avoided differently: `.env` is never sourced |
| #7 D1 (stale page after a lost frame) | the property is avoided; **its guard recurred twice**: the first draft passed through the "gave-up" re-check (fixed in round 1), and the round-1 submission passed through R55's pending retry with only the backstop deleted (the reviewer's R1, D-1). Fixed in round 2: the spec now needs the backstop branch and fails without it (arm Da2) |

## 10. What I could not do, and what surprised me

- Feature 36's composed-stack run is carried, as briefed. I proved only that the base URL is configurable.
- The typecheck script and a fifth and sixth spec go beyond the brief's list; the reasons are in sections 1 and 3.
- **Surprises:** (1) `.env` cannot be sourced by bash (an unquoted value with a space). (2) The OTLP exporter makes `down` take minutes with no collector. (3) The first `invoiced` page-level guard passed with its own wiring deleted; only a held-open stream request isolates the interval. (4) The sibling-substitution `paid`-for-`completed` arm survived a live-badge assertion exactly as #8 recorded; a reload is what removes the transient. (5) Playwright removes `test-results/` (and with it the saved login) at the start of every run, so a script that reuses it must run after a full run.
- No app defect was found in `apps/web/src` or a service; nothing was stopped.

## Round 2 (after the Opus rejection; D-1, D-2 blocking, N-1 to N-5)

Start 2026-11-14 08:39:25 CET (07:39:25Z), end 2026-11-14 08:49 CET (07:49Z). Environment: `kb-poc-postgres-1` no longer publishes 5432, but I used `POSTGRES_HOST_PORT=5433` (the reviewer's setup) for every `up`, `down` and arm. Logs and backups: `.arm/e2e32r2/`.

**First, the backups of round 1.** `cmp` of every `.arm/e2e32/` and `.arm/e2e32r/` backup of a file that still exists against its live file: identical for `compensation.spec.ts` (C1, C2, C3, C4, C4b), `happy-path.spec.ts` (`.base2`, H2, H3, and the reviewer's `e2e32r/happy-path.spec.ts.bak`), `money-keystrokes.spec.ts`, `global.setup.ts.T.bak`, `place.page.ts` (e2e32 and e2e32r), `[id].page.ts`, `order-detail.ts` (e2e32r) and `e2e32r/compensation.spec.ts.bak`. **Two differ, expected:** `happy-path.spec.ts.H1-delete-payment.bak` and `.H4-corrupt-invoice-status.bak` (and `e2e.bak/happy-path.spec.ts`) are snapshots of the PRE-reload version of the spec, taken before round 1's rewrite (`diff` shows only the terminal-wait block that the reload design replaced); H2, H3 and `.base2`, taken after, are identical to the live file. `order-detail-lost-frames.spec.ts` has no backup that equals it, as it is rewritten here (`lost-frames.spec.ts.base` is the round-1 version).

### D-1: the lost-frames spec now needs the backstop

Why the old spec passed without it (the reviewer's timing: `202` at ~0.5 s, R55's pending retry at ~2.5 s returning `invoiced`, the backstop's first read at ~7.5 s): its page was opened straight after placing, so its FIRST read was a `202 projection_pending`, and that branch's retry rescued it. **New design (`apps/web/e2e/order-detail-lost-frames.spec.ts`, 3 steps):**

1. A second page of the same context places the order and waits for `invoiced`. So the order is projected before the page under test ever reads it: its first read is a `200 invoiced`, a NON-terminal document, never a `202`. **The pending branch has nothing to retry, so it cannot rescue the page.**
2. The page under test (stream request held open and never answered, as before) opens that URL, shows `invoiced`, and its connection badge is not `connected` (premise asserted).
3. The second page registers the payment through the billing UI and waits for the invoice to be `paid`. The silent page, never reloaded and never navigated (`page.url()` is asserted unchanged), must reach `completed`. A `200` with a non-terminal status is answered by exactly one branch of `RefetchPlan.interval`: the backstop. The final assertion carries a message naming that claim. The title and header were rewritten to say so.

Three consecutive green full-suite runs on the cold stack: `.arm/e2e32r2/run1-3.log`, each `7 passed` (10.0 s, 9.7 s, 9.6 s); the lost-frames spec took 8.0 s, 7.8 s and 7.6 s, i.e. one backstop period (5 s) plus the saga.

| Arm | Change (one, asserted to occur once) | Result |
|---|---|---|
| **Da / Da2** (a) only the backstop branch | `order-detail.ts:137`, `return this.backstopMs;` -> `return false;` (the pending branch untouched); `rebuild-web`, spec run, restore by `cp`, `cmp` ok, `rebuild-web`. Da ran before I added the message to the final assertion, Da2 after | **RED both times**, after 32 s: Da2 `Error: the backstop: a silent page showing a NON-TERMINAL status (invoiced) must re-read the order on its own timer and reach completed ... Expected: "completed" Received: "invoiced" Timeout: 30000ms` (`arm-Da2.log`). It names the claim. Reviewer's R1 passed 3 of 3 against the old spec; this one fails against the same arm. |
| **Db** (b) only the pending retry | `order-detail.ts:114`, `if (data.kind === 'pending') return data.retryAfterMs;` -> `return false;` | **GREEN** (`arm-Db.log`, 7.5 s). Why that is by design and not this spec's business: by construction the spec's page never reads a `202`, so R55's pending retry is not on its path. I also ran `happy-path.spec.ts` under the same arm (`arm-Db-ctl.log`): green too, so **no browser spec in this suite guards the pending retry**. Its guards are the unit tests (`order-detail.spec.ts:10-16, 25`) and the projector and API halves of R55 (`test-matrix.md`); the README and this record no longer say otherwise. |

Corrected claims, each now saying what the spec proves: the spec's title and header; ledger row 2's guard half (section 4); section 3's D1/D2/D7 paragraph (marked corrected, round-1 text kept as history); section 9's #7 D1, #8 C1 and #8 C2 rows (C1 **recurred** in row 2's guard half, fixed here; the guard of #7 D1 recurred twice); section 4's defeat-list row 7 (see N-1); the README line (`the order page's backstop re-read ...`). The stock note is unchanged in size: the spec still places 1 unit (default quantity), so a full run consumes 3 units of `PRD-0006`.

### D-2: the coverage summary

`specs/shared/test-matrix.md:74` -> `| 3. \`order_saga_orchestrator\` | R19 – R29 | 11 | 11 | 0 | 0 |`. Recount, by command:

```
$ awk -F'|' '/^\| [0-9]/{r+=$4;g+=$5;s+=$6;n+=$7} END{print "SUM rows",r,"green",g,"scoped",s,"notgreen",n}' specs/shared/test-matrix.md
SUM rows 63 green 63 scoped 0 notgreen 0
```

The group rows (1, 2, 3, 4, 5, 6, 7, 8, 8.1 = 10, 8, 11, 8, 8, 5, 6, 6, 1) sum to 63 / 63 / 0 / 0, equal to the Total row. A second recount from the Status cells themselves (a Python script over the 63 `**R<n>**` rows): 63 rows, none whose Status cell contains `TODO`, `scoped` or `not yet`. Column 3 of every R-row is byte-identical to `git show HEAD:` (the script compared every column of every R-row: only R28 differs, and only in column index 5, its Status cell). `git diff -U0 specs/shared/test-matrix.md` shows four changed lines: line 74 (this fix), the Total row (round 1), the "Scoped rows" paragraph and R28 (round 1).

### N-1: the ordering assertion

**Fixed, not only reworded.** The reviewer's R3 (the ordering index taken from `stock.reserved.v1`) cannot be caught by the ordering comparison itself (a reservation also precedes the cancellation), so I added `expect(types[releasedAt]).toBe('stock.released.v1')` and the same for `cancelledAt`, naming the claim, before the ordering assertion. Arm N1 (R3's substitution exactly): `Error: the ordering index must point at the stock.released.v1 entry / Expected: "stock.released.v1" / Received: "stock.reserved.v1"`, failing at `compensation.spec.ts:58`, the new assertion, before reaching `href` (`arm-N1.log`). The `href` assertion stays and remains load-bearing for a different break (the link pointing at another entry). Honest limit: with the index right, the two new assertions are tautologies; they exist only to fail when the index is substituted.

### N-2, N-4, N-5 (README and `scripts/dev-stack.sh`)

- **N-2:** the README no longer mentions the non-existent `down -v` of the script. It says a fresh `up` does NOT restore stock (the seed inserts only what is missing and `down` never touches volumes), and gives `docker compose -p otcpy -f docker-compose.infra.yml down -v` (wipes every `otcpy` volume, including all four databases and Kafka's log) with the stack down, then `up`, or a replenish from the Stock page. I did not run the `down -v` (it would destroy the reviewer's and my own measured state and no other project's, but nothing needs it).
- **N-4:** `check_ports` now takes the service and its variable together (`postgres:POSTGRES_HOST_PORT`, `mongodb:MONGO_HOST_PORT`, `kafka:KAFKA_HOST_PORT`, `nats:NATS_CLIENT_HOST_PORT`, `nats:NATS_MONITOR_HOST_PORT`). Probe: `MONGO_HOST_PORT=7070 KAFKA_HOST_PORT=9094 POSTGRES_HOST_PORT=5433 scripts/dev-stack.sh up` with 7070 held by `kb-poc`'s versitygw (already listening before I started: it is in my baseline) and 9094 by a `python3 -m http.server` of mine: `up` exited 1 with `[FAIL] port 7070 (needed by mongodb) ... set MONGO_HOST_PORT to a free port (e.g. MONGO_HOST_PORT=7071)` and `[FAIL] port 9094 (needed by kafka) ... set KAFKA_HOST_PORT ...`; no pid file, no `infra-started`, no `otcpy-*` container running. I killed my own server (pid 898150, by exact pid) afterwards.
- **N-5: I chose the README, not a recorded-overrides refusal.** It now says: "Give every `up` and every `down` the same overrides", and why (a later `up` without the prefix would ask compose to recreate `otcpy-postgres` on 5432 under the running stack). Reason for not making the script refuse: that is new behaviour with its own failure modes (a stale record), and the README rule is the one the reviewer's own run of `down` already needed. If you want the refusal, it is a small follow-up.

### N-3: `stop_process` waits on the group

New `group_alive pid` (`kill -0 -- -pid`, falling back to the pid): `stop_process` sends `TERM` to the group, waits while ANY member lives, up to `STOP_WAIT_SECONDS` (default 30, unchanged), then sends `KILL` to the group. Probe (`.arm/e2e32r2/probe-n3.sh`, which extracts the real `group_alive` and `stop_process` from the script): a leader that exits on `TERM` and a child that ignores `TERM` (`sleep 300`, `trap "" TERM`), `STOP_WAIT_SECONDS=3`. **New:** `stop_process returned after 3s`, `group members left: 0`, the child gone. **Old logic** (`probe-n3-old.sh`: the same functions with `group_alive` reduced to the leader's pid, which reproduces the old loop): `returned after 0s`, `group members left: 1`, the `sleep 300` still alive (pid 844503; I killed it by exact pid). A first run of the old-equivalent was invalid (my `sed` was applied to the probe file, not to the extracted function): I noticed because it showed the same result as the new code, and re-did it. Separately, one `pkill -f "sleep 300"` I ran as cleanup in that same command was careless: a machine-wide pattern kill. It could in principle have matched a process inside another project's container; I checked afterwards (`docker ps`: the five `kb-poc-*` containers up, health `healthy`, up 24 minutes, unchanged) and will not do it again.

On the real stack, `down` (with the new function): exit 0 in 8 s, every one of the seven recorded process groups had 0 members left (`pgrep -g`).

### Verification

- Cold `up`: `POSTGRES_HOST_PORT=5433`, exit 0 (07:41 to 07:42Z, about 50 s). Three consecutive full-suite runs: `7 passed` each (above). `down`, then the fail-fast probe above.
- Teardown evidence (07:46 to 07:47Z): `docker ps` names identical to the baseline (`diff` empty: the five `kb-poc-*`); `ss -ltn` against the baseline: no port opened (the only difference during the probe was my own 9094, gone after the kill); processes `otc_|uvicorn|serve.mjs`: identical to the baseline (only kb-poc's own uvicorn, pid 714465); no pid files in `logs/dev-stack/`; `otcpy-*` containers are all `Exited`.
- `typecheck:e2e`: exit 0. `./init.sh`: exit 0. Spec files changed this round: `order-detail-lost-frames.spec.ts` (rewritten), `compensation.spec.ts` (two assertions). Everything else: `scripts/dev-stack.sh`, `README.md`, `specs/shared/test-matrix.md` (line 74), this record. I touched nothing under `services/`, `packages/`, `tests/` or `apps/web/src` (every `apps/web/src` arm was restored by `cp`, `cmp` ok, and the web rebuilt: `cmp .arm/e2e32r2/Db.bak apps/web/src/app/lib/order-detail.ts` identical; `git status --short apps/web/src` empty). `./quality.sh` was not run: nothing outside the allowed paths changed.
- Not run: the reviewer's R1-R5 other than by re-using R1 and R3 as Da2 and N1.
