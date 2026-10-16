# Brief — reviewer, feature 29 `web_app`, **stage 1 of 4** (phase 16, full group: security)

**Task:** approve or reject stage 1 of feature 29: the BFF, auth, the client shell, generated types and the error-text instrument. Its scope is in `progress/brief_impl_web_app_stage1.md` (*Must hold* A–D and the nine inherited findings); the implementer's record is `progress/impl_web_app.md` section "Stage 1" (301 lines; §13 lists the open points). The specification of record is `feature_list.json` id 29's acceptance items **1 and 2** in full, item **4**'s instrument (login page and shell as its population), and from item **6** the stack label and `WEB_PORT=3010`. Items 3, 5 (pages other than login), 7 and the inherited ids 98 (page half), 100–103, 106 are stages 2–4: **not grounds for rejection here.**

## Stopping rule (written by the leader before the review starts)

Reject only for: (a) a stage-1 *Must hold* item or inherited finding that is unmet, shown by a probe; (b) a live security or product defect in the stage-1 code, shown by a probe; (c) a guard the record claims as armed that does not fail when its claim is broken. Everything else — style, coverage shapes with no instance today, and anything stages 2–4 will build — is an **advisory** with a recommendation, not a rejection. Each finding names the unit (route, file:line, test, arm) and the probe that showed it.

## Inputs (on disk; the leader read the diff summary and §1–4, §11–13)

- Code: `apps/web/**` (BFF `src/server/**`; client `src/app/**`; `scripts/{openapi-types,serve}.mjs`; `src/generated/openapi.ts`; `src/build/production-bff.spec.ts`; `vite.config.ts`; `pnpm-workspace.yaml`). `git status` shows the full change set; the scaffold files it deletes are the Phase 5 template's.
- Leader edits this stage: `quality.sh` section 7 (`types:check`, two lines, by the implementer within bounds), `.env.example` new *Web app* section after the Gateway block (`WEB_PORT=3010`, `WEB_SESSION_PASSWORD`, `WEB_COOKIE_SECURE`, `WEB_GATEWAY_TIMEOUT_MS`, commented `GATEWAY_BASE_URL`), `init.sh` section 5 (`--exclude-dir=.arm`). Review these too: #8's L1 was a leader `.env.example` edit.
- Baselines: #7 `../order-to-cash-nestjs/apps/web/server/**`; #8 `../order-to-cash-dotnet/apps/web/src/{server,app/api}/**`, `src/app/error-text-sweep.test.tsx`, `src/test/page-sweep.tsx`; #8's four-round review `../order-to-cash-dotnet/progress/review_web_app.md` (your probes G1–G4, G6, D1–D3 at lines 518–566 and 727–822 are the attack shapes to re-try against #9's instrument).

## Probes the leader asks for (choose your own beyond these)

1. **Token custody.** Try to make the JWT reach the browser: any response body (including problem documents and the catch-all 404), any cookie that is not the sealed one, upstream `Set-Cookie` or other upstream headers relayed through `relay`/`proxyToGateway`, the SSE stream, a log line, the built client bundle, `index.html`. Session reading from a request header (h3's default, which §13 says is neutralised): prove it with a request. Anonymous requests must not mint a session.
2. **Proxy path integrity.** `/api/orders/{id}` and `/api/invoices/{id}/payments` with `..`, encoded slashes, `?`/`#` in the id, and query-string pass-through: can a browser request reach a Gateway path or query the BFF does not intend?
3. **Relay.** Status and problem bytes unchanged; cookie cleared on 401 only (both directions); BFF-local 401/502/504 problems in their own words; Gateway unreachable vs timeout distinguished.
4. **SSE proxy against the production build.** `Last-Event-ID` forwarded verbatim; a frame delivered while the upstream is open; upstream aborted within a bounded time after the client disconnects. Re-run at least the abort arm yourself.
5. **CSRF.** The `Origin` / `Sec-Fetch-Site` middleware goes beyond #7 and #8 (§13). Is it sound: what passes, and what does a legitimate same-origin browser POST look like? Recommend keep or remove, with the evidence.
6. **The instrument.** Re-try #8's G1 (generic text beside the problem text), G4 (a late request), G6 (a status-conditioned generic branch) and the D1 shape (a second upstream call) against #9's sweep. Judge the empty `LABELS`/`NOT_SHOWN` (§13): acceptable for stage 1, or a vacuous guard now?
7. **Arms.** Re-run a sample of the 62 arms of your choosing, at least one per group (BFF, client, port/types, build), plus every arm behind probes 1, 3 and 4. A re-run arm must fail with a message naming its claim.
8. **Gates.** Section 7's commands (`npx --yes pnpm@12.8.1 -C apps/web …`: `install --frozen-lockfile`, `types:check`, `test:ci`, `build`) once; reconcile the Vitest count with §11 (18 files / 236 tests).
9. **§13 open points:** SSR off, Nitro binding all interfaces, jsdom vs browser — one recommendation each.

## Process

- Read-only: you report, never patch. Arms follow `CLAUDE.md`'s protocol (grep it on disk): backups in `.arm/web29r1/` with `sha256`, restore by `cp` + `cmp`, rebuild `apps/web` after a restore where `dist/` could serve old code, every run under `setsid --wait` with a timeout that kills the process group, the verdict read from a reporter artifact. Arming never deletes or moves a tracked path. Wait on a PID, never on `pgrep -f`.
- The developer stack is stopped except `otcpy-n8n`. A live probe may start it (`progress/current.md` *Notes*) and the Gateway host; stop what you start (`docker ps` before and after). Nobody else is running tests now.
- Leave the tree as you found it: `git status --short` before and after, identical.

## Output

`progress/review_web_app.md`, section "Stage 1 review": verdict (APPROVED / REJECTED); findings under the stopping rule (blocking / advisory, each with unit, probe, verbatim output, recommendation); the arms you re-ran (mutation, test, verbatim message, `cmp`); the gate results; the §13 recommendations. Do not edit `feature_list.json`. Return only "result in `progress/review_web_app.md`" plus the verdict and at most 4 lines.
