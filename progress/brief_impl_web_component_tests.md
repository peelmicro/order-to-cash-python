# Brief — implementer — feature 30 `web_component_tests` (phase 17), LIGHT (test-only)

Classification: **light** (test-only; one implementer, the leader reads the diff and runs the tests; no reviewer). If you find a **product defect** (a test that fails on the real behaviour), STOP and record it in your file; do not fix source — the leader re-classifies.

## Inputs (read these, nothing broader)

- `feature_list.json` id 30: three acceptance items (do not edit `feature_list.json`; the leader is its single writer).
- `apps/web/src/app/lib/order-stream-client.ts`, `.../order-stream-client.spec.ts` (fake EventSource), `.../order-stream-client.eventsource.spec.ts` (real `eventsource` package over a real `node:http` server), `apps/web/src/app/testing/fake-event-source.ts`.
- #8's real-server cases: `../order-to-cash-dotnet/apps/web/src/lib/order-stream-client.test.ts` (whole file; the cases at lines ~156–235 are the ones #9 lacks). #7's: `../order-to-cash-nestjs/apps/web/app/lib/order-stream-client.spec.ts` (~line 201).
- Phase 16's note on Angular Testing Library: `progress/impl_web_app.md:269` (installed, then removed as "adds nothing over RouterTestingHarness").

## What the leader has already verified with a command this session

- Every page has component tests: `order-detail.spec.ts` (timeline: `R-detail`, `R-stream-live`, `R-conn`), `place-order.spec.ts`, `stock.spec.ts`, `billing.spec.ts`, `orders-list.spec.ts`; held-request loading tests exist (`R-list-states`, `R-stock-states`, `R-billing-states`, order-detail "while the read is in flight").
- `order-stream-client.eventsource.spec.ts` drops the first connection with `response.end()` (a **clean** close), not a forced socket destroy; its `onStatusChange` is a no-op. #8 and #7 both force the drop with `res.destroy()`.
- `grep -rln "@testing-library/angular" apps/web/src` → 0 files. `package.json` has `@testing-library/dom` 10.4.2 only. `npm view @testing-library/angular@latest` → 19.6.0, peers `@angular/core >= 21.0.0`, `@angular/router >= 21.0.0`, `@testing-library/dom ^10.0.0`; #9 is on Angular `^22.0.0`. #7 uses `@testing-library/vue`, #8 `@testing-library/react`. The feature title and CLAUDE.md name "Vitest + Angular Testing Library".

## Work

1. **Inventory first** (`progress/impl_web_component_tests.md`): for each of the three acceptance items, the tests that cover it, by file and test name, as a search result (the command and its output, one classification per hit). Then a **ported-guards table**: every `it(` in #8's `order-stream-client.test.ts` and in #7's `order-stream-client.spec.ts`, each classified as *ported (the #9 test name)*, *deliberately not ported (reason)* or *not applicable*. Count the population with a command (`grep -c "^\s*it(" <file>`).
2. **Forced mid-stream disconnect on a real server** (acceptance item 2), in `order-stream-client.eventsource.spec.ts`, keeping the existing clean-close test:
   - first connection: `stream.ready` resumed:false, a content frame with an id, a timeline frame with an id, a `ping` without an id, then **`res.destroy()`** (or `socket.destroy()`) mid-stream; the server may send `retry: 20` to pace the reconnect (the Gateway sends none; say so in a comment);
   - second connection: assert the `Last-Event-ID` it carries is the last CONTENT frame's id; the replay redelivers one already-applied frame plus a missed one;
   - assert: requests' `Last-Event-ID` list exactly `[undefined, <id>]`; each frame type's eventIds applied once each (literal expected arrays, distinct ids); `resyncs === 1`; the statuses include `reconnecting` and end at `connected`. Wait with a polling deadline, never a bare fixed sleep for the main condition.
3. **Two more real-server cases** that check the fake's premises (`FakeEventSource.drop()` = CONNECTING, `refuse()` = CLOSED): (a) repeated forced drops reach `gave-up` after N errors (pass N=3) and **no further connection is made** afterwards (count server connections at give-up, wait ~200 ms, unchanged; reconnecting counted exactly N−1); (b) a non-200 answer (401 `application/problem+json`) ends at `gave-up` with exactly one connection, never a retry loop.
4. **Angular Testing Library**: add `@testing-library/angular` **19.6.0** as an exact-pinned devDependency (pnpm 12.8.1 through `npx --yes pnpm@12.8.1 -C apps/web add -D -E @testing-library/angular@19.6.0`; if pnpm asks for a build-script decision, deny it in `pnpm-workspace.yaml` `allowBuilds` with a reason). Use its `render` + `screen` for genuine **component-level** tests of the standalone components that have none at that level: `src/app/components/pager.ts` (what it renders, Previous/Next enabled states, the click outputs) and `src/app/components/order-status-badge.ts` (each status's text). New files beside them (`pager.component.spec.ts`, `order-status-badge.spec.ts`) — do NOT rewrite the existing page tests. If ATL cannot render under this app's zoneless setup, record the exact error and stop that item (do not hand-roll a substitute).
5. **Stability**: run the stream file 20 times (`for i in $(seq 20); do ... vitest run src/app/lib/order-stream-client.eventsource.spec.ts || echo FAIL $i; done`) and record the tally. Any single failure is a finding: give the assertion a diagnostic message and report the mechanism, do not retry it away.
6. **Arming** (one arm per new test; light): back up into the ROOT `.arm/phase17/` (never `apps/web/.arm/`, never `/tmp`), `sha256` recorded, mutate `order-stream-client.ts` (e.g. drop the `readyState === CLOSED` give-up arm for 3b; make the `ping` listener not count / break per-type dedup for item 2; for the ATL tests, flip a pager `disabled` condition and a badge text), run the ONE test, record the failure verbatim, restore with `cp`, confirm with `cmp`, re-run green.
7. **Final runs**: from `apps/web`, `npx --yes pnpm@12.8.1 install --frozen-lockfile` then `npx --yes pnpm@12.8.1 run test:ci` and `npx --yes pnpm@12.8.1 run build`. Record file/test counts (Phase 16: 33 files / 668 tests) and the exit codes. Every run under `setsid --wait` with a timeout that kills the process group; wait on a PID.

## Bounds

- Edit only `apps/web/src/**/*.spec.ts`, new spec files, `apps/web/src/app/testing/**`, `apps/web/package.json` + `pnpm-lock.yaml` (+ `pnpm-workspace.yaml` only if a build decision is asked). No source under `apps/web/src` other than tests/testing helpers. No `feature_list.json`, no git command that writes the index or working tree, no commit.
- Ledger in your file: one line for the SSE resume idiom ("#7 relied on X (file:line); #8 supplied Y (file:line); in #9 it is supplied by Z, guarded by <test>") and one for the Testing Library.
- `Packages installed:` line in your file.

Return: a 5-line summary and the path `progress/impl_web_component_tests.md`.
