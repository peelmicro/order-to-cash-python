# Implementation — feature 30 `web_component_tests` (phase 17), LIGHT (test-only)

Status: finished, no product defect found. `feature_list.json` not touched (leader is the single writer).

## 1. Inventory of the three acceptance items (search results, `apps/web/src/app`)

Command: `grep -n "^\s*describe(\|^\s*it(" order-detail.spec.ts place-order.spec.ts` and `grep -n "describe(" stock.spec.ts billing.spec.ts`; `grep -c "^\s*it(" stock.spec.ts billing.spec.ts orders-list.spec.ts` gave `orders-list 9, billing 28, stock 27`.

**Item 1 — timeline, place-order form, stock and billing tables covered.** One classification per page:
| Page | File | Covering tests (describe names) | Class |
|---|---|---|---|
| timeline | `order-detail.spec.ts` | `R-detail`, `R55 (web half)`, `R-stream-live`, `SA-6 caused by`, `R-conn`, `#8 id 98` (11 `it`s from line 30 to 261) | covered |
| place-order form | `place-order.spec.ts` | `R-bytes`, `R-bad-input`, `R-typing`, `R-step`, `R-total`, `R-single`, `R-result`, `R-catalog-notice`, `R-label-id` | covered |
| stock table | `stock.spec.ts` | `R-stock-states`, `R-stock-rows`, `R-stock-name`, `R-stock-filters`, `R-replenish-*`, `R-stock-labels`, `R-typing` (27 `it`s) | covered |
| billing tables | `billing.spec.ts` | `R-billing-states`, `R-billing-money`, `R-billing-filters`, `R-payment-*`, `R-billing-labels`, `R-typing` (28 `it`s) | covered |
| (extra) orders list | `orders-list.spec.ts` | `R-list-states` (9 `it`s) | covered |
| (new this phase) components | `components/pager.component.spec.ts`, `components/order-status-badge.spec.ts` | below | added |

**Item 2 — SSE service, fake AND real server with a forced mid-stream disconnect.**
| Test | File | Class |
|---|---|---|
| 11 fake-EventSource tests (`R-dedup`, `R-resync`, `R-status`) | `lib/order-stream-client.spec.ts` | fake: covered |
| clean-close resume (`response.end()`, `retry` absent so the browser default 3 s) | `lib/order-stream-client.eventsource.spec.ts` "the second request carries the id of the last frame…" | real server, CLEAN close only |
| **forced `response.destroy()` mid-stream** | same file, "socket destroyed after a content frame, a timeline frame and a ping…" | **new: closes the gap** |
| repeated drops to gave-up, no further connection | same file, "repeated forced drops reach gave-up after N=3 errors…" | new |
| 401 problem+json, one connection | same file, "a 401 application/problem+json answer ends at gave-up…" | new |

**Item 3 — loading-state tests hold the request on an unresolved promise.** Command: `grep -n "in flight\|held.started" *.spec.ts`. Hits, all classified *held on an unresolved promise and asserts started*: `orders-list.spec.ts:25-29` (R-list-states), `stock.spec.ts:36-40` (R-stock-states), `billing.spec.ts:45-49,60` (R-billing-states, invoices and credits), `order-detail.spec.ts:54` ("while the read is in flight"), `place-order.spec.ts:191` (three catalogue requests, `started` toBe 3), `billing-order-link.spec.ts:88-98` ("lookup is in flight"). `login.spec.ts:83` and the R-payment-single / R-replenish-single hits are double-submit tests, not loading-state tests (not applicable). Unchanged by this phase.

## 2. Ported-guards table

Population: `grep -c "^\s*it(" <file>` gave `order-to-cash-dotnet/apps/web/src/lib/order-stream-client.test.ts: 7`, `order-to-cash-nestjs/apps/web/app/lib/order-stream-client.spec.ts: 5`. 12 rows.

| # | Source `it(` | Class | #9 test |
|---|---|---|---|
| 8-1 | `R51 — a redelivered order.updated … applied exactly once` (:77) | ported | `order-stream-client.spec.ts` "a redelivery of the SAME type with the same eventId is dropped…" |
| 8-2 | `seeded snapshot ids suppress a replayed frame of EITHER type…` (:117) | ported | "facts a fetched snapshot already holds are seeded for BOTH types…" |
| 8-3 | `stream.ready resumed:false asks the page to re-fetch; resumed:true does not` (:136) | ported | "resumed:false re-reads…; resumed:true does not" (fake) and, on a real server, the 2nd connection of the new forced-drop test (`resyncs === 1`) |
| 8-4 | `id 30 — a forced mid-stream disconnect is resumed with Last-Event-ID` (:156) | ported (this phase) | "socket destroyed after a content frame, a timeline frame and a ping…" |
| 8-5 | `gives up visibly after repeated failures, and stops reconnecting` (:195) | ported (this phase) | "repeated forced drops reach gave-up after N=3 errors…" |
| 8-6 | `a non-200 answer (e.g. a 401 problem) ends the stream as gave-up` (:214) | ported (this phase) | "a 401 application/problem+json answer ends at gave-up…" |
| 8-7 | `ignores malformed data without breaking the stream` (:225) | ported at fake level; deliberately not ported to a real server | "a malformed frame is ignored, not applied and not fatal". Reason: the guard is in `parse()`, which the transport cannot influence; a real-server copy executes the same lines |
| 7-1 | `R51 — a redelivered order.updated frame … exactly once` (:43) | ported | same as 8-1 |
| 7-2 | `order.updated then timeline.appended sharing one eventId are BOTH applied` (:86) | ported | "the two frames of one fact share an eventId: both are applied, once each" |
| 7-3 | `timeline.appended then order.updated … (reverse wire order)` (:132) | ported | "the reverse arrival order too…" |
| 7-4 | `resumed: false triggers onResync` (:180) | ported | same as 8-3 |
| 7-5 | `resumed: true does NOT trigger onResync, and a real reconnect (forced socket close…)` (:201) | ported (this phase) | same as 8-4 (it also asserts `reconnecting` in statuses and ends `connected`) |

Gap closed: #9 had only the clean-close real-server drop; #7 and #8 both force it with `res.destroy()`.

## 3. Ledgers

- **SSE resume idiom.** #7 relied on the browser-grade `EventSource` honouring `Last-Event-ID` after a forced `res.destroy()` (`order-to-cash-nestjs/apps/web/app/lib/order-stream-client.spec.ts:201`, `setTimeout(() => res.destroy(), 40)`); #8 supplied it with the same real `EventSource` plus `retry: 20` and `res.destroy()` (`order-to-cash-dotnet/apps/web/src/lib/order-stream-client.test.ts:156-193`); in #9 it is supplied by the `eventsource` 5.1.1 package (Node, fetch-based, `{ fetch }` option) over `node:http`, guarded by "socket destroyed after a content frame, a timeline frame and a ping…" (armed A1, A1c below) plus the unchanged clean-close test.
- **Testing Library.** #7 used `@testing-library/vue`, #8 `@testing-library/react` (both framework adapters, in `package.json`); Phase 16 installed `@testing-library/angular` then removed it as "adds nothing over RouterTestingHarness" (`progress/impl_web_app.md:269`); in #9 it is supplied by `@testing-library/angular` 19.5.0 (exact pin), used for `render` + `screen` on the two standalone components that had no component-level test, guarded by `pager.component.spec.ts` and `order-status-badge.spec.ts` (armed A4, A4b, A5). The existing page tests (RouterTestingHarness + `@testing-library/dom`) were left alone.

## 4. What changed

- `apps/web/src/app/lib/order-stream-client.eventsource.spec.ts`: 3 new tests plus helpers (`listen`, `waitUntil` with a lazy diagnostic message, `recorder`); the existing test is unchanged. Facts: first connection sends `retry: 20` (the Gateway sends none; commented), `stream.ready` resumed:false, an update with id `c-update-1`, a timeline frame with `c-timeline-1`, a `ping` with no id, then `response.destroy()` after 50 ms. Reconnect asserts `Last-Event-ID` list is exactly `[undefined, 'c-timeline-1']`; replay re-sends the already applied timeline frame plus a new update/timeline pair; `updates` = `[E1, E2]`, `entries` = `[E1, E2]`, `resyncs === 1`, statuses contain `reconnecting` and end `connected`. Gave-up test: N=3, connections at give-up exactly 3, unchanged after 200 ms, `reconnecting` counted exactly 2. 401 test: exactly 1 connection after 200 ms, no `reconnecting`.
- New `apps/web/src/app/components/pager.component.spec.ts` (6 tests) and `order-status-badge.spec.ts` (10 tests: the nine statuses via `it.each(ORDER_STATUSES)` plus a population assertion that they are the nine).
- `apps/web/package.json` (+ `@testing-library/angular` 19.5.0, exact), `pnpm-lock.yaml` (+17 lines). `pnpm-workspace.yaml` is unchanged from HEAD.
- No source file under `apps/web/src` other than specs touched (`git status --short apps/web/src`: 1 modified spec, 2 new specs).

Packages installed: `@testing-library/angular@19.5.0` (npm, devDependency, apps/web). No uv packages.

## 5. Requirement traceability (R-names are this repo's web-spec describe names, not `specs/shared` rows)

R55 resume with Last-Event-ID on a forced drop: the destroyed-socket test. Gave-up bound and no reconnection afterwards: the N=3 test. A refusal is final: the 401 test. Pager behaviour: the 6 component tests. Badge text: the 10 badge tests.

## 6. Stability (item 5)

`for i in 1..20: vitest run src/app/lib/order-stream-client.eventsource.spec.ts` under `timeout -k 5 120`: **pass=20 fail=0**. Load average (1 min) read after each run ranged 1.70 to 5.07 while the #7 and #8 test suites ran in parallel, so no failure to attribute to load. Each run is about 4.5 s (the old clean-close test waits the browser default 3 s reconnect).

## 7. Arming (backups with sha256 in `/home/.../order-to-cash-python/.arm/phase17/`: `client.ts bb9c0674...06a9`, `pager.ts e92a0aaf...1aff`, `badge.ts 0be43932...038c`; each restored with `cp`, confirmed with `cmp`, final `git status` shows the three source files unmodified)

| Arm | Mutation | Test | Failure (verbatim) |
|---|---|---|---|
| A1 | `seenTimelineEntryIds = this.seenOrderUpdateIds` (one shared set; defeat row 1/2) | socket destroyed… | `both timeline frames should arrive across the reconnect; requests=[null,"c-timeline-1"] statuses=[...]: expected false to be true` |
| A1c | delete `if (!data.resumed) this.callbacks.onResync();` | socket destroyed… | `only the first stream.ready said resumed:false: expected +0 to be 1` |
| A2 | remove the `consecutiveErrors >=` give-up | repeated forced drops | `should give up after 3 errors; connections=564 statuses=["connecting","reconnecting",...` |
| A2b | `>=` to `>` (off by one) | repeated forced drops | `one initial connection plus one per reconnecting error: expected 4 to be 3` |
| A3 | remove `readyState === READY_STATE_CLOSED` | 401 | `a refusal should end at gave-up; statuses=["connecting","reconnecting"]: expected false to be true` |
| A4 | pager Previous `current() <= 1` to `< 1` | pager component | `expected false to be true` and `expected [ false, true ] to deeply equal [ true, true ]` (2 failed) |
| A4b | pager Next `>= pages()` to `> pages()` | pager component | `expected [ true, false ] to deeply equal [ true, true ]` (2 failed) |
| A5 | badge template `{{ status() }}!` | badge | 9 failed, 1 passed (the population assertion) |

A first A1-A3 pass failed for the wrong visible reason: my `waitUntil` built the diagnostic message eagerly, before waiting, so it printed `connections=0 statuses=["connecting"]`. Fixed (message is a function, evaluated after the wait) and ALL arms were re-run on the final file; the table is from the re-run. Not armed: the "ping carries no id" half of A1 is a browser/`eventsource` behaviour, not a client one; the `[undefined, 'c-timeline-1']` assertion is the guard and would fail if the cursor were wrong, but no client mutation can change it (a test-side corruption of the frame id was not run).

## 8. Final runs (from `apps/web`)

- `pnpm install --frozen-lockfile`: "Lockfile is up to date", exit 0.
- `pnpm run test:ci`: exit 0, **35 files / 687 tests** (Phase 16: 33 / 668; +2 files, +19 tests = 3 + 6 + 10). Duration 525 s (the number-box guard specs dominate; not changed by this phase).
- `pnpm run build`: exit 0 ("server has been successfully built").
- `pnpm run typecheck` (`tsc --noEmit -p tsconfig.spec.json`): exit 0.

## 9. Surprises and things you could not or did not do

1. **ATL renders fine under the zoneless setup**; no error to record. `render(Component, { inputs, on })` worked as is.
2. **19.6.0 replaced by 19.5.0 (leader correction).** The brief pinned 19.6.0, published 2026-10-17T17:35Z (today), so pnpm added a `minimumReleaseAgeExclude` entry to bypass the release-age policy. Switched to 19.5.0 (published 2026-09-09, same peers): removed the exclude line, restored the lockfile from `git show HEAD:...`, re-ran `add -D -E @testing-library/angular@19.5.0`. `git diff -- apps/web/pnpm-workspace.yaml` is empty and no exclusion was asked. Re-run on 19.5.0: the two ATL files plus pager.spec pass (27 tests); arm A4 (pager `current() < 1`) fails again (`expected [ false, true ] to deeply equal [ true, true ]`, 2 failed) and restores (`cmp`); `install --frozen-lockfile` exit 0, `test:ci` exit 0 with 35 files / 687 tests, `build` exit 0.
3. **jsdom does not suppress a dispatched click on a disabled button** (`fireEvent.click` reached the Angular listener and emitted a page on a disabled Next/Previous), while `HTMLElement.click()` is inert as in a browser. The component tests use `.click()` for disabled buttons and say why in a comment. Existing page tests assert `.disabled` only, so none of them would have caught a disabled-but-firing button; not a product defect (a real browser blocks it).
4. `.arm/phase17/web7` and `web8` directories exist (other implementers' backups); I did not touch them.
5. No product defect found; no source edited.
