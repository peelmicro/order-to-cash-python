# Premise check — progress/brief_impl_web_app_stage1.md

VERIFIED   feature 29 has seven acceptance items — python count prints 7
VERIFIED   feature 29 is in_progress, sdd false — printed `in_progress False`
VERIFIED   item 4 = behavioural sweep; item 6 = ids 98,100,101,102,103,106 + stack label + WEB_PORT=3010; item 7 = backlog 201 — feature_list.json acceptance dump
VERIFIED   features 25 and 26 are done — gateway_rest_auth done, gateway_sse_push done
VERIFIED   backlog 201 exists — id 201 live_timeline_causation_names_commands_not_facts (done)
UNVERIFIABLE ids 98,100,101,102,103,106 as #8 ids — not features in this repo's feature_list.json (None); they are #8 backlog ids; not checked in #8 individually
VERIFIED   Analog 2.8.0 — apps/web/node_modules/@analogjs/router version 2.8.0, platform 2.8.0; package.json ^2.8.0
VERIFIED   Angular 22, h3 ^1.13.0 dependency, Vite 8, Vitest 5 — package.json: @angular/core ^22.0.0, h3 ^1.13.0, vite ^8.0.0, vitest ^5.0.0 (installed vitest 5.0.3)
VERIFIED   pnpm 12.8.1 in packageManager; global pnpm 11.22.0 — package.json:55 `pnpm@12.8.1`; `pnpm -v` 11.22.0
VERIFIED   Node 24.19.0 from .nvmrc — cat .nvmrc = 24.19.0
VERIFIED   quality.sh step 7 uses npx --yes pnpm@VER -C apps/web, install --frozen-lockfile, lint --if-present, test:ci, build — quality.sh:51-61
VERIFIED   build-script decisions with reasons in apps/web/pnpm-workspace.yaml — allowBuilds with a comment per entry
VERIFIED   apps/web/src/lib/currency-exponents.json exists; read by path at packages/shared_kernel/tests/test_currency_exponent.py:14 — sed -n 13,14p shows `WEB_JSON = REPO_ROOT / "apps" / "web" / "src" / "lib" / "currency-exponents.json"` at line 14
VERIFIED   openapi.yaml lines: /auth/login 110, /auth/me 146, /orders 163, /orders/{id} 297, /orders/{id}/cancel 342, /orders/stream 395, /stock 529, /stock/replenish 572, /invoices 613, /invoices/{id}/payments 664, /credits 765, catalog 802/829/856 — grep -n "^  /" matches all
VERIFIED   .env.example has GATEWAY_PORT=3001 and operator credentials — lines 243, 245-247
VERIFIED   SA-9 declared statuses — README.md registry row SA-9 (default responses on every operation)
VERIFIED   CLAUDE.md Environment notes carry the spartan/components.json gotcha — in project CLAUDE.md as loaded
VERIFIED   README has "Running the services" — README.md:140
VERIFIED   progress/current.md Notes has the restart command — current.md:25 `docker compose -p otcpy -f docker-compose.infra.yml start ...`
VERIFIED   Playwright Chromium cached — ls ~/.cache/ms-playwright: chromium-1234, chromium-1243
VERIFIED   #7 server utils {session,gateway,stream-proxy}.ts and stream-proxy.spec.ts — find output
VERIFIED   #7 has 15 route files under server/api — find ... | wc -l = 15; composition auth login/logout/session, catalog x3, credits, invoices index + [id]/payments, orders index.get/[id].get/index.post/stream.get, stock index + replenish
VERIFIED   #7 client files app/lib/{problem,order-stream-client,stack-label}.ts, composables/useSession.ts, middleware/, plugins/ — ls
VERIFIED   #7 progress/history.md line 1101 is the web_app (id 29) closure-review entry; the generic-error-text lesson ("every page's error text was silently generic ... field always undefined, four review passes walked past it") is in that entry (Notes for #8 and #9, line ~1120) — sed/grep
VERIFIED   #7 progress/{impl,review}_web_app.md exist — ls
VERIFIED   #8 commit 83223f1 "feat(web): Next.js web app with a BFF session..." — git log/show
VERIFIED   #8 BFF src/server/{session,gateway,stream-proxy}.ts, gateway-relay.test.ts — find/git show --stat
VERIFIED   #8 src/app/api/**/route.ts, route-handlers.test.ts, orders/stream/stream-route.test.ts — find (13 route.ts files plus tests)
VERIFIED   #8 src/lib/problem.ts, app/error-text-sweep.test.tsx, test/{page-sweep.tsx,fake-gateway.ts,gateway-fixtures.ts,session-cookie.ts} — ls
VERIFIED   #8 src/lib/stack-label.ts and app/stack-label.test.tsx — ls
VERIFIED   #8 .env.example:221-245 holds WEB_SESSION_PASSWORD, WEB_COOKIE_SECURE, WEB_PORT=3010 — sed 221,245p (WEB_PORT 243). Note: GATEWAY_BASE_URL is only described in the comment inside the range; its setting line is commented out at line 246
VERIFIED   #8 history.md line 2832 = "Backlog id 29 — web_app (phase 16): APPROVED at review round 4, after three rejections"
VERIFIED   #8 review_web_app.md has 1057 lines — wc -l
VERIFIED   #8 review B1 at line 23 — `### B1 — the place-order page's catalogue failure notice is a generic message`
VERIFIED   #8 B1 defended by test saying "only the failure matters here, not its words" — review line 29 quoting place-order-form.test.tsx:224
VERIFIED   #8 L1 at line 75; WEB_PORT=3000 in .env.example defeating WEB_PORT=3010 override — line 75 heading
VERIFIED   #8 RR2 D1 at 518, D2 at 550 (range 518-566 ends at the next section) — grep headings; syntax-guard defeats `if (isError) return`, `switch`, error.tsx at review lines 525-530
VERIFIED   #8 RR3-2 G-table at line 727 — heading `## RR3-2. Attacks on the sweep's own premises`
FALSE      "G1–G6 line 727" — table at 727-736 holds G1, G2, G3, G4, G6 only (grep -n "G5" review_web_app.md prints nothing); there is no G5
VERIFIED   #8 RR3 D1 at 786: login route's second call (/auth/me) dropped the problem body — review 786-800: line 58 `redirectToLogin(request, \`Sign-in failed (HTTP ${meResponse.status}).\`)`; login/route.ts calls POST /auth/login then GET /auth/me. Nuance: dropped only on the no-JS form path; the JS path relays
VERIFIED   #8 RR3 D2 (807) "never a generic message" not asserted; reviewed-literal label set both ways — lines 807-809, 830
VERIFIED   #8 RR3 D3 (811) populations on the wrong unit; G2-G4, G6 content as described — lines 811-821, 832-833 (range 786-822 covers D1-D3)
VERIFIED   #8 RR4 advisories A1 at line 1011 — `### A1 (advisory, outside the bullets): an expired session ... "Connection lost"`
VERIFIED   #8 RR4 reviewer killed a mutant clearing the cookie on every 4xx/5xx — review line 994 mutation U1x `relay clears on any status >= 400` fails 2/3 (a mutation of "status >= 400")
VERIFIED   #8 providers.tsx redirectOnSignedOut sends 401 to /login — providers.tsx:19-28
VERIFIED   #7 session uses h3 useSession; #8 uses iron-session-style sealData with sessionPassword() — #7 session.ts:2,29-32; #8 session.ts:5,36,47 (brief asks a question, so no claim)
UNVERIFIABLE "#7 field always undefined for the app's whole life" beyond the history note — only the closure note asserts it; code at the time is not checkable
UNVERIFIABLE "the Plan requires" production-build SSE testing — Plan is an external private document
UNVERIFIABLE "#8 reviewed ... did production build testing" not individually checked beyond tests-integration/stream-proxy.test.ts existing
UNVERIFIABLE "stage 2-4 scope", "Opus reviewer follows" — plan statements, not checkable
UNVERIFIABLE spartan generator output / TanStack Query pin — nothing exists yet (no components.json in apps/web)

Counts: VERIFIED 44, FALSE 1, UNVERIFIABLE 6
Verdict: DO NOT ACT (1 FALSE; it is the cosmetic "G1–G6", no G5 exists)
NOTED: none.
