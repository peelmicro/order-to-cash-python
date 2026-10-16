# Review: feature 29 `web_app` (phase 16, `sdd: false`, full group: security)

## Stage 1 review

Reviewer: Claude (Opus 5.5), 2026-10-15. Inputs: `progress/brief_review_web_app_stage1.md` (stopping rule applied as written), `progress/impl_web_app.md` "Stage 1", `apps/web/**`, the leader's `.env.example` / `init.sh` / `quality.sh` diffs. Read-only: no source edited; `feature_list.json` not edited (feature 29 stays `in_progress`); `git status --porcelain` before and after identical (`diff` of the two snapshots: no output, "IDENTICAL"). `docker ps` before and after: `otcpy-n8n` only. I started no Gateway or developer stack: every live probe ran against the **production build** (`node dist/analog/server/index.mjs`) in front of a scratch fake Gateway on a loopback port. (A `nuxt dev` on 127.0.0.1:3000, started 07:19 from `~/Work/Projects/EdiEz/ediez-app-2024`, is not mine and was left alone.)

### Verdict: **REJECTED**

Five blocking findings under the stopping rule: two live security/product defects shown by probes (B1 CSRF bypass, B2 SSE upstream leak), and three guards claimed as armed that stay green while their claim is broken (B3 log guard, B4 inline generic text, B5 id traversal). B1 and B5 are one defect class (the BFF reads the raw path; Nitro/h3 routes on the decoded one), so one round can close both. Everything else stage 1 claims held under my probes: token custody, relay, 401-only cookie clearing, Last-Event-ID, lockstep frames, 502 vs 504, the 401 to `/login` path, G6, the D1 shape, stack label, port, types drift, production build.

### Blocking findings

**B1 (security, rule b + c). The CSRF middleware is bypassed by percent-encoding one character of the path.** `apps/web/src/server/middleware/csrf.ts:7` tests `getRequestURL(event).pathname.startsWith('/api/')` on the RAW URL, while h3's app handler routes on `_decodePath(...)` (`node_modules/h3/dist/index.mjs:1996,2148`). `/%61pi/stock/replenish` is not `/api/...` to the middleware, but it is `/api/stock/replenish` to the router. A browser does not decode `%61` in a path (WHATWG URL keeps it), so this is reachable from a page.
- Probe (`.arm/web29r1/probe1.mjs`, `probe2.mjs` (outputs `probe1.out`, `probe2.out`), production build, raw sockets):
  - `C path /%61pi/stock/replenish -> 200 upstream ["POST /stock/replenish"]` with `Origin: https://evil.example` (control `/api/stock/replenish` with the same Origin: `403`).
  - Login CSRF, as a cross-site urlencoded form would send it: `L login CSRF via /%61pi/auth/login: 200 {"authenticated":true,...} sets session: true` (headers `Origin: https://evil.example`, `Sec-Fetch-Site: cross-site`); control `L control /api/auth/login: 403`.
  - Same-site mutation with a `text/plain` (CORS-simple, no preflight) body: `L same-site place-order via /ap%69/orders: 599 reached gateway: true` (599 is my fake's "no route"; the request reached `POST /orders` with the bearer token).
- The record claims (§5 CSRF row, `R-csrf` test, B12-B14) "every non-read method under /api is refused when ..." and "login CSRF" refused; both are false today while `R-csrf` is green. The `Sec-Fetch-Site: same-site` refusal is the only defence against a sibling-subdomain attacker (SameSite=Lax sends the cookie there), and it is the one bypassed.
- Contributing premise, also false (`csrf.ts:12-13`): "The body is JSON read by `readBody`, which needs a JSON content type, so a cross-site `<form>` ... could not carry credentials". Probe: `C urlencoded login -> 200 ... upstream body: {"username":"operator","password":"x"}` (h3 `readBody` parses `application/x-www-form-urlencoded`), and `C text/plain body -> 200 upstream ct: application/json body: {"retailerCode":"A","x":"="}` (`proxyToGateway` forwards any body and forces `Content-Type: application/json`, `gateway.ts:36`).
- Must change: apply the check to every non-safe method regardless of path (there is no non-`/api` mutation to exempt), or test the decoded `event.path`; refuse a mutating request whose `Content-Type` is not `application/json` with the BFF's own 415 problem (this alone kills form/`text/plain` CSRF on every path); correct the `csrf.ts` comment; add the encoded-path (`/%61pi/...`, `/ap%69/...`) and urlencoded/`text/plain` cases to `R-csrf`, in-process and production, and arm them (delete the fix, see them fail by name).

**B2 (product, rule a + b). A client that leaves before the Gateway answers the stream's headers leaks the upstream connection forever.** `apps/web/src/server/routes/api/orders/stream.get.ts:16-33`: `upstreamAbort` is only wired to `res.on('close')` inside `pumpStream` (`stream-proxy.ts:49`), which runs after `await openUpstreamOrderStream(...)` resolves. If the client closes during that await, `close` has already fired when the listener is attached; then `res.write` on the destroyed response returns false and `pumpStream` waits on `drain`/`close` (`stream-proxy.ts:57`), neither of which will ever fire again.
- Probe (`.arm/web29r1/probe2.mjs`, production build; the fake Gateway answers `/orders/stream` headers 1500 ms after the request; the client destroys its socket at 300 ms):
  ```
  S3 upstream request arrived: true open 1
  S3 1000 ms after the client left (upstream headers at 1500 ms from request): upstream open = 1
  S3 2500 ms after the client left ...: upstream open = 1
  S3 5000 ms after the client left ...: upstream open = 1
  S3 8000 ms after the client left ...: upstream open = 1
  ```
  Control (client leaves after the first frame): `S2 abort after client close: upstream open = 0 after 10 ms`.
- Each leak holds a Gateway StreamHub subscription and a socket for the server's life. This is the ledger's own "engine-supplied vs hand-built cleanup" question answered incompletely: #8 tied the upstream to the request's `signal`, which exists from the first byte, so #8 had no pre-pump window (ledger row "SSE: client closes -> upstream aborted", `impl_web_app.md` §5). Must Hold A ("aborts the upstream on client disconnect within a bounded time") is unmet on this path.
- Must change: attach the abort to the request/response `close` before opening the upstream (and check `res.destroyed` after the await); add a contract case "client leaves before the upstream answers its headers: upstream aborted within the bound", run in-process and on the production build, armed by moving the listener back.

**B3 (guard, rule c). The log guard stringifies each console argument with `String()`, so a token inside an object is invisible to it.** `apps/web/src/server/bff.spec.ts:108`: `spies.flatMap((spy) => spy.mock.calls.flat().map(String))`. Node's console prints nested objects with `util.inspect`, so the token reaches the log while the guard sees `[object Object]`. The same coercion is at `bff.spec.ts:66` (`.join(' ')`).
- Arm R_B19 (mutation in `login.post.ts`: `console.error('gateway call', { headers: { Authorization: \`Bearer ${issued.accessToken}\` } })`, the commonest structured-logging leak): `bff.spec.ts -t "the JWT is in no log line"` gave **total 29, passed 1, failed 0**. The implementer's B19 (a string concatenation) is the one shape this guard can see.
- Must change: format captured calls as console does (`util.format(...args)`, or `util.inspect(arg, { depth: Infinity })` per argument), or capture `process.stdout`/`stderr` writes; re-arm with the object-argument mutation above. Consider asserting the production server's own output as well (`RunningServer.output()` is already captured).

**B4 (guard, rule c). "Never a generic message" is not enforced when the generic text shares the problem's text node.** `apps/web/src/app/error-text.sweep.spec.ts:127`: `labelled = texts.filter((text) => !text.includes(sentinelText) && ...)` exempts the whole node that contains the sentinel. Angular renders `Static {{ interpolation }}` as ONE text node.
- Arm R_G1inline (`login.page.ts:45`: `<p hlmAlertDescription>Something went wrong. {{ errorText() }}</p>`): `error-text.sweep.spec.ts -t "shows each action request's failure as that problem's own"` gave **total 25, passed 4, failed 0**. The separate-node shape is caught (R_G1node: `text beside the problem's words that is not a reviewed label: ["Something went wrong."]`), which is what C04 armed.
- This is #8's G1 re-tried with the plainest Angular form, and it matters for stage 2 directly: #8's reviewed labels were prefixes (`Could not load orders:` ... RR3-2), which in Angular will live in the same node as the problem text, so the label set can never be "checked both ways" with today's unit. The brief's own wording ("minus the text containing the sentinel") is where the unit came from; the claim (acceptance item 4, record §4 row 5) is broken regardless.
- Must change: for a node containing the sentinel, remove the sentinel and require the remainder (trimmed of whitespace and punctuation) to be empty or a reviewed label; arm with the inline mutation above.

**B5 (guard, rule c; low impact). An id of `..` reaches another Gateway path while "an id is path-encoded and can never reach another Gateway path" is green.** `routes/api/orders/[id].get.ts:8` and `routes/api/invoices/[id]/payments.post.ts:8` `encodeURIComponent` the router param, which h3 has already decoded (`%2E%2E` -> `..`), and `encodeURIComponent('..')` is `..`; `fetch` then normalises the dot segment.
- Probe (`probe1.mjs`, production build):
  ```
  P GET /api/orders/.. -> 200 | upstream: ["GET /"]
  P GET /api/orders/%2E%2E -> 200 | upstream: ["GET /"]
  P POST /api/invoices/../payments -> 200 | upstream: ["POST /payments"]
  P GET /api/orders/x%3Fy=1 -> 200 | upstream: ["GET /orders/x"]   (id truncated at the decoded '?')
  ```
  Encoded slashes are safe (`..%2Fstock` -> `/orders/..%252Fstock`). Impact today is nil: a browser normalises `..`/`%2E%2E` itself, and neither `/` nor `/payments` is a Gateway path (`grep -nE "^  /" specs/shared/openapi.yaml`, 17 paths). The test (`bff-contract.ts:256-264`) only tries encoded slashes.
- Must change: answer the BFF's own 400 problem for an id that is empty, `.` or `..`, or contains `/` or `?` after decoding; add `..`, `%2E%2E`, `.` and `x%3Fy` to the test.

Defect class B1/B5 enumerated (`grep -rn "getRequestURL\|event\.path\|getRouterParam\|\.pathname\|originalUrl\|node\.req\.url" src/server scripts`, tests excluded), 5 hits: `middleware/csrf.ts:7` (B1), `orders/[id].get.ts:8` (B5), `invoices/[id]/payments.post.ts:8` (B5), `lib/gateway.ts:109` (`getRequestURL(event).search` from the raw URL; the source of the `%3F` truncation, B5), `api/[...path].ts:9` (message text only, not a defect).

### Advisories (not grounds for rejection; each with a recommendation)

- **A1. A tampered or expired cookie mints a fresh empty sealed session.** `GET /api/auth/session` with `Cookie: otc_session=garbage` answers `{"authenticated":false}` and `set-cookie: otc_session=Fe26.2**...` (probe T3). No token is in it, so not a leak; the record's "anonymous requests must not mint" holds only for cookie-less requests. Recommend clearing an unreadable cookie instead of letting `useSession` mint one, and extending the "tampered cookie" test to assert no new session cookie.
- **A2. BFF-local 502/504 details disclose the internal Gateway URL to the browser** (`gateway.ts:57,60`): `"The Gateway at http://127.0.0.1:41737 could not be reached (fetch failed)."`. Inherited from #8 (`order-to-cash-dotnet/apps/web/src/server/gateway.ts:58`). Recommend keeping the URL in a server log line and out of the browser-facing detail.
- **A3. The late-request bound has a form the TIMERS scan does not know.** R_G4b: a request fired 2000 ms after the shell is constructed, via `AbortSignal.timeout(2000)`, with a generic error branch. All load-phase tests of `/orders` passed; it was caught only incidentally, because the sign-out action's run lasts long enough for the timer to fire inside it (3 failures, all `/orders | sign-out`). A page with no action would not catch it. No instance today. Recommend, in stage 2, recording the longest delay requested at run time (wrap `setTimeout`/`AbortSignal.timeout` in the harness) instead of widening the regex.
- **A4. `LABELS`/`NOT_SHOWN` empty.** Acceptable for stage 1: nothing can be stale yet. But `error-text.sweep.spec.ts:319-322` compares a literal to a literal (defeat row 8). Stage 2 must replace it with "every label is produced by some failing run", and arm the stale direction once B4's remainder check exists.
- **A5. `h3` is `^1.13.0`** while the BFF's security rests on h3 1.15.11 internals (`sessionHeader` default, `_decodePath`, cited by line). The lockfile pins 1.15.11. Recommend an exact pin, like the other runtime libraries this stage added.
- **A6.** The CSRF Origin check compares hosts, not schemes (`Origin https same host -> 200`). This is negligible, but it costs nothing to compare `new URL(origin).origin` with the request's own origin.

### Probes the leader asked for

1. **Token custody** (production build, `probe1.mjs`). Results:
   - The login body is identity only, and exactly one `Set-Cookie`, `otc_session`: `HttpOnly; Secure; SameSite=Lax`, `Max-Age=43200`.
   - The JWT (and each of its segments) is absent from: the login head and body, a proxied response's head and body, the catch-all 404, the upstream-401 relay, the SSE stream, `/`, `/login`, `/orders`, `/index.html` (no `ng-state`), and the server output.
   - Upstream `Set-Cookie`, `X-Auth-Token: <jwt>` and `WWW-Authenticate` are not relayed; only `content-type` and `x-correlation-id` came through, plus `Cache-Control: no-store`. The stream's upstream `Set-Cookie` is not relayed.
   - Anonymous requests set no cookie (T2). The `x-otc_session-session` header does not authenticate, with or without a garbage cookie (T4, T4b).
   - Caveats: B3 (the log guard) and A1.
2. **Path integrity.** See B5. Encoded slashes, `%23`, `%5C`, `%00`, `@host` and `http:%2F%2F` ids all stay inside `/orders/<id>`. GET query strings pass through raw (`/stock?a=1&a=2&page=%2F..`), as #8's routes did. POST query strings are dropped. `/api//orders`, `/api/orders/a/b` and `/api/catalog/../credits` get the catch-all 404 and make no upstream call.
3. **Relay.** Status and bytes are unchanged (R_B20c: corrupting `"code"` fails with `body is not the Gateway's document unchanged`). The cookie is cleared on a 401 only, guarded both ways (R_B06 `a 403 must not touch the session cookie`; R_B07 with the sibling status 418: `a 401 must expire the session cookie`). Live, timeout and unreachable are distinguished: `R timeout 504 ... "did not answer within 400 ms"`, `R unreachable 502 ... "could not be reached (fetch failed)"`.
4. **SSE against the production build.**
   - `Last-Event-ID` is forwarded verbatim, including an odd value (`"1755511234901-18 weird,id;=x"`, `verbatim: true`).
   - A frame arrives while the upstream is open.
   - The upstream is aborted 10 ms after the client leaves.
   - I re-ran the abort arm on the production build myself (R_B09p): `the upstream connection stayed open after the client left: still false after 3000 ms`.
   - The pre-header window leaks (B2).
5. **CSRF.** A legitimate same-origin browser `fetch` POST carries `Origin: http://<host>:<port>` and `Sec-Fetch-Site: same-origin` and passes (`C browser same-origin -> 200`). Cross-origin `Origin`, `Sec-Fetch-Site: same-site`, `Origin: null` and an `X-Forwarded-Host` spoof are refused. Recommendation: **keep the middleware**. It is the only defence against same-site (sibling subdomain) attackers, which SameSite=Lax does not stop. But it must be fixed as B1 says: apply it on every path, and require a JSON content type. If the maintainer prefers #7/#8's cookie-only stance instead, delete the middleware AND its claims; do not ship a bypassable one.
6. **The instrument.**
   - G1: caught as a separate node (R_G1node), not caught inline (B4).
   - G4: a late request at 800 ms is caught (R_G4a: `/orders: requests with no success body in page-sweep.ts: expected [ 'GET /api/orders' ]`). At 2000 ms via `AbortSignal.timeout` it is caught only incidentally (A3).
   - G6: caught (R_G6: `POST /api/auth/login -> 429 | detail | expected "sweep-...-3-detail" | shown instead: Too many attempts. Try again later.`).
   - D1 shape: caught (R_D1, #8's exact text: `POST /api/auth/login | upstream GET /auth/me answered 401 (detail) | body is not the Gateway's document unchanged: {... "detail":"Sign-in failed (HTTP 401).", ...}`).
   - Empty `LABELS`/`NOT_SHOWN`: acceptable for stage 1 (A4), but only once B4 is fixed. Without the remainder check, a label set cannot be checked at all.
7. **Arms.** 21 re-run (table below), covering every group (BFF, client, port/types, build) and every arm behind probes 1, 3 and 4, mostly as sibling or corrupt-field variants rather than the implementer's own mutations. 19 failed by name and 2 survived (R_B19 -> B3, R_G1inline -> B4). The backup `sha256` of every touched file equals the implementer's recorded digest (for example `346abce35953` for `login.post.ts`, `3013036166ae` for `stream-proxy.ts`). Every restore was confirmed with `cmp`.
8. **Gates** (`npx --yes pnpm@12.8.1 -C apps/web ...`, each under `setsid --wait timeout -k 10`):
   - `install --frozen-lockfile`: exit 0, "Lockfile is up to date".
   - `run types:check`: exit 0, `types:check OK — src/generated/openapi.ts matches a fresh generation from specs/shared/openapi.yaml.`
   - `test:ci` (vitest with a JSON reporter artifact): **18 files, 236 tests, 236 passed, 0 failed, 0 pending**. This reconciles with §11 file by file (openapi-types 4, serve 4, typecheck 1, api-client 7, app-config 1, error-text.sweep 25, problem 8, login 8, seam 3, session 15, stack-label 5, ui-components 6, production-bff 27, bff 29, boundaries 10, config 6, routes.sweep 75, generated-types 2).
   - `run build`: exit 0, `377 modules transformed`, `dist/client/index.html` has no `/src/main.ts`.
   - After the arms: the suite was re-run green (18/236/0), and `run build` re-run (exit 0) so `dist/` is built from the restored source. `dist/client/index.html` has no `ng-state` and no `/src/main.ts`.
9. **§13 open points.**
   - *SSR off*: keep. It removes the TransferState path, and the guard that catches a re-enable is armed (R_E01: `/ carries Angular transfer state`).
   - *Nitro binding all interfaces*: accept for now. The Gateway binds `0.0.0.0` as well (`.env.example:242`), so the BFF adds no exposure the Gateway does not already have. If the maintainer wants loopback-only, default `NITRO_HOST=127.0.0.1` in `scripts/serve.mjs` with an override.
   - *jsdom vs browser*: keep jsdom for the sweep (the full population, fast). Add a stage-4 Playwright smoke over every page, with Playwright as an `apps/web` devDependency rather than borrowed from #8's checkout.

### Arms re-run by the reviewer

Driver `.arm/web29r1/arm.py`, definitions `.arm/web29r1/arms.json`, log `.arm/web29r1/results.jsonl`. For each arm the driver:
- backed up the touched file into `.arm/web29r1/backup/<id>/` and recorded its `sha256`;
- applied one mutation, asserting its anchor occurs exactly once;
- ran one named test under `setsid --wait timeout -k 10 420 npx vitest run --project <p> <file> -t <name>`, reading the verdict from the JSON reporter's artifact;
- restored the file with `cp`, confirmed it with `cmp`, and cleared `node_modules/.vite` and `.angular`.

The two production arms rebuilt `dist/`, which was rebuilt from the restored source afterwards. No tracked path was deleted or moved.

| id | claim | mutation | test | result (verbatim, from the artifact) | sha256 (12) | cmp |
|---|---|---|---|---|---|---|
| R_B03 | JWT never in a body | login returns `accessToken` beside SessionInfo | bff.spec "login answers identity only" | `the login response body is not identity-only (it must carry no token field)` | 346abce35953 | identical |
| R_B04 | JWT in no readable cookie | `Set-Cookie: otc_tok=<jwt>` appended | same | `response header set-cookie carries the JWT` | 346abce35953 | identical |
| R_B05 | session header not an auth path | `sessionHeader: false` deleted | bff.spec "default session header" | `a sealed session in the x-otc_session-session header authenticated the request` | 5f4c734a4955 | identical |
| **R_B19** | JWT in no log line | `console.error('gateway call', { headers: { Authorization: 'Bearer <jwt>' } })` | bff.spec "the JWT is in no log line" | **SURVIVED: passed 1, failed 0** (B3) | 346abce35953 | identical |
| R_B06 | clear on 401 only | `status >= 400` | bff.spec "a 403, 409, 500 and 503 relay" | `a 403 must not touch the session cookie` | 5731f4a3e18b | identical |
| R_B07 | 401 expires the cookie | sibling status 401 -> 418 | same | `a 401 must expire the session cookie: expected '<no Set-Cookie header>'` | 5731f4a3e18b | identical |
| R_B20c | bytes relayed unchanged | corrupt field: `"code":"` -> `"code":"X` | routes.sweep "GET /api/stock ... relays" | `body is not the Gateway's document unchanged: {... "code":"XDOMAIN_ERROR" ...}` (2 failed) | 5731f4a3e18b | identical |
| R_B10c | Last-Event-ID verbatim | corrupt field: truncated at the first `-` | bff.spec "a frame reaches the client ..." | `expected '1755511234901' to be '1755511234901-18'` | 3013036166ae | identical |
| R_B11d | frame while upstream open | each write delayed 6 s | same | `no chunk containing "event: stream.ready" within 5000 ms; got ""` | 3013036166ae | identical |
| R_B14s | same-site mutation refused | only `cross-site` refused | bff.spec "R-csrf" | `{"Sec-Fetch-Site":"same-site"}: expected 200 to be 403` | 2e416a0927ad | identical |
| R_D1 | login's 2nd call relayed (#8 RR3 D1) | #8's text: `Sign-in failed (HTTP n).` for a refused `/auth/me` | routes.sweep "POST /api/auth/login ... relays" | `upstream GET /auth/me answered 401 (detail) \| body is not the Gateway's document unchanged` (2 failed) | 346abce35953 | identical |
| R_C14s | 401 -> /login | sibling status 401 -> 403 | session.spec "a query answered 401" | `expected '/orders' to be '/login'` | 9322f5746829 | identical |
| R_G6 | every declared status swept (#8 G6) | fixed sentence for 429 only | error-text.sweep "... own detail" | `POST /api/auth/login -> 429 \| detail \| expected "sweep-ce7510d057e0-3-detail" \| shown instead: Too many attempts. Try again later.` | 99c57dafb9cd | identical |
| R_G1node | never a generic message (#8 G1) | `<p>Something went wrong.</p>` beside the alert text | same | `text beside the problem's words that is not a reviewed label: ["Something went wrong."]` | 99c57dafb9cd | identical |
| **R_G1inline** | same claim, same node | `Something went wrong. {{ errorText() }}` | error-text.sweep "... own" (both variants, both actions) | **SURVIVED: passed 4, failed 0** (B4) | 99c57dafb9cd | identical |
| R_G4a | late request observed (#8 G4) | shell fires `GET /api/orders` at 800 ms | error-text.sweep "renders; its observed requests" | `/orders: requests with no success body in page-sweep.ts: expected [ 'GET /api/orders' ]` | e70a93d67db1 | identical |
| R_G4b | late request, 2000 ms, `AbortSignal.timeout` | as named, with a generic branch | whole error-text.sweep | caught only by `/orders \| sign-out` (3 failed; every load-phase test passed) (A3) | e70a93d67db1 | identical |
| R_D01s | WEB_PORT default 3010 | sibling 3011 | serve.spec "defaults to 3010" | `expected 3011 to be 3010` | de0f7217f9b1 | identical |
| R_D03c | types drift fails | corrupt field: `tokenType: "bearer"` | openapi-types.spec "passes against the real spec" | `types:check FAILED — src/generated/openapi.ts is stale ... first difference at line 629` | 3a4cec7c62ce | identical |
| R_E01 | no transfer state | `<script id="ng-state" type="application/json">` in index.html | production-bff "no transfer state" | `/ carries Angular transfer state` | 99487ae32256 | identical |
| R_B09p | client close aborts upstream, PRODUCTION | `res.on('close', onClientGone)` -> no-op | production-bff "closing the client connection aborts the upstream" | `the upstream connection stayed open after the client left: still false after 3000 ms` | 3013036166ae | identical |

### Leader edits reviewed

- `.env.example`: the new *Web app* block matches #8's `.env.example:221-245` setting for setting (`WEB_PORT=3010`, a 41-character dev `WEB_SESSION_PASSWORD`, `WEB_COOKIE_SECURE=true`, commented `GATEWAY_BASE_URL`), plus `WEB_GATEWAY_TIMEOUT_MS=15000`. `WEB_PORT=3010` equals the code default, so #8 L1 does not recur. The repository `.env` has no `WEB_*` line (`grep -n WEB_ .env` shows only `WEB_CONCURRENCY`, which `apps/web` does not read).
- `init.sh`: `--exclude-dir=.arm` excludes at the source, consistent with the rule beside it.
- `quality.sh`: `types:check` sits between `lint` and `test:ci`, and passes.

### CHECKPOINTS.md (boxes applicable to a stage review)

- [x] C2: at most one feature `in_progress` (`[29]`).
- [x] C3: no stray debug logging (`grep -rn "console\.\|TODO\|debugger"` over non-test source: the CLI messages in `scripts/openapi-types.mjs` and the intended warning at `config.ts:48`).
- [ ] C4: the web part of the gate passes (install, types:check, test:ci 18/236, build). Not ticked, because two of its guards are vacuous for the shapes in B3/B4. The full `./quality.sh` was not run (the leader runs it at the checkpoint).
- [x] C4: no Jest, Karma or Jasmine (`grep` of `package.json` returned no match; lockfile count 0).
- [x] C5: no suspicious untracked files (`dist/`, `.nx/` caches and `node_modules` are ignored; `git status` unchanged); Claude did not commit.
- [x] C6: n/a (`sdd: false`).
- [x] C7: `specs/shared/` untouched (`git status --porcelain specs/` is empty); the nine inherited findings are each classified in §4. I agree with "avoided" for 1, 2, 3, 4, 6, 7, 8, 9, and for 5 only partly (B4).
- [ ] C7 ledger: the SSE-abort row's claim is incomplete (B2). Re-check it when B2 is fixed.

### What must change before re-review

1. B1: CSRF on every non-safe method regardless of path, plus a JSON-only `Content-Type` for mutations. Correct the comment, add the encoded-path and form/`text/plain` cases, and arm them.
2. B2: wire the abort before the upstream is opened. Add the pre-header disconnect case, run it in-process and on the production build, and arm it.
3. B3: format logged arguments as console does. Re-arm with an object argument.
4. B4: the remainder check for sentinel-bearing nodes. Re-arm with the inline generic text.
5. B5: refuse `.`, `..`, `/` and `?` ids with the BFF's own 400. Add `..`, `%2E%2E`, `.` and `%3F` cases.

The re-review will re-run R_B19, R_G1inline, the probe1/probe2 cases quoted above, and each new arm. The advisories A1 to A6 are optional in this round. None is rooted in `specs/shared/`, so no SA-n or backlog routing is owed.

## Stage 1 re-review (fix round 1)

Reviewer: Claude (Opus 5.5), 2026-10-15. Brief: `progress/brief_review_web_app_stage1_round2.md`, with its stopping rule applied as written. Inputs: the fix brief `progress/brief_impl_web_app_stage1_round2.md` (nine items), `progress/impl_web_app.md` "Stage 1 — fix round 1", `apps/web/**`.

I was read-only. No source was edited except by the arm driver: backup, mutate, restore with `cp`, confirm with `cmp`. Every touched file's `sha256` after the run equals its backup: `stream.get.ts` a5721d77951a, `session.ts` faed02b628fc, `lib/csrf.ts` 46d21dcfd018, `middleware/csrf.ts` 11d4472522b5, `path-id.ts` 5c74dd073140, `gateway.ts` f60a7686b1c6, `payments.post.ts` ad5aed8b0a0b, `login.post.ts` 346abce35953, `login.page.ts` 99c57dafb9cd, `package.json` b33a104705e3. These equal the implementer's recorded digests.

`dist/` was rebuilt from the restored source at the end. The bundle has the original `if (res.destroyed || upstreamAbort.signal.aborted)` and `invoices/${encodeURIComponent(id)}/payments`, and none of the experiment text. `feature_list.json` was not edited; feature 29 stays `in_progress`.

`ss -ltnp` before and after: identical (`diff` of the local-address columns, "PORTS-IDENTICAL"). `git status --porcelain` before and after differs by exactly two untracked files that I did not write: `progress/brief_impl_web_app_stage2.md` and `progress/premise_impl_web_app_stage2.md`. The leader wrote them during this run.

Artifacts are in `.arm/web29r2/`: `arm.py`, `arms.json`, `results.jsonl`, `out_*.json`, `armprod.sh`, `probe3.mjs`, `probeW.mjs`, `probe{1,2,3}.out`, `R2_B2*.{diff,out}`, and `g*_*.log/json`.

### Verdict: **REJECTED**

One item is unmet, shown by a probe (rule a): **item 2 (B2)**. The fix is one line, plus one contract case. The other eight items are met, and every guard I armed for them failed by name.

### N1 (blocking, rule a). The pre-header leak is still there when the client leaves before the route attaches its listener.

`apps/web/src/server/routes/api/orders/stream.get.ts:12,21`. The `close` listener is now attached before `openUpstreamOrderStream`, but still after `await readSession(event)` (line 12, which unseals with webcrypto). If the client goes away during that await, `close` has already fired, the listener never runs, and the upstream fetch is opened with a signal that nothing will ever abort. This is B2's own mechanism, a listener attached after an await, moved one await earlier.

The post-await `res.destroyed` check (line 35) releases the upstream only when the Gateway answers its headers. If the Gateway never answers, the upstream connection stays open for the server's lifetime. The implementer's own pre-header contract case uses exactly that fake: "the Gateway accepts the request and never answers its headers".

That contract case waits for the upstream request to arrive before it destroys the client (`bff-contract.ts:497`), so it only drives the window after the listener is attached. This is defeat row 12.

Probe: `.arm/web29r2/probe3.mjs`, run on the production build. The client is a raw socket that writes the request and calls `destroy()` in the same tick. The upstream connections still open after 300 / 1000 / 2000 / 3500 ms:
```
W slow-headers, client destroys in the same tick it sends: upstream arrived=true open 300ms:1 1000ms:1 2000ms:0 3500ms:0   (x5)
W never-headers, client destroys in the same tick it sends: upstream arrived=true open 300ms:1 1000ms:1 2000ms:1 3500ms:1  (x5)
```
The leak was deterministic: 5 of 5 runs, and 3 of 3 more in each experiment below.

Practical impact is low against a healthy Gateway, because it answers the stream's headers at once and line 35 then releases the upstream. It is unbounded against a Gateway that stalls. The ask in item 2 was "upstream aborted within the bound", and here the bound is the Gateway's header latency.

The fix is one line and was verified by experiment (`.arm/web29r2/armprod.sh R2_B2fix_candidate`: backup `sha256` a5721d77951a, production rebuild, `cmp` identical after restore). Insert after line 21:
```ts
  if (res.destroyed) { res.off('close', onClientGone); return undefined; }
```
With it, the upstream is never opened:
```
W slow-headers ...: upstream arrived=false open 300ms:0 1000ms:0 2000ms:0 3500ms:0   (x3)
W never-headers ...: upstream arrived=false open 300ms:0 1000ms:0 2000ms:0 3500ms:0  (x3)
```
The test to add, in-process and on the production build: "a client that leaves in the same tick it sends the request: no upstream connection stays open", using a raw socket that writes then destroys, and the never-headers fake. Arm it by deleting the new line.

### Item by item

| # | item | met? | probe (verbatim, production build unless noted) | arms (mine; verdict from the JSON reporter artifact) |
|---|---|---|---|---|
| 1 | B1 CSRF on every path, 415, comment, cases | **met** | `L login CSRF via /%61pi/auth/login: 403 {... Sec-Fetch-Site is \"cross-site\" ...}`; `L same-site place-order via /ap%69/orders: 403 reached gateway: false`; `C path /API/stock/replenish -> 403 upstream []`, `C path /%61pi/stock/replenish -> 403`; `C text/plain body -> 415`, `C urlencoded login -> 415`; probe3: `PUT /api/orders {Origin evil, text/plain} -> 403`, `Content-Type "text/plain; application/json" -> 415`, `"application/json, text/plain" -> 415`, `"application/jsonx" -> 415`, `POST /API/orders text/plain -> 415`, same-origin JSON `-> 200`. Comment at `lib/csrf.ts:15-18` is now correct | R2_B1_reqUrl (in-process; sibling form of the original defect, gate on raw `event.node.req.url`): `/%61pi/stock/replenish {"Origin":"https://evil.example"}: expected 200 to be 403`. R2_B1_reqUrl_prod: same message. R2_B1_textplain_allowed (in-process): `text/plain order: expected 201 to be 415`. R2_B1_urlencoded_prod: `urlencoded login: expected 200 to be 415` |
| 2 | B2 SSE pre-header abort | **UNMET (N1)** | round 1's S3 case is fixed: `S3 1000 ms after the client left ...: upstream open = 0` (also 2500/5000/8000); `S2 abort after client close: upstream open = 0 after 11 ms`. The leak remains for a same-tick disconnect (N1) | R2_B2_listener_late (in-process; listener moved after the await, check kept): `the upstream connection stayed open after the client left before the upstream answered its headers: still false after 3000 ms`. R2_B2b_check_deleted (production, probe): see B2b below |
| 3 | B3 log guard sees objects | **met** | `LOG jwt in server output: false` | **R_B19 (round 1's surviving arm, re-run): now fails**: `a log line carries the JWT: expected 'gateway call {\n  headers: {\n    Aut…' not to contain 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvcGVy…'`. R2_B3_array_warn (`console.warn('session', [{ t: token }])`): `a log line carries the JWT: expected 'session [\n  {\n    t: \'eyJhbGciOiJI…'`. R2_B3_prod_info (`console.info({ a: { tok: token } })`, production): `the server output carries the JWT: expected 'Listening on http://127.0.0.1:45991\n…' not to contain 'eyJ…'` |
| 4 | B4 remainder check | **met** | n/a | **R_G1inline (round 1's surviving arm, re-run): now fails, 2 of 2**: `/login \| action sign-in \| POST /api/auth/login -> 400 \| detail \| text beside the problem's words that is not a reviewed label: ["Something went wrong. sweep-7e6393a481a3-1-detail"]` (and the title variant). R2_G1prefix (`Error: {{ errorText() }}`): `... not a reviewed label: ["Error: sweep-cccb40ca518a-1-detail"]` |
| 5 | B5 dot / separator ids | **met** | `P GET /api/orders/.. -> 400 \| upstream: []`, `%2E%2E -> 400`, `. -> 400`, `x%3Fy=1 -> 400`, `POST /api/invoices/../payments -> 400`; probe3 edges: `.%2E -> 400`, `%2E. -> 400`, `x%2F.. -> 400`; `%252E%252E -> 200 upstream ["GET /orders/%25252E%25252E"]`, `%2e%2e%3b -> ["GET /orders/..%3B"]`, `%5C.. -> ["GET /orders/%5C.."]`, `a%2500 -> ["GET /orders/a%252500"]`, which are all one encoded segment and safe | R2_B5_single_dot (in-process; `.` dropped): `GET /api/orders/.: expected 599 to be 400`. R2_B5_payments_prod (payments route proxies the raw param when `pathId` refuses): `POST /api/invoices/../payments: expected 599 to be 400` |
| 6 | A1 unreadable cookie cleared | **met** | `T3 garbage cookie session: 200 {"authenticated":false} set-cookie lines: [ 'set-cookie: otc_session=; Max-Age=0; Pat' ]`; `T3b garbage cookie proxied: 401 ... otc_session=; Max-Age=0; Path=/; HttpOnly; Secur` | R2_A1_sibling_cookie (clears `otc_sessionx`): `an unreadable cookie must be expired: expected [] to have a length of 1 but got +0` |
| 7 | A2 no Gateway URL in 502/504 detail | **met** | `R timeout 504 {...,"detail":"The Gateway did not answer within 400 ms.",...}`; `R unreachable 502 {...,"detail":"The Gateway could not be reached (fetch failed).",...}`; the server output holds `gateway could not be reached: http://127.0.0.1:41871 (fetch failed)` | R2_A2_504_detail (in-process): `the browser-facing detail names the internal Gateway address: expected 'The Gateway did not answer within 150…' not to contain '127.0.0.1:44985'` |
| 8 | A5 exact h3 pin | **met** | `package.json:38 "h3": "1.15.11"`; lockfile `specifier: 1.15.11` / `version: 1.15.11`; `install --frozen-lockfile` passes | R2_A5_tilde (`~1.15.11`): `h3 is not an exact version (a range lets the lockfile drift silently): expected '~1.15.11' to match /^\d+\.\d+\.\d+$/` |
| 9 | A6 whole-origin compare | **met** | `C Origin https same host -> 403`; `Origin uppercase host -> 200` (normalised); probe3: `X-Forwarded-Proto: https` + `Origin http://<own>` `-> 403` (consistent with the comment at `lib/csrf.ts:13`) | R2_A6_host_only_prod (round 1 behaviour, scheme taken from the request): `Origin https://127.0.0.1:44073: expected 200 to be 403` |

Arms: 19 run through the driver plus 2 production experiments. 18 failed at the intended test by name. 1 survived: B05_header_fallback, see below. All 21 were restored byte-identical (`cmp`).

| arm | test (`-t`) | result | backup sha256 (12) | cmp |
|---|---|---|---|---|
| R_B19 | bff.spec "the JWT is in no log line" | failed 1/35, named | 346abce35953 | identical |
| R2_B3_array_warn | same | failed 1/35, named | 346abce35953 | identical |
| R2_B3_prod_info | production "in no line the production server writes" | failed 1/34, named | 346abce35953 | identical |
| R_G1inline | sweep "shows each action request's failure as that problem's own" | failed 2/26, named | 99c57dafb9cd | identical |
| R2_G1prefix | same | failed 2/26, named | 99c57dafb9cd | identical |
| R2_B1_reqUrl / _prod | "the check runs on every path the router can reach" | failed 1/35 and 1/34, named | 11d4472522b5 | identical |
| R2_B1_textplain_allowed / R2_B1_urlencoded_prod | "does not declare application/json" | failed 1/35 and 1/34, named | 46d21dcfd018 | identical |
| R2_A6_host_only_prod | "compares the whole origin" | failed 1/34, named | 46d21dcfd018 | identical |
| R2_B2_listener_late | "leaves before the Gateway answers the stream's headers" | failed 1/35, named | a5721d77951a | identical |
| R2_B5_single_dot / R2_B5_payments_prod | "an id that is empty, a dot segment" | failed 1/35 and 1/34, named | 5c74dd073140 / ad5aed8b0a0b | identical |
| R2_A1_sibling_cookie | "a tampered cookie is no session" | failed 1/35, named | faed02b628fc | identical |
| R2_A2_504_detail | "does not answer within WEB_GATEWAY_TIMEOUT_MS" | failed 1/35, named | f60a7686b1c6 | identical |
| R2_A5_tilde | boundaries "R-pin" | failed 1/11, named | b33a104705e3 | identical |
| B05_header_first | "default session header" | failed 1/35: `a sealed session in the x-otc_session-session header authenticated the request: expected { authenticated: true, …(3) } to deeply equal { authenticated: false }` | faed02b628fc | identical |
| B05_useSession_noflag | same | failed 1/35, same message | faed02b628fc | identical |
| **B05_header_fallback** | same | **SURVIVED: passed 1, failed 0** | faed02b628fc | identical |
| R2_B2b_check_deleted (production probe) | probeW | leaks (below) | a5721d77951a | identical |
| R2_B2fix_candidate (production probe) | probeW | no upstream opened (N1) | a5721d77951a | identical |

### The two disclosures

**B2b (the post-await `res.destroyed` check): keep it, and correct the record.** It is not unarmable. The record says no test can drive it reliably, and that is false. Today it is the only thing that bounds the N1 window. With it deleted (R2_B2b_check_deleted, production), the slow-headers same-tick case leaks indefinitely (3 of 3):
```
W slow-headers, client destroys in the same tick it sends: upstream arrived=true open 300ms:1 1000ms:1 2000ms:1 3500ms:1
```
With it present, the same case releases when the headers arrive (`2000ms:0`). The implementer's arm B2b survived only because their test destroys the client after the listener is attached.

Once N1's one-line synchronous check is in, the post-await check really does become defence in depth, covering only a tick that cannot be driven. Keeping it then, disclosed as unarmed, is acceptable. The N1 contract case is what must be armed.

**B05 (`sessionHeader: false` an equivalent mutant): the property is still guarded, but only in part.** The test `R-session: h3's default session header (x-otc_session-session) is not an authentication path` fails when the header is read before the cookie (B05_header_first). It also fails when `readSession` goes back to `useSession` with the flag deleted (B05_useSession_noflag). So the A1 change did not leave the property unguarded, and the implementer's account of the equivalent mutant is right.

It does not fail when the header is read as a fallback with no cookie (B05_header_fallback survived). The test always sends `cookie: otc_session=garbage` alongside the header (`bff-contract.ts:168`), so a `getCookie(...) ?? header` read never reaches the header. Live, the property holds today: probe1 `T4 header-only session (no cookie): {"authenticated":false}`.

Recommendation (an advisory under the stopping rule, but one line, so fold it into the N1 round): add a cookie-less request carrying only the header to the same test, and arm it with B05_header_fallback.

### B5 class enumeration, re-run

`grep -rn "getRequestURL\|event\.path\|getRouterParam\|\.pathname\|originalUrl\|node\.req\.url" src/server scripts --include=*.ts --include=*.mjs --exclude=*.spec.ts --exclude-dir=testing` (run in `apps/web`, with the exclusion applied at the source, exit 0):
```
src/server/lib/gateway.ts:1:import { getHeader, getRequestURL, readRawBody, sendNoContent, setResponseHeader, setResponseStatus, type H3Event } from 'h3';
src/server/lib/gateway.ts:114:      search: method === 'GET' ? getRequestURL(event).search : '',
src/server/lib/path-id.ts:1:import { getRequestURL, getRouterParam, type H3Event } from 'h3';
src/server/lib/path-id.ts:14:  const id = getRouterParam(event, name) ?? '';
src/server/lib/path-id.ts:16:  const rawPath = getRequestURL(event).pathname;
src/server/routes/api/[...path].ts:1:import { defineEventHandler, getRequestURL } from 'h3';
src/server/routes/api/[...path].ts:9:export default defineEventHandler((event) => localProblem(event, 404, 'NOT_FOUND', 'No such API route', `${event.method} ${getRequestURL(event).pathname} is not a route of this site.`));
```
Sentinel: the same pattern finds hits in the excluded population (`src/server/boundaries.spec.ts`, `src/server/testing/fake-gateway.ts`), so it is the exclusion that removes them, not a broken pattern.

The 7 hits are the implementer's 7, and I agree with each classification:
- `gateway.ts:1`, `path-id.ts:1` and `[...path].ts:1` are imports.
- `[...path].ts:9` is message text only.
- `path-id.ts:14,16` are the fix itself.
- `gateway.ts:114` is the raw GET query string, appended after a path built from a validated id. A literal `?` starts it (probe: `GET /api/orders/x?y=1 -> ["GET /orders/x?y=1"]`), and query pass-through on GETs was accepted in round 1 as #8's behaviour.
- The old reader sites `orders/[id].get.ts:8` and `payments.post.ts:8` now go through `pathId`, and `middleware/csrf.ts:7` is gone.

### Gates (`npx --yes pnpm@12.8.1 -C apps/web ...`, each under `setsid --wait timeout -k 10`)

- `install --frozen-lockfile`: exit 0, "Lockfile is up to date, resolution step is skipped".
- `run types:check`: exit 0, `types:check OK — src/generated/openapi.ts matches a fresh generation from specs/shared/openapi.yaml.`
- `run test:ci` (JSON reporter artifact `g3_testci.json`): **18 files, 251 tests, 251 passed, 0 failed, 0 pending**. This reconciles with the record's 236 + 15 file by file:
  - error-text.sweep 25 -> 26 (+1);
  - production-bff 27 -> 34 (+7);
  - bff 29 -> 35 (+6);
  - boundaries 10 -> 11 (+1);
  - the other 14 files are unchanged.
- `run build`: exit 0, `377 modules transformed`, and `dist/client/index.html` has no `/src/main.ts`.
- After the arms: `test:ci` re-run green (`g5_green.json`: 18 / 251 / 251 / 0), then `run build` re-run (exit 0). `dist/client/index.html` has no `ng-state` and no `/src/main.ts`.

### CHECKPOINTS.md (boxes applicable to a stage review)

- [x] C2: one feature `in_progress` (29).
- [x] C3: no stray debug logging. The two new `console.error` lines in `gateway.ts:60,64` are the intended server log of A2.
- [x] C4: the web part of the gate passes (install, types:check, test:ci 18/251, build). The full `./quality.sh` was not run; the leader runs it at the checkpoint.
- [x] C4: no Jest, Karma or Jasmine (unchanged from round 1).
- [x] C5: Claude did not commit. My artifacts are under the git-ignored `.arm/`.
- [x] C6: n/a (`sdd: false`).
- [x] C7: `specs/shared/` untouched (`git status --porcelain` lists nothing under `specs/`).
- [ ] C7 ledger, SSE-abort row: still incomplete (N1). The record's correction ("CORRECTED (reviewer B2)") holds only once the listener runs before the client can leave.

### What must change before re-review

1. **N1**: `stream.get.ts`, after line 21: `if (res.destroyed) { res.off('close', onClientGone); return undefined; }` (one line, verified above). Add the same-tick-disconnect contract case (raw socket writes then destroys; never-headers fake; no upstream connection open within the bound), in-process and production. Arm it by deleting the line. Correct the B2b paragraph in `impl_web_app.md`: the check was armable and load-bearing before this fix.
2. (Advisory, folded in because it is one line.) B05: add a cookie-less, header-only request to `R-session: h3's default session header ...` and arm it with B05_header_fallback (`getCookie(...) ?? header`).

No finding is rooted in `specs/shared/`, so no SA-n or backlog routing is owed. This is the first rejection after a fix round. Under `CLAUDE.md` ("At most one rejection round without asking"), the leader now asks the maintainer whether to run a second round for the item above or accept with a disposition.

## Stage 1 re-review (fix round 2)

Reviewer: Claude (Opus 5.5), 2026-10-15. Scope, set by the maintainer's ruling at the gate after the second rejection (`progress/current.md`): only N1, B05 and the B2b record correction from "Stage 1 re-review (fix round 1)" → "What must change before re-review". Fix brief: `progress/brief_impl_web_app_stage1_round3.md`. Record: `progress/impl_web_app.md` → "Stage 1 — fix round 2". There is no round 3.

I was read-only. Sources were touched only by the arm drivers (backup with `sha256`, mutate, restore by `cp`, `cmp`). `sha256sum -c .arm/web29r3/sha_start.txt` after all runs: all 11 watched files OK, including `stream.get.ts` c1b8cbdf247e, `session.ts` faed02b628fc and `bff-contract.ts` e3e569771f20. `git status --short` before and after: identical ("GIT-IDENTICAL"). `ss -ltnp` local addresses before and after: identical ("PORTS-IDENTICAL"). No `dist/analog/server/index.mjs` process left. `feature_list.json` not edited. Artifacts are in `.arm/web29r3/`: `arm.py` and `armprod.sh` (copies of `.arm/web29r2/`'s with the directory changed), `arms.json`, `results.jsonl`, `out_*.json`, `backup/`, `probeW_fixed.out`, `N1del_probe.{diff,out}`, `R2_B2b_check_deleted.{diff,out}`, and `g*.log/json`.

Scope check: `find apps/web` (excluding `node_modules`, `dist`, `.angular`) for files newer than the previous re-review's last build (`.arm/web29r2/g6_build.log`, 07:56) lists exactly 2 files: `src/server/routes/api/orders/stream.get.ts` and `src/server/testing/bff-contract.ts`. The 9 other watched files keep round 1's digests. The round touched nothing outside its bounds.

### Verdict: **APPROVED** (stage 1)

N1 and B05 are met, each shown by a probe and by arms that fail by name. The B2b record is corrected and agrees with what I measured. The change introduced no defect that I found.

### Item by item

| item | met? | evidence |
|---|---|---|
| **N1**: `stream.get.ts` returns without opening the upstream when the response is already destroyed; same-tick contract case in-process and production, armed | **met** | `stream.get.ts:21-26`: `res.on('close', onClientGone)` followed synchronously by `if (res.destroyed) { res.off(...); return undefined; }`. The production bundle has it too (`dist/analog/server/chunks/routes/api/orders/stream.get.mjs:53-57`). Nothing is awaited between the check and `fetch` (`stream-proxy.ts:19-24` is synchronous), so no window remains before the listener is attached. probeW on a fresh production build, 6 of 6 clean: `W never-headers, client destroys in the same tick it sends: upstream arrived=false open 300ms:0 1000ms:0 2000ms:0 3500ms:0` (and the same for slow-headers). Before the fix this was `arrived=true ... 3500ms:1`. New test: `bff-contract.ts:509` `R-stream: a client that disconnects in the same tick it sends the request opens no upstream connection`, run by both `bff.spec.ts` (in-process) and `production-bff.spec.ts` (production) |
| **B2b record correction** | **met** | `impl_web_app.md:391` is marked "CORRECTED IN PLACE": load-bearing in round 1 (3 of 3 leaked without it), unarmed only after N1's line. "Stage 1 — fix round 2" → "B2b correction" says the same. Measured: with N1's block present and the post-await check deleted (`R2_B2b_check_deleted` re-run on production), 6 of 6 are clean (`arrived=false ... 3500ms:0`). So the check really does carry nothing observable now, and "kept, unarmed, defence in depth" is accurate |
| **B05**: cookie-less, header-only request added to `R-session: h3's default session header ...`, armed with B05_header_fallback | **met** | `bff-contract.ts:171-173`: `bff.fetch('/api/auth/session', { headers: { 'x-otc_session-session': sealed } })` expects `{ authenticated: false }`, labelled `'a cookie-less request carrying only the x-otc_session-session header authenticated'`. B05_header_fallback, which survived the last round, now fails by name (below) |

### Arms (re-run by me; verdict from each run's JSON reporter artifact `out_<id>.json`; `setsid --wait timeout -k 10 420`; backups in `.arm/web29r3/backup/<id>/`)

There are 23 driver arms. All 23 failed at the intended test by name, with no suite errors, and every one was restored `cmp`-identical, with the `sha256` after the run equal to the backup. I adapted `R2_B2_listener_late` to the current anchor: the listener moves after the await, and the N1 block goes with it. That is round 1's defect form. I retargeted B05_header_fallback's `expect` to the new assertion label.

| arm | mutation | test | verbatim failure (first line) | backup sha256 (12) | cmp |
|---|---|---|---|---|---|
| **N1_line_deleted** (record's) | N1 block deleted | in-process `same tick` | `AssertionError: the upstream connection stayed open for a client that had already left: expected 3 to be +0 // Object.is equality` | c1b8cbdf247e | identical |
| **N1_prod** (record's) | same, production rebuilt in `beforeAll` | production `same tick` | `AssertionError: the upstream connection stayed open for a client that had already left: expected 3 to be +0 // Object.is equality` | c1b8cbdf247e | identical |
| **B05_header_fallback** (record's; survived last round) | `getCookie(...) ?? req.headers['x-otc_session-session']` | in-process `default session header` | `AssertionError: a cookie-less request carrying only the x-otc_session-session header authenticated: expected { authenticated: true, …(3) } to deeply equal { authenticated: false }` | faed02b628fc | identical |
| N1_no_return (mine, corrupt family) | the `return undefined` dropped from the N1 block | in-process `same tick` | `AssertionError: the upstream connection stayed open for a client that had already left: expected 3 to be +0 // Object.is equality` | c1b8cbdf247e | identical |
| N1_sibling_writableEnded (mine, sibling family) | `res.destroyed` -> `res.writableEnded` | in-process `same tick` | same message | c1b8cbdf247e | identical |
| R2_B2_listener_late | listener after the await, N1 block removed, post-await check kept | in-process `leaves before the Gateway answers` | `Error: the upstream connection stayed open after the client left before the upstream answered its headers: still false after 3000 ms` | c1b8cbdf247e | identical |
| B05_header_first | header read before the cookie | `default session header` | `AssertionError: a sealed session in the x-otc_session-session header authenticated the request: expected { authenticated: true, …(3) } to deeply equal { authenticated: false }` | faed02b628fc | identical |
| B05_useSession_noflag | `useSession` with `sessionHeader:false` deleted | same | same message | faed02b628fc | identical |
| R_B19 | `console.error('gateway call', { headers: { Authorization } })` | `the JWT is in no log line` | `AssertionError: a log line carries the JWT: expected 'gateway call {\n  headers: {\n    Aut…' not to contain 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvcGVy…'` | 346abce35953 | identical |
| R2_B3_array_warn | `console.warn('session', [{ t }])` | same | `AssertionError: a log line carries the JWT: expected 'session [\n  {\n    t: \'eyJhbGciOiJI…' not to contain 'eyJ…'` | 346abce35953 | identical |
| R2_B3_prod_info | `console.info({ a: { tok } })`, production | `in no line the production server writes` | `AssertionError: the server output carries the JWT: expected 'Listening on http://127.0.0.1:34883\n…' not to contain 'eyJ…'` | 346abce35953 | identical |
| R_G1inline / R2_G1prefix | generic / `Error:` text in the problem's node | sweep `shows each action request's failure as that problem's own` | failed 2/26 each: `AssertionError: /login \| sign-in: action failures the user does not see in the problem's own words ...` | 99c57dafb9cd | identical |
| R2_B1_reqUrl / _prod | middleware gated on raw `req.url` | `the check runs on every path` | `AssertionError: /%61pi/stock/replenish {"Origin":"https://evil.example"}: expected 200 to be 403` (both runners) | 11d4472522b5 | identical |
| R2_B1_textplain_allowed | `text/plain` accepted | `does not declare application/json` | `AssertionError: text/plain order: expected 201 to be 415` | 46d21dcfd018 | identical |
| R2_B1_urlencoded_prod | urlencoded accepted, production | same | `AssertionError: urlencoded login: expected 200 to be 415` | 46d21dcfd018 | identical |
| R2_A6_host_only_prod | scheme from the request | `compares the whole origin` | `AssertionError: Origin https://127.0.0.1:33367: expected 200 to be 403` | 46d21dcfd018 | identical |
| R2_B5_single_dot | `.` no longer refused | `an id that is empty, a dot segment` | `AssertionError: GET /api/orders/.: expected 599 to be 400` | 5c74dd073140 | identical |
| R2_B5_payments_prod | raw param proxied on refusal | same, production | `AssertionError: POST /api/invoices/../payments: expected 599 to be 400` | ad5aed8b0a0b | identical |
| R2_A1_sibling_cookie | clears `otc_sessionx` | `a tampered cookie is no session` | `AssertionError: an unreadable cookie must be expired: expected [] to have a length of 1 but got +0` | faed02b628fc | identical |
| R2_A2_504_detail | base URL in the 504 detail | `does not answer within WEB_GATEWAY_TIMEOUT_MS` | `AssertionError: the browser-facing detail names the internal Gateway address: expected 'The Gateway did not answer within 150…' not to contain '127.0.0.1:40567'` | f60a7686b1c6 | identical |
| R2_A5_tilde | `"h3": "~1.15.11"` | boundaries `R-pin` | `AssertionError: h3 is not an exact version (a range lets the lockfile drift silently): expected '~1.15.11' to match /^\d+\.\d+\.\d+$/` | b33a104705e3 | identical |

Production probe arms (`.arm/web29r3/armprod.sh`: backup, mutate, `vite build`, run `.arm/web29r2/probeW.mjs`, restore, `cmp`):

| arm | diff | probeW result | backup sha256 | cmp |
|---|---|---|---|---|
| N1del_probe (N1 block deleted) | `23,26d22` (the 4 lines) | leaks again, 3 of 3 in never-headers: `W never-headers, client destroys in the same tick it sends: upstream arrived=true open 300ms:1 1000ms:1 2000ms:1 3500ms:1`. slow-headers: `arrived=true ... 2000ms:0` (released by the post-await check) | c1b8cbdf247e | identical |
| R2_B2b_check_deleted (post-await check deleted, N1 present) | `40,46d39` | no leak, 6 of 6: `upstream arrived=false open ... 3500ms:0` | c1b8cbdf247e | identical |

### Gates (`npx --yes pnpm@12.8.1 -C apps/web ...`, each under `setsid --wait timeout -k 10`; `.arm/web29r3/gates.sh`)

- `install --frozen-lockfile`: exit 0, "Lockfile is up to date, resolution step is skipped".
- `run types:check`: exit 0, `types:check OK — src/generated/openapi.ts matches a fresh generation from specs/shared/openapi.yaml.`
- `run test:ci` (JSON artifact `g3_testci.json`): **18 files, 253 tests, 253 passed, 0 failed, 0 pending**. Reconciled with the last re-review's `g3_testci.json` file by file: `bff.spec.ts` 35 -> 36 and `production-bff.spec.ts` 34 -> 35, the other 16 unchanged. That is +2, the same-tick case in each runner. B05 extended an existing test.
- `run build`: exit 0, `377 modules transformed`, `dist/client/index.html` has no `/src/main.ts`.
- After the arms: `test:ci` re-run green (`g5_green.json`: 18 / 253 / 253 / 0), then `run build` re-run (exit 0). The bundle carries the N1 block and the post-await check, and no mutation.

### CHECKPOINTS.md (boxes applicable to this scoped re-review)

- [x] C2: one feature `in_progress` (29). Not edited by me.
- [x] C3: no debug logging added (the 2-file diff has none).
- [x] C4: the web part of the gate passes (install, types:check, test:ci 18/253, build). The full `./quality.sh` was not run; the leader runs it at the checkpoint.
- [x] C5: Claude did not commit. My artifacts are under the git-ignored `.arm/`.
- [x] C6: n/a (`sdd: false`).
- [x] C7: `specs/shared/` untouched.
- [x] C7 ledger, SSE-abort row: now complete. The client leaving at any point after the request is parsed releases or never opens the upstream: before the listener (N1 block), before the headers (listener plus abort), after the headers (pump / close). Each of the three is armed: N1_line_deleted / N1_prod, R2_B2_listener_late, and round 1's S2 / `closing the client connection aborts the upstream`.

### Advisories carried to stage 2 (no rejection, under the "no round 3" ruling)

1. **The same-tick test has no positive control.** `bff-contract.ts:509-525` asserts that nothing reached the upstream. It does not assert that the BFF ever handled the 3 requests with a valid session. If a later change makes the BFF refuse the raw-socket request earlier (for example a 401 because the cookie stops being accepted, or a header the raw request lacks), the test passes vacuously. Today it is not vacuous: N1_line_deleted shows 3 upstream connections. Suggested acceptance item for stage 2: a fourth socket in the same case that stays connected and must reach the upstream (`requests` +1), so that a test that stops exercising the route fails.
2. **The post-await `res.destroyed || signal.aborted` check (`stream.get.ts:40-46`) is unarmed by design.** Measured above: deleting it changes nothing observable with N1 in place. This is disclosed in the record and acceptable. If stage 2 touches `stream.get.ts`, re-run `.arm/web29r3/armprod.sh N1del_probe` and `R2_B2b_check_deleted` (both re-runnable as they stand), because the arms go stale with the path.

No finding is rooted in `specs/shared/`, so no SA-n or backlog routing is owed. A3 and A4 remain stage 2's acceptance items, as recorded at the first review.

## Stage 2 review

Scope: `progress/brief_review_web_app_stage2.md` (stopping rule written by the leader before the review), against `progress/brief_impl_web_app_stage2.md` items 1–12 and *Must hold*, the resume addendum, and the record `progress/impl_web_app.md` "Stage 2 of 4". Reviewer artifacts: `.arm/web29r2/s2/` (driver `arm.py`, a copy of `.arm/web29s2/arm.py` with the directory changed; `defs_r2.py`; `results.jsonl`, 28 rows; `<id>/out.json` reporter artifacts; `parity/`; `live/`; `sha_start.txt`). Disclosure: the four gate logs and `gates.sh`/`gates.summary` were written at the root of `.arm/web29r2/` (stage 1's directory) before I moved to `s2/`; they are new files, no stage 1 artifact was overwritten (stage 1's are `g1_*`…`g6_*`, `out_*`, `R2_*`, listed at its section).

### Verdict: **REJECTED** (stage 2)

Two findings meet the stopping rule: B1 under (b) (wrong money reaches the BFF from the production build), B2 under (a)/(c) (item 10, A3: a page that fires a request after a delay with no action passes the whole sweep). Everything else probed holds: money parse/format/step, the bytes for "19.99" and "0.29", parity both ways, the live timeline (per-type de-duplication, `Last-Event-ID`, one stream, close on leave, `resumed:false` re-read, R55's waiting state), id 98, backlog 201, id 106, item 12, ids 100/102, and every arm re-run except the two that expose B2 and A1. This is the first rejection round of stage 2.

### Blocking findings

**B1 (rule b, item 6 and item 1: wrong money).** A malformed price typed into the unit-price or line-discount box is dropped by the browser, and the page places the order at the catalogue price (or with no discount), with no problem shown.

- Unit: `apps/web/src/app/pages/(app)/orders/place.page.ts:150` and `:157` (`<input type="number">`, the handler stores `$event.target.value`); `:337` and `:342` (`if (line.unitPrice.trim())` / `if (line.lineDiscount.trim())` read an empty string as "not overridden"); `:289-290` (no problem for an empty string).
- Mechanism: for a `type="number"` input whose text is not a valid floating-point number, Chromium shows the typed text but `value` is `""` (`validity.badInput` true), and the `input` event carries `""`. The money module never sees the text, so its refusal "in words" never fires.
- Probe 1 (Chromium, a bare `<input type="number" step="0.01">`, `.arm/web29r2/s2/live/numprobe.mjs`): `"12e" {"shown":"12e","value":"","badInput":true}`, `"1-2" {"shown":"1-2","value":"","badInput":true}`, `"19.99-" {"shown":"19.99-","value":"","badInput":true}`.
- Probe 2 (end to end, the production build from my gate run, served by `dist/analog/server/index.mjs`, real Chromium, every `/api/**` answered by `page.route`, so the body recorded is the bytes the browser sends to the BFF; `.arm/web29r2/s2/live/bytes.mjs`, output `bytes.out`). Catalogue price of PRD-0001 is 19.99 EUR, quantity 2:
  - `"1-2"` typed as unit price: `"shown":{"priceValue":"","priceBadInput":true,...,"runningTotal":"39.98 EUR"}`, `"sent":"{\"retailerCode\":\"CarrefourEs\",\"companyCode\":\"IBERFOODS\",\"currency\":\"EUR\",\"lines\":[{\"productCode\":\"PRD-0001\",\"quantity\":2}]}"`, and the page navigated to the new order.
  - `"12e"` and `"19.99-"`: the same body, no `unitPrice`.
  - `"5-"` typed as line discount: `"discountBadInput":true`, sent with no `lineDiscount`.
  - Controls, correct: `"19.99"` sent `"unitPrice":1999`, `"0.29"` sent `"unitPrice":29`, BHD `"1.005"` sent `"unitPrice":1005` with `step` `0.001`.
- Why it matters: the operator sees an override in the box and gets an order at another price, in the path the brief classes as full group. The module's own contract (`money.ts:26-28`: "`undefined`, never a wrong number, for ... a sign, scientific notation") is bypassed by the input type. #8 did not have this, because its money inputs are text inputs with `inputMode="decimal"` (`order-to-cash-dotnet/apps/web/src/features/orders/place-order-form.tsx:400-416`), so its parser sees every character. #7 used `type="number"` (`order-to-cash-nestjs/apps/web/app/pages/orders/place.vue:381,395`).
- Not a tested path: `R-bytes` drives the inputs with `fireEvent.input(..., { target: { value } })`, which can never produce a bad input with a non-empty visible text.
- Recommendation (the implementer chooses): item 1 mandates `step`, so keep `type="number"` and treat `validity.badInput` as a typed but unparseable value. The handler records it, `problemsFor` refuses it in words ("Enter an amount ..."), and `buildRequest` sends nothing. Alternatively, use #8's text input, and then decide what item 1's `step` means for it. Guard: a place-order test where the input reports `badInput` with an empty value (jsdom: define `validity` on the element), asserting that nothing is sent and the problem text is shown, for both money fields. Arm it by deleting the `badInput` branch.

**B2 (rule a/c, item 10, stage 1 A3): the measured late bound accepts an app timer whose delay falls in a library class.** `LONG_TIMER_CLASSES` (`apps/web/src/app/error-text.sweep.spec.ts:229-232`) matches on `kind` and `delay` only. The harness already records `origin` (`'app'` / `'library'`, `testing/page-sweep.ts:199`), but no class reads it, so an app-origin timer is waved through as "gcTime", "staleTime" (any `setTimeout` in 0–2001, 28000–30001 or 58000–60001 ms) or "poll" (`setInterval` 5000).

- V07 (mutation in `pages/(app)/orders/index.page.ts`: `constructor() { const later = setTimeout; later(() => void this.api.listStock(), 1800); }`; test "the late watch is measured against the timers the runs REQUESTED"): **SURVIVED**, `passed 1 failed 0` (`out.json`: that test ran, 61 skipped).
- V07c (the same, at `29_000` ms; the **whole** `error-text.sweep.spec.ts`): **SURVIVED**, `passed 62 failed 0`. A page that fires a request 29 s after load, with no action reaching it, passes every sweep test.
- V07b (1800 ms, whole file): 18 failures, all in action-phase runs (`/orders | sign-out: requests with no success body: expected [ 'GET /api/stock' ] to deeply equal []`, `/orders | filter-by-status ...`). This is caught only because those runs last longer than 1.8 s, which is exactly the incidental catch stage 1's A3 described ("A page with no action would not catch it").
- Control V07d (the same 1800 ms request written as a literal `setTimeout(`): FAILED in the TIMERS content scan (`a timer the late watch has not been checked against. Found: {... "pages/(app)/orders/index.page.ts":["refetchInterval","setTimeout"] ...}`). The content scan catches the literal form, but the measured guard, which item 10 asked for because content scans miss forms ("don't widen a regex"), does not.
- The record's arm P18 used `AbortSignal.timeout(3000)`, a kind and delay outside every class, so it could not see this.
- Recommendation: a class matches only `origin === 'library'` (and for the staleTime band, a TanStack creator). An app-origin timer longer than `LATE_WATCH_MS` is always unreviewed unless it is named in its own reviewed entry. Re-arm with V07 and V07c (`.arm/web29r2/s2/defs_r2.py`), and keep P18.

### Advisories (not grounds for rejection; each with a recommendation)

- **A1. The same-tick premise counts route entry, not a signed-in request (item 11 met as worded).** V09 (`server/testing/bff-contract.ts`: the raw same-tick request sends `Cookie: otc_probe=1`): **SURVIVED**, `passed 1 failed 0`. The route logs `STREAM_ROUTE_ENTERED` before `readSession` (`stream.get.ts:12-14`), so a request the BFF refuses with 401 satisfies the premise and opens no upstream. This is the case stage 1's advisory 1 named ("a 401 because the cookie stops being accepted"). Recommend a second marker after the session is read (or stage 1's positive-control socket), and arming with V09.
- **A2. The pager keeps the last count after a poll failure.** Probe `.arm/web29r2/s2/live/listpoll.mjs` (production build; the first `/api/orders` answers 45 rows, every later one 500): `{"when":"after a poll failed","listReads":3,"pager":"Page 1 of 3 · 45 orders","error":"The read model is down (probe).","table":0,"nextEnabled":true}`. The comments at `index.page.ts:149` ("nothing is claimed while loading or after a failure") and `components/pager.ts:19` say otherwise. TanStack keeps `data` on a failed refetch. The pager does not lie while loading (#8 S4 holds, P06), so this is not stage 2's acceptance item. Recommend `counts = isError() ? undefined : data()?.page`, or correcting the comment, with a test that fails the second read.
- **A3. Ledger rows (record section 5): the #7/#8 halves are not read from the checkouts with a file and line, and two are wrong.**
  - "Table parity": #7 has no Python table. Its `apps/web/app/lib/money.ts:16` points at `packages/shared-kernel/src/domain/currency-exponent.ts`. #8's guard is a .NET test, `tests/SharedKernel.UnitTests/CurrencyExponentWebParityTests.cs:30`, not "the Python test".
  - "Stable label/control ids": #7 derives them from the line index (`app/pages/orders/place.vue:348-379`), not from a `useId`-style id.
  - Recommend correcting every row with a file:line per half (CLAUDE.md, *Porting*). This is a record-only edit. Under the stopping rule it is not by itself a rejection ground, but the round is open.
- **A4. The `/` census in the record is one short.** My AST census of `apps/web/src` and `scripts` (every `/`, `**`, `parseFloat`, `toFixed`, `Intl`, `getNumberOfCurrencyDigits`, `toLocaleString`, `parseInt`, `Number(` outside specs; 94 files, 18 hits) finds two `/`, not one: `components/pager.ts:8` (disclosed) and `pages/(app)/orders/[id].page.ts:262` (`milliseconds / 1000`, a retry interval shown in a sentence, not money). Both are acceptable. Recommend naming the second one in the record. Every hit is classified:
  - `Number(` at `lib/money.ts:22,88,98` converts a BigInt after the range check (exact);
  - `place.page.ts:50` is a quantity after `/^\d+$/` and `isSafeInteger`;
  - `api-client.ts:66` is `Retry-After`;
  - `server/lib/config.ts:61` is a timeout;
  - `scripts/serve.mjs:20` is a port;
  - the remaining `Number(` hits are in testing files;
  - `Intl` and `getNumberOfCurrencyDigits` appear only in `scripts/cldr-disagreement.mjs:8,12,21,22` (the measurement).
  - A template search (`{{ ... / ... }}`, number or currency pipes) found none.
- **A5. `console.debug(STREAM_ROUTE_ENTERED)` runs in production** on every stream request (`stream.get.ts:12`). It is deliberate and documented as the test premise. Recommend keeping it out of the production log (a hook the harness installs), or accepting it explicitly.
- **Pager `/` (probe 9), judged: acceptable.** `(total - total % size) / size` divides an exact multiple, so the quotient is exact for safe integers. V06 (`whole = total / pageSize`) fails `pager.spec.ts` (`expected 1.05 to be 1`), so the claim is armed. It is not money.

### Probes the leader asked for

1. **Money.** Parse/format/step for HUF, IQD, JPY, BHD, EUR and an unlisted code are asserted in `money.spec.ts` (`R-parse`, `R-format`, the `it.each` rows: `"1e3"`, `"+5"`, `"-5"`, `" 20.50 "`, `".99"`, `"20."`, `"."`, `"٣"`, `"0x10"`) and `currency-exponent.spec.ts`. Safe-integer neighbours are tested at every exponent (`money.spec.ts:35-44`). On the rendered input, `step` is `0.01` / `0.001` / `1` / `0.0001` (`place-order.spec.ts` `R-step`), and live: BHD `"priceStep":"0.001"`. The census is A4.
   - Parity both ways (`.arm/web29r2/s2/parity.sh`):
     - Y2, Python table `KWD 3 -> 2` (backup sha256 `90d0860b049b`): `test_the_json_export_for_the_web_equals_the_python_table_in_both_directions` fails, `AssertionError: assert ['KWD: Python... JSON says 3'] == []`, `cmp` identical.
     - W2, web JSON `IQD 3 -> 0` (`b21e1c1ce3ef`): the same Python test fails, `assert ['IQD: Python... JSON says 0'] == []`. The web test "every one of the 26 rows is the literal row" fails, `expected [ Array(1) ] to deeply equal []`. `cmp` identical.
     - Afterwards the parity file is green: 15 passed.
   - CLDR measurement re-run: output byte-identical to the record's (`.arm/web29r2/s2/cldr.out`): 1 of 26 table rows, 17 of 162 codes, Angular 14.
2. **Bytes to the BFF.** Production build, Chromium: `"19.99"` was sent as `"unitPrice":1999` and `"0.29"` as `"unitPrice":29` (full bodies in `live/bytes.out`). The malformed-text case is B1.
3. **Live timeline.**
   - Per-type de-duplication with colliding ids: V05 (the timeline handler checks the update set) fails, `expected [ …(3) ] to deeply equal [ …(4) ]`, as does P09.
   - `Last-Event-ID`: P26 fails, `expected undefined to be 'c1'`, against a real `eventsource` client.
   - One stream, closed on leave: P08 (record) and the `R-stream-live` test.
   - `resumed:false` re-read: P15 fails, `expected 1 to be 2`.
   - R55 web half: the test is named in the matrix row's words (`order-detail.spec.ts` › "renders the waiting state on a projection-pending answer and fills in from the update stream", with Retry-After 60 s so only the stream can fill it in). P13 fails, `the frame made the page read the order again: expected 1 to be 2`.
4. **Id 98.** P10 fails, `giving up asked the order again, through a query: expected false to be true`. P11 fails, `a refusal must never reopen a stream: expected 2 to be 1`. The refusal is held by `gate()`, not by timing (`order-detail.spec.ts`, id 98 block).
5. **Backlog 201.**
   - Rule: link only to an entry on the timeline, and render nothing otherwise.
   - V04 (an `@else` that prints `caused by {{ event.causationId }}` for a command cause) fails, `expected 'Credit hold of 1 242.50 EUR approvedc…' not to match /caused by/i`. P12 fails.
   - Citations verified: #8 `apps/web/src/features/orders/order-detail-view.tsx:178-184` (`{cause ? (...) : null}`) and `src/lib/order-detail.ts:101-104`; #7 `apps/web/app/pages/orders/[id].vue:113-115` (`causingEvent`) and `:245` (`v-if`). Both render nothing for an unresolved cause, the same as #9.
6. **Id 106.** P04 fails, `render 1: the ids differ from the first render's (a module-level counter keeps counting)`.
7. **Ids 100/102.**
   - `python3 .arm/web29s2/ids100_102.py` re-run: output identical to `.arm/web29s2/ids100_102.out` (35 hits). I checked each of the 35 against the record's five groups, 8 + 14 + 5 + 7 + 1, and they reconcile.
   - Broader search of my own (every f-string with a money-like interpolation anywhere in `services/*/src` without `format_money`, plus `.format` and `%`): 20 hits. None reaches a problem document beyond the record's list:
     - notification templates use `money_text`;
     - `summaries.py:57` is a unit count;
     - `summaries.py:84` is a `format_money` result;
     - `seed/.../deterministic.py:66` is a check digit;
     - the rest are the record's snapshot invariants and `invoice_wire.py:74`.
   - The leader's disposition of `invoice_wire.py:74` is not contested.
8. **The instrument.** A3 is B2. A4: P16 fails, `reviewed labels that no failing run produces ...: expected [ 'A label nobody produces' ]`; P17 fails. Item 12: V08 (an `injectMutation` added to `[id].page.ts`) fails, `a new consumer of the query client: script it in ACTIONS ... then update REQUEST_UNITS`; P19 fails, `a control the sweep has not been told about: button:Reload`.
9. **Arms.** See the table below. The pre-interruption sweep arms P16–P19 exercise `[id].page.ts` and `pager.ts` (the sweep renders every page), both edited at 10:46 after those arms ran. The record did not re-run them; I did, and all four fail as claimed.
10. **Gates.** Below.

### Arms re-run by me (driver `.arm/web29r2/s2/arm.py`: backup with sha256, one mutation, the ONE named test under `setsid --wait timeout -k 10 420`, verdict from the JSON reporter artifact, restore by `cp`, `cmp`, `.vite`/`.angular` cleared)

| id | mutation | verdict | first failure (verbatim, trimmed) | sha256 (12) | cmp |
|---|---|---|---|---|---|
| V01 | money.ts: `fraction.length > exponent ||` deleted | FAILED | `expected 1005 to be undefined` | 42f00b4bbc10 | identical |
| V02 | place.page.ts: `[attr.step]` removed from the unit-price input only | FAILED (6) | `expected null to be '0.01'` | 540b088e59a0 | identical |
| V03 | place.page.ts: `wire.lineDiscount = lineDiscount + 1` (payload corruption) | FAILED | `expected '{"retailerCode":"CarrefourEs","compan…' to be ...` | 540b088e59a0 | identical |
| V04 | [id].page.ts: "caused by <causationId>" for a command cause | FAILED | `... not to match /caused by/i` | 247503c3aaa6 | identical |
| V05 | order-stream-client.ts: timeline handler checks the update set | FAILED | `expected [ …(3) ] to deeply equal [ …(4) ]` | bb9c06745c30 | identical |
| V06 | pager.ts: `whole = total / pageSize` | FAILED (5) | `expected 1.05 to be 1` | d3d3c46eece2 | identical |
| V07 | index.page.ts: aliased `setTimeout`, request at 1800 ms | **SURVIVED** | (B2) | ee8e63431347 | identical |
| V07b | the same, whole sweep file | FAILED (18), action phases only | `/orders \| sign-out: requests with no success body: expected [ 'GET /api/stock' ]` | ee8e63431347 | identical |
| V07c | the same at 29 000 ms, whole sweep file | **SURVIVED** 62/62 | (B2) | ee8e63431347 | identical |
| V07d | literal `setTimeout(` at 1800 ms (control) | FAILED | `a timer the late watch has not been checked against` | ee8e63431347 | identical |
| V08 | [id].page.ts: a second `injectMutation` | FAILED | `a new consumer of the query client: script it in ACTIONS ...` | 247503c3aaa6 | identical |
| V09 | bff-contract.ts: same-tick request with a refused cookie | **SURVIVED** | (A1) | 5a8fe03d3850 | identical |
| M01 | (record) float parse | FAILED | `0.29: expected 28 to be 29` | 42f00b4bbc10 | identical |
| M06 | (record) literal step on both inputs | FAILED (4) | `expected '0.01' to be '1'` | 540b088e59a0 | identical |
| P01 | (record) `Number(typed) * 100` | FAILED (4) | `the exact bytes the BFF receives: expected ...` | 540b088e59a0 | identical |
| P04 | (record) module counter | FAILED | `render 1: the ids differ from the first render's ...` | 540b088e59a0 | identical |
| P09 | (record) shared de-dup set | FAILED (2) | `expected [ …(3) ] to deeply equal [ …(4) ]` | bb9c06745c30 | identical |
| P10 | (record) no gave-up re-check | FAILED | `giving up asked the order again, through a query: expected false to be true` | 247503c3aaa6 | identical |
| P11 | (record) Retry reopens blindly | FAILED | `a refusal must never reopen a stream: expected 2 to be 1` | 247503c3aaa6 | identical |
| P12 | (record) false cause link | FAILED (2) | `expected [ …(2) ] to deeply equal [ Array(1) ]` | 1682c5e54446 | identical |
| P13 | (record) pending not filled by stream | FAILED | `the frame made the page read the order again: expected 1 to be 2` | 247503c3aaa6 | identical |
| P15 | (record) resync ignored | FAILED | `expected 1 to be 2` | 247503c3aaa6 | identical |
| P16 | (record) stale label | FAILED | `reviewed labels that no failing run produces ...` | d3b5d1111e8e | identical |
| P17 | (record) label reworded | FAILED | `/orders/place: load failures the user does not see in the problem's own words ...` | 540b088e59a0 | identical |
| P18 | (record) `AbortSignal.timeout(3000)` | FAILED | `timers longer than the 1500 ms late watch that no reviewed class explains ...` | ee8e63431347 | identical |
| P19 | (record) unscripted Reload button | FAILED | `a control the sweep has not been told about: button:Reload` | ee8e63431347 | identical |
| P26 | (record) reconnect by hand | FAILED | `expected undefined to be 'c1'` | bb9c06745c30 | identical |
| R02 | (record) request misses the route | FAILED | `the premise: the same-tick requests did not reach the stream route ...: expected +0 to be 3` | 5a8fe03d3850 | identical |

After every arm and the parity script, `sha256sum -c .arm/web29r2/s2/sha_start.txt` reports 13 of 13 OK (the 13 files mutated, including `bff-contract.ts`, `stream.get.ts`, the web JSON and the Python table). No new file was left behind; no tracked path was deleted or moved.

### Gates (`.arm/web29r2/gates.sh`, under `setsid --wait timeout -k 10 1500`; logs `.arm/web29r2/gate_*.log`)

- `install --frozen-lockfile`: exit 0.
- `run types:check`: exit 0.
- `run test:ci`: exit 0, **28 files / 457 tests passed**. This matches the record (stage 1's 18 / 253, +10 files, +204 tests).
- `run build`: exit 0.
- `uv run pytest packages/shared_kernel/tests/test_currency_exponent.py`: 15 passed.
- I did not re-run the full `quality.sh`. The leader's run is `.arm/phase16/q2.log`, exit 0 ("quality.sh: all gates passed"). The production build used for the live probes is the one from my gate run, built before any arm, and the sources are byte-identical to it (13/13 sha256).
- Live probes: `docker ps` before and after shows only `otcpy-n8n` (as found). The build was served on port 3000; `ss -ltnp` local addresses are identical before and after ("PORTS-IDENTICAL"), and the server was stopped by its PID. `git status --short` is identical to `.arm/phase16/status_before_review2.txt` ("GIT-IDENTICAL"). `feature_list.json` was not edited.

### CHECKPOINTS.md (boxes applicable to a stage review)

- [x] C2: one feature `in_progress` (29). Not edited by me.
- [ ] C3, "no stray debug logging": `stream.get.ts:12` logs on every stream request in production. It is deliberate and documented, so it is advisory A5, not a defect.
- [x] C3: money in the web is integer minor units, with no float, `/` or `Intl` in the money population (census A4, arms V01, M01, R-no-float).
- [x] C4: the web gates pass (28 / 457). The full `quality.sh` is the leader's (exit 0).
- [ ] C4 "verification is real": B2 (the A3 guard is defeated by an app timer) and B1 (no test drives a bad input).
- [x] C5: Claude did not commit. Artifacts are under the git-ignored `.arm/`.
- [x] C6: n/a (`sdd: false`).
- [x] C7: `specs/shared/` is untouched. The R55 web-half test is named in the matrix row's words; the leader edits the matrix.
- [ ] C7 ledger: the #7/#8 halves lack file:line, and two rows are wrong (A3).

### What must change before re-review

1. **B1:** a malformed money text (`validity.badInput`) in the unit-price or line-discount box is refused in words and nothing is sent. Add a test for both fields, armed by deleting the branch. Re-run P01, V02 and V03, and the live bytes probe (`.arm/web29r2/s2/live/bytes.mjs`, the `"1-2"`, `"12e"`, `"19.99-"` and discount `"5-"` cases must send nothing).
2. **B2:** `LONG_TIMER_CLASSES` matches library-origin timers only. V07 and V07c must fail, naming the app timer; P18 must still fail; the classes must still all be seen.
3. In the same round, record-only: correct the ledger rows (A3) and name the second `/` (A4). A1, A2 and A5 are the implementer's choice, each with its recommendation above.

No finding is rooted in `specs/shared/`, so no SA-n or backlog routing is owed.

## Stage 2 re-review (fix round 1)

Scope: `progress/brief_review_web_app_stage2_round2.md`. Its stopping rule was written by the leader before this review. The items in scope are B1 (as a class over every `type="number"` input), B2, A1, A2 and item 8. A3 and A4 are record corrections, checked as advisories only. A5 was accepted by the leader and is not a ground. The record under review is `progress/impl_web_app.md` "Stage 2 — fix round 1" (lines 664–789).

Reviewer artifacts are in `.arm/web29r3/s2r1/`:

- `arm.py` is a copy of the implementer's driver with only the directory changed. `defs.py` loads `web29s2/defs_pages.py` and `web29s2f1/defs_g.py`, and adds my own arms H01–H05.
- `results.jsonl` holds 22 rows; each arm also has `<id>/out.json` and `<id>/log`.
- `prefix/` holds the pre-fix backup and builds. `live/` holds the probes and their outputs. `gate_*.log` and `gates.summary` are the gate run.

Full suite: I ran the four section-7 commands once, plus the lint step, which is `--if-present` and is a no-op. I did not run the whole of `quality.sh`.

### Verdict: **APPROVED** (stage 2)

No finding meets the stopping rule.

- **Rule (a):** B1 holds for all three `type="number"` inputs, live and under arms. B2 holds: V07, V07c and P18 fail, naming the timer. A1 holds: V09 fails. A2 holds: F04 fails, and the live pager claims no count after a failed poll. Item 8 holds: the mechanism is reproduced on the pre-fix production build, and the fix is clean in 113 cold runs (below).
- **Rule (b):** no live money or product defect was found in the changed code.
- **Rule (c):** every arm the record claims fails, and each message names its claim. Two arms survive: F08 is an instrument control, as the record says, and my own H01 is an advisory (below). Neither breaks a claim the record makes about the product.

Feature 29 stays `in_progress`: stages 3 and 4 remain. `feature_list.json` and `progress/history.md` are not edited, because no feature closes here.

### Item 8 (the centre of this round)

**1. The mechanism is true, shown at the engine level.** `live/bare2.mjs` uses a bare `<input type=number step=0.01>` in Chromium 151.0.7922.34. After typing the keys "19.", `value` is `"19"`. Then one change is applied to the input, and the keys "99" are typed:

| Change after "19." | Final text |
|---|---|
| nothing | `19.99` |
| `value = value` (the same string) | `9919` |
| `setAttribute('step', '0.001')` | `19.99` |
| `setAttribute('placeholder', …)` | `19.99` |
| `aria-invalid` | `19.99` |
| `id` | `19.99` |

The same reassignment turns `"0."` + `"29"` into `290`. Only an assignment to `value` disturbs the text on screen. The other writes the page makes to these inputs (`[attr.step]` on a currency change, `[attr.placeholder]` when a catalogue price arrives, `aria-invalid`, `[id]`) do not.

**2. Reproduced on the pre-fix code, in the production build, in Chromium.**

- I took a backup of `place.page.ts` to `prefix/place.page.ts.bak` (sha256 `230593fdeca7`) and changed all three `[appDraftValue]="line.…"` back to `[value]="line.…"`. Then I ran `pnpm run build` (exit 0).
- Every run used a fresh server and a fresh browser, with every `/api/**` answered by `page.route`. "Sent" below is the body the browser posts to the BFF.
- `live/keys.mjs` types as soon as the box is attached, without waiting for the page to settle. `run_bytes.sh` runs the stage 2 review's `bytes.mjs`.

Pre-fix results (the full per-run lines are in `live/cfg_prefix.out`, `cfg_prefix_b.out`, `bytesruns_prefix.out` and `keys_prefix.out`):

| Configuration (cold runs) | Scrambled | What was shown and sent |
|---|---|---|
| `bytes.mjs`, 8 runs, first three rows | 8 rows of 24 | "19.99" scrambled in run 8 (`9919` shown, `"unitPrice":991900`). "0.29" scrambled in runs 6 and 8 (`290`, `29000`). BHD "1.005" scrambled in runs 1, 2, 3, 4 and 6 (`0051` shown, `"unitPrice":51000`). |
| unit price "19.99", render lag 150 ms, key gap 60 ms | 5/5 | every run `9919`, `"unitPrice":991900` |
| discount "0.29", render lag 60 ms, key gap 40 ms | 5/5 | every run `290`, `"lineDiscount":29000` |
| unit price, no lag, key gap 0 | 2/5 | runs 1 and 3 `9919` / 991900; runs 2, 4 and 5 correct |
| unit price, CPU throttle ×6, key gap 0 | 3/5 | runs 1, 2 and 3 `9919` / 991900; runs 4 and 5 correct |
| discount, CPU throttle ×6, key gap 0 | 4/5 | runs 1, 3, 4 and 5 `290` / 29000; run 2 correct |
| unit price, key gap 100 ms, catalogue held 150 ms | 0/5 | all correct |
| first batch: natural, throttle ×6 and lag 150 at key gap 40 ms, × unit/discount/quantity, 5 runs each | 0/45 | all correct, but **every** run logged a same-text assignment after every key (e.g. `"19" over "19"`, `"19.9" over "19.9"`) |

So the cause, an assignment of the held text, is present on every keystroke. The effect, the scramble, needs a render to land between the "." and the next key, so it is timing-dependent.

I restored the file by `cp` (`cmp` identical, sha256 `230593fdeca7`), cleared `.vite` and `.angular`, and rebuilt (exit 0).

**3. The fixed build, same configurations.** `cfg_fixed.out`, `bytesruns_fixed.out`, `keys_fixed.out`:

| Configuration (cold runs) | Result |
|---|---|
| `bytes.mjs`, 8 runs | 24 of 24 rows correct: `19.99`/1999, `0.29`/29, `1.005`/1005 |
| lag 150 / gap 60, unit price | 5/5 correct |
| lag 60 / gap 40, discount | 5/5 correct |
| gap 0, unit price | 5/5 correct |
| throttle ×6, gap 0, unit price | 5/5 correct |
| throttle ×6, gap 0, discount | 5/5 correct |
| gap 100, unit price | 5/5 correct |
| first batch (45 runs) | 45/45 correct, each with the typed text sent exactly |

In all of these, no assignment was logged while typing. The only write is the quantity box's initial `"1" over ""`. In every run that submitted, the text survived a 503 answer to the submit (`shownAfterSubmitFailure`).

Total: 113 cold runs or rows on the fixed build, 0 scrambled.

**4. Is the fix complete for every path that writes those inputs?** Yes. The enumeration is in `place.page.ts`; the writers of `lines` are at `:311`, `:314`, `:317`, `:323` and `:334`.

- **The `.value` writer.** The directive is the only writer of `.value` on the three boxes. `grep -rn "\.value\s*=" src/app` outside specs and testing gives one hit, `components/draft-value.ts:20`. `BrnInput` (the spartan `hlmInput` host directive) binds only `id` and data/aria attributes.
- **A currency change.** It changes `[attr.step]` and `[attr.placeholder]` only, and neither disturbs the text (probe above).
- **A catalogue price arriving.** It changes `[attr.placeholder]` and swaps the product cell between input and select. The number boxes are not recreated: `@for … track line.key`.
- **A line added or removed.** These are `:311` and `:314`. They create or remove rows by key, and no existing box's draft changes.
- **A draft reset after a submit failure.** There is no such path: `placeOrder` has no `onError`, and `onSettled` only clears `submitting`. The live 503 runs show the text kept.
- **The demo button** (`:334`) gives the line a new key, so it is a new element written once.
- **The text fields** (retailer, company, currency, notes, product code) keep `[value]`. That is correct: a text input's `value` equals its on-screen text, so a same-text assignment does not move the caret (HTML: the cursor moves only when the value changes).

**5. Recommendation: the cause-level guard is the right binding guard for stage 2. Carry the Chromium effect check to feature 32 as an acceptance item; do not add a browser to `src/build/`.**

The evidence for the cause-level guard:

- The cause is necessary: no other write the page makes disturbs the text (finding 1).
- The cause is deterministic in jsdom: G01–G04 fail on every run, and `R-typing` fails on the redundant writes alone.
- The effect is timing-dependent in Chromium without injected lag: 0/5 to 4/5 above. A plain Chromium test would therefore be a flaky detector.
- With the init-script render lag (150 ms lag and 60 ms key gap for "19.99"; 60 ms lag and 40 ms key gap for "0.29"), the effect is 5/5 before the fix and 0/5 after it. That is a deterministic recipe for an effect-level test.

Why it belongs to feature 32 and not to `src/build/`:

- `apps/web/package.json` has no Playwright. Every probe in this phase imports `playwright-core` from #7's checkout. Adding it to the `src/build/` harness is a dependency decision.
- Feature 32 (`e2e_playwright`, phase 19, `pending`) will bring Playwright to this repository. This is the "half that depends on code not yet built" (CLAUDE.md).

**Routing (for the leader to file; I do not write `feature_list.json`):** add an acceptance item to feature 32:

> typing "19.99" into the unit price and "0.29" into the line discount of a cold `/orders/place`, with an init-script render lag (150 ms, key gap 60 ms; 60 ms, key gap 40 ms), shows and sends exactly the typed amount (1999, 29); armed by restoring `[value]` on the three number inputs (must show 9919/290).

Optional and cheap: strengthen `redundantWrites` in `place-order.spec.ts:158` to record **every** assignment made while typing, not only same-text ones. Any assignment moves a number input's caret.

### Arms re-run by me (`.arm/web29r3/s2r1/arm.py`)

Protocol for every arm: back up with sha256, apply one mutation, and run the ONE named test under `setsid --wait timeout -k 10`. The verdict is read from the JSON reporter artifact. Then restore by `cp`, check with `cmp`, and clear `.vite` and `.angular`; N1_prod and R03 also rebuild.

| id | mutation | verdict (passed/failed) | first failure (verbatim, trimmed) | sha256 (12) | cmp |
|---|---|---|---|---|---|
| F01 | `typeMoney`: the badInput branch dead for unitPrice | FAILED (2/2) | `nothing may be sent: no catalogue-price fallback, no "no discount": expected [ { key: 'POST /api/orders', …(1) } ] to have a length of +0 but got 1` | 230593fdeca7 | identical |
| F02 | the same for lineDiscount | FAILED (3/1) | the F01 message | 230593fdeca7 | identical |
| F03 | `parseQuantity`: an empty text reads as 1 | FAILED (0/1) | `expected [ { key: 'POST /api/orders', …(1) } ] to have a length of +0 but got 1` | 230593fdeca7 | identical |
| H03 (mine, sibling identifier) | the badInput flag is set on the OTHER money field | FAILED (2/2) | `expected null to be 'true'` (the typed box is not `aria-invalid`) | 230593fdeca7 | identical |
| H04 (mine, a stale premise) | a parseable retype no longer clears the flag | FAILED (2/2) | `expected [] to have a length of 1 but got +0` | 230593fdeca7 | identical |
| F04 | `counts` ignores `isError()` | FAILED (0/1) | `TanStack keeps the last data after a failed refetch; the pager must not keep claiming its count: expected 'Page 1 of 3 · 45 orders' to be ''` | 9bb7067ec07c | identical |
| V07 | aliased `setTimeout`, request at 1800 ms | FAILED (0/1) | `timers longer than the 1500 ms late watch that no reviewed class explains ...: ["setTimeout(1800) from app code (OrdersListPage, /orders/index.page.ts)"]` | 9bb7067ec07c | identical |
| V07c | the same at 29 000 ms, whole sweep file | FAILED (61/1) | `...: ["setTimeout(29000) from app code (OrdersListPage, /orders/index.page.ts)"]` | 9bb7067ec07c | identical |
| P18 | `AbortSignal.timeout(3000)` | FAILED (0/1) | `...: ["AbortSignal.timeout(3000) from app code (OrdersListPage, /orders/index.page.ts)"]` | 9bb7067ec07c | identical |
| F08 (control) | `fromQueryCore` made `() => true`, plus V07c's 29 s request | SURVIVED (1/0) | (control, see below) | c7f2e34df035 / 9bb7067ec07c | identical |
| H05 (mine, a form the instrument does not see) | `timer(29_000).subscribe(() => void this.api.listStock())` from rxjs: a library-asked `setInterval` in the staleTime band | FAILED (0/1) | `...: ["setInterval(29000) from library code (Object.setInterval, .../node_modules/.pnpm/rxjs@7.8.2/.../intervalProvider.js)"]` | 9bb7067ec07c | identical |
| V09 | the same-tick request carries a refused cookie | FAILED (0/1) | `the premise: the same-tick requests did not reach the stream route, so nothing below says anything about it: expected +0 to be 3` | 5a8fe03d3850 | identical |
| N1_line_deleted | the `if (res.destroyed)` block deleted | FAILED (0/1) | `the upstream connection stayed open for a client that had already left: expected 3 to be +0` | c81d47c227e5 | identical |
| N1_prod | the same, production suite | FAILED (0/1) | the same | c81d47c227e5 | identical, rebuilt |
| R03 | the `console.debug` line deleted, production suite | FAILED (0/1) | the V09 message | c81d47c227e5 | identical, rebuilt |
| G01 | `[value]` instead of `[appDraftValue]` on quantity | FAILED (3/1) | `an assignment of the text the input already holds moves the caret of a number input: expected [ '2', '25' ] to deeply equal []` | 230593fdeca7 | identical |
| G02 | the same on unit price | FAILED (3/1) | `...: expected [ '1', '19', '19.9', '19.99' ] to deeply equal []` | 230593fdeca7 | identical |
| G03 | the same on line discount | FAILED (3/1) | `...: expected [ '0', '0.2', '0.29' ] to deeply equal []` | 230593fdeca7 | identical |
| G04 | directive always assigns | FAILED (1/3) | `...: expected [ '2', '25' ] to deeply equal []` | 5bd0b086180b | identical |
| G05 | directive never assigns | FAILED (0/1) | `expected '' to be '249.99'` | 5bd0b086180b | identical |
| H02 (mine, corrupt the written field) | the directive writes `text + '0'` | FAILED (3/1) | `expected '249.990' to be '249.99'` | 5bd0b086180b | identical |
| H01 (mine) | the directive assigns only on its first run | **SURVIVED** (4/0) | (advisory 2) | 5bd0b086180b | identical |

After all arms, `sha256sum -c .arm/web29r3/s2r1/sha_start.txt` reports 9 of 9 OK, and every hash equals the record's. The production build in `dist/` was last rebuilt from the restored source (R03's rebuild).

**F08, judged.** I agree with the record that F08 is an instrument control and not a guard. It replaces the class predicate itself with `true`, which removes the claim rather than breaking the product. It shows the `fromQueryCore` condition is what holds the line: V07c fails with the condition and passes without it. H05 is the stronger check of the new rule. A request an app schedules through another library (rxjs) has `origin === 'library'` and a delay inside the staleTime band. It is still refused, because it was not asked by `@tanstack/query-core`.

### B1, A1 and A2 live

- **B1.** The stage 2 review's `bytes.mjs` and the implementer's variant, which adds quantity rows, were run on the fixed build (`live/bytes.out`, `live/bytes_impl.out`):
  - Controls hold: "19.99" sent `"unitPrice":1999`, "0.29" sent `"unitPrice":29`, BHD "1.005" sent `"unitPrice":1005` with step `0.001`.
  - Unit price "19.99-", "1-2" and "12e": `priceBadInput:true`, problem "Enter an amount with at most 2 decimals (EUR).", `(nothing sent)`.
  - Discount "5-" and "0.5-": `discountBadInput:true`, the same problem, nothing sent.
  - Quantity "1-2" and "12e": "Enter a whole number of at least 1.", nothing sent.
  - **Population**, `grep -rnE "type=[\"']?number|type: *['\"]number|'number'\)|\.type *= *['\"]number" src scripts index.html` outside specs, gives 6 hits:
    - `place.page.ts:146` (quantity), `:153` (unit price) and `:160` (line discount): the three inputs.
    - `place.page.ts:40`, `components/draft-value.ts:6` and `lib/currency-exponent.ts:28`: doc comments.
  - The class is three of three.
- **A1.** `stream.get.ts:12-15`: the marker is logged after `readSession` and the 401 return, and no second line was added. V09, R03 and both N1 arms fail (table above).
- **A2.** `index.page.ts:150` reads `counts = isError() ? undefined : data()?.page`. `live/listpoll.out` re-runs the review's probe. `live/listpoll2.out` is my variant, which reads the DOM in one `evaluate`: the original's first line samples its fields at different times, because `textContent()` auto-waits.
  - After the first read: `"pager":"Page 1 of 3 · 45 orders","error":null,"table":1,"nextEnabled":true`.
  - After a poll failed: `"pager":"","error":"The read model is down (probe).","table":0,"nextEnabled":false`.

### A3 and A4 (record only, advisory)

- **A3.** The two rows I showed wrong are corrected, and I re-read their citations in the checkouts:
  - #7 `apps/web/app/lib/money.ts:16` points at `packages/shared-kernel/src/domain/currency-exponent.ts`.
  - #8 `tests/SharedKernel.UnitTests/CurrencyExponentWebParityTests.cs:30` reads `apps/web/src/lib/currency-exponents.json`.
  - #7 `app/pages/orders/place.vue:348-350` builds `` `product-select-field-${index}` ``.
  - #8 `place-order-form.tsx:371` has `useId()`, and `:69` has `nextLineKeyRef`.
  - The new pager row, #8 `orders-list.tsx:121` (`orders.isError ? null : <Pager …>`), is also verified.
  - #7's `currency-exponent.spec.ts` and #8's `currency-exponent.test.ts` exist at the cited paths.
- **A4.** The second `/` (`[id].page.ts:262`, `milliseconds / 1000`) is named in the record.

### Advisories carried to stage 3 (not grounds under the stopping rule; each with a recommendation)

1. **The B1 and item 8 class comes back in stage 3's money inputs.** Register payment, replenish and credits will add number boxes. No guard enumerates the `type="number"` population and requires both `[appDraftValue]` and a badInput-aware handler. A fourth input written with `[value]` and `$event.target.value` would pass every current test.
   - Recommend for stage 3: a population guard over the templates (every `type="number"` carries `appDraftValue` and a handler that reads `validity.badInput`), armed by adding such an input. Or use #8's text input with `inputmode="decimal"` for the new boxes.
2. **H01: the "outside" test proves creation, not an outside change to an existing box.** The test is "a draft changed from OUTSIDE the input (the demo button) is still written into it". The demo button gives the line a new key, so the box is new. A directive that writes only on its first run passes all four `R-typing` tests.
   - This is not a live defect: the five writers of `lines` enumerated above include no path that changes an existing box's draft from outside.
   - Recommend renaming the test to what it proves. If stage 3 adds such a path (a reset, a reformat on currency change), change an existing line in the test, and arm it with H01 (`.arm/web29r3/s2r1/defs.py`).
3. **Instrument note: `bytes.mjs` reads the running total before the re-render.** It shows `38.00 EUR` for "19.99" × 2 in 7 of 8 fixed runs. `live/total.mjs`, run three times, reads the total right after typing and after 500 ms, and gets `39.98 EUR` both times with the box at `19.99`. The page is correct; the probe's sample is early, as the record says.
4. **The cause-level guard could count every write made while typing, not only same-text writes** (see item 8, point 5). This is optional.
5. **#7 (not this repository).** The record notes that #7 uses `type="number"` money boxes (`place.vue:381,395`) and very likely has B1's gap. #7 is complete and is touched only at the maintainer's request. I recommend the leader mention it at the gate; I did not probe it.

### Gates (`.arm/web29r3/s2r1/gates.sh`, each under `setsid --wait timeout -k 10`)

- `install --frozen-lockfile`: exit 0.
- `run --if-present lint`: exit 0 (no script).
- `run types:check`: exit 0.
- `run test:ci`: exit 0, **Test Files 28 passed (28), Tests 466 passed (466)**, from the default reporter in `gate_run_test_ci.log`. My extra `-- --reporter=json` argument did not produce the JSON file, and the count is the full population.
- `run build`: exit 0.
- `uv run pytest packages/shared_kernel/tests/test_currency_exponent.py`: 15 passed.

The counts reconcile: stage 2's 457, plus 5 from round 1 (`R-bad-input`: two `it.each` rows, quantity and total; the A2 test), plus 4 from `R-typing` (three `it.each` rows and the demo-button test), is 466 tests, in the same 28 files.

Housekeeping:

- `docker ps` shows only `otcpy-n8n`, before and after.
- `ss -ltn` local addresses are identical before and after, and nothing listens on 3010. Every server I started was stopped by its PID. One server, started with a wrong cwd in a compound command, was found by `ss -ltnp` and stopped by its PID.
- `git status --short` is identical to my start snapshot. It equals `.arm/phase16/status_before_review3.txt` except for the leader's own untracked brief, `progress/brief_review_web_app_stage2_round2.md`, which was already present when I started.

### CHECKPOINTS.md (boxes applicable to this scoped re-review)

- [x] C2: one feature `in_progress` (29). Not edited by me.
- [x] C3, "no stray debug logging": `stream.get.ts:15` `console.debug(STREAM_ROUTE_ENTERED)` is A5, accepted by the leader with a re-open trigger, and recorded in the record.
- [x] C3: money in the web is integer minor units. Malformed text is refused, and the typed text reaches the wire exactly (live, both builds).
- [x] C4: the web gates pass (28 / 466). Every claimed arm fails with a message naming its claim. The two survivors are classified: F08 is a control, H01 is advisory 2.
- [x] C5: Claude did not commit. All artifacts are under the git-ignored `.arm/`.
- [x] C6: n/a (`sdd: false`).
- [x] C7: `specs/shared/` is untouched. The ledger rows now carry a file:line per half (A3, verified).

No finding is rooted in `specs/shared/`, so no SA-n is owed. One routing item is for the leader to file: the Chromium keystroke acceptance item on feature 32 (`e2e_playwright`), worded above.

---

## Stage 3 review

**Verdict: REJECTED** (4 blocking findings, 9 advisories). This is rejection round 1 for stage 3. Feature 29 stays `in_progress` (I did not edit `feature_list.json`; stage 4 is still owed, so no history entry is due).

**The money path is correct.** Real Chromium against the production build, through the BFF, to a stub Gateway that recorded raw bytes, sent exactly the typed amount in the invoice's exponent in every case. 4 blocking findings remain. One is a product defect found live: the age filter silently drops unreadable text. One is a number-box guard with unclassified survivors. Two are test fixtures or titles that let an armed mutation pass.

Process: full group (Register payment parses money). Brief `progress/brief_review_web_app_stage3.md`. Every artifact is in `.arm/web29r4/s3/`: `defs.py`, `arm.py` (the implementer's driver, retargeted), `results.jsonl` (52 rows), `logs/`, and `live/`.

### What I ran, and what I did not

- **Gates** (`.arm/web29r4/s3/gates.sh`, each under `setsid --wait timeout -k 10`; `logs/gates.txt`): install, lint (no script), types:check, test:ci and build all exit 0. `uv run pytest packages/shared_kernel/tests/test_currency_exponent.py` gives 15 passed.
  - **Test Files 32 passed (32), Tests 644 passed (644).**
  - Reconciled per file against stage 2's gate log (`.arm/web29r3/s2r1/gate_run_test_ci.log`): the only differences are 4 new files (billing 55, stock 39, number-boxes 23, money-bytes 7) and the sweep going from 62 to 116 (+54). 466 + 124 + 54 = 644. Every other file has the same count, `place-order.spec.ts` included (42).
- I did not re-run the full sweep or the whole suite except through the gate above.
- **Arms:** 52 rows. 23 are re-runs of the implementer's arms, across N/S/B/BB/W. 15 are stage 2's arms on the place-order boxes (P01, V02, V03, G01–G05, F01–F03, F06), including re-targeted variants. 14 are my own.
  - `cmp` is identical on every row.
  - `sha256sum -c .arm/web29r4/s3/sha_start.txt` gives 12 of 12 OK at the end. The hashes equal the record's (`4d00787da8bc` billing, `1d8b9e156d35` stock, `6264020e409f` place, `5bd0b086180b` draft-value, `f60a7686b1c6` gateway).
- **Live run:** `live/stub-gateway.mjs` on 3911, `node dist/analog/server/index.mjs` on 3010 (the build from my gate run), and Chromium through playwright-core from #7's `node_modules` (read only).
  - Scripts: `live/probe.mjs`, `reopen.mjs`, `reopen2.mjs`, `age.mjs`. Outputs: `*.out` and `stale.png`.
  - Housekeeping: `docker ps` showed only `otcpy-n8n` before and after. The `ss -ltnp` local addresses are identical before and after; both processes were stopped by process group. `git status --short` is identical before and after.

### Q1. Money, bytes at the BFF (live, `live/probe.out`)

The stub's totals differ from the typed text, so no row can pass by prefill. The bytes below are what the stub Gateway received through the BFF.

| Invoice, prefill | Typed | Gateway received / shown |
|---|---|---|
| EUR, prefill `1242.50` | `0.29` | `"amount":29` |
| EUR, prefill `1242.50` | `19.99` | `1999` |
| BHD, prefill `2.005`, step `0.001` | `1.005` | `1005` |
| BHD | `0.29` | `290` (the invoice's exponent) |
| JPY, prefill `5000`, step `1` | `1999` | `1999` |
| JPY | `19.99` | refused: "Amount: enter a whole amount (JPY)." |
| EUR | `1-2`, `12e` | `badInput:true`; "Amount: the browser could not read what was typed. Enter an amount with at most 2 decimals (EUR)."; nothing sent |
| EUR | `1e3`, `-1`, `1.005`, `90071992547409.92` | refused in words, nothing sent |
| EUR, total MAX_SAFE | `90071992547409.91` | `9007199254740991` exactly |
| EUR, the same remittance twice | | 201 "recorded (HTTP 201)…", then 200 "was already recorded (HTTP 200). Nothing new was created: this was an idempotent replay." |

Replenish `units`:

- `1.5`, `1e3`, `0` and `9007199254740993` are refused with "Units to add: enter a whole number of at least 1."
- `1-2` gives the unreadable sentence.
- `7` sent `{"companyCode":"BAUWERK","lines":[{"productCode":"PRD-0001","units":7}]}`.

**Are the seam/BFF tests sound?** BB1, BB2 and BB3 re-run KILLED. My R2 (`padEnd` changed to `padStart` in `money.ts`) KILLED (the `.5` row). But see **B-S3-3**: the 0.29, BHD and JPY rows of `R-payment-bytes` pass with typing ignored. Also, R3 (the BFF re-serialising through `JSON.parse`/`JSON.stringify`) SURVIVED (advisory A3).

### Q2. Register payment vs `openapi.yaml` 664–760

- The body is exactly `RegisterPaymentRequest`: `paymentReference`, `amount{amount,currency}`, `valueDate` in the wire instant form, and `source:"operator"` (the live bytes above).
- There is no idempotency header, which is correct: the spec makes `paymentReference` the key.
- The 201 and 200 sentences are chosen by `outcome`, each shows its status, and they match the spec's table. The prefill is the invoice's exact total (the spec requires equality, R49). The suggested reference follows the spec example's shape and is at most 30 characters.
- "The order completes once the saga catches up: … moves to paid and then completed" is what the description states (R47).
- I found nothing the page says about a payment that the spec does not guarantee.

One non-payment sentence over-states the spec (A4).

### Q3. #8 id 101

- **Product:** `stock/index.page.ts:222-224` takes `productName` (trimmed) first, then the catalogue, else `undefined`. The template shows the code once (`:137-141`). Live through the stub: `Olive oil 1 L (PRD-0001)` on both companies' rows, and `PRD-0999` alone.
- **Fixtures:** "Olive oil 1 L", "Arroz bomba" and "Rice 5 kg" contain no code, and the codes contain no name, so "never twice" cannot pass by accident.
- **Arms:** I re-ran S2 (code twice), S3 (catalogue wins) and S4 (catalogue failure hides the table); all KILLED. W8 (catalogue request dropped from the load) KILLED.
- **Acceptance met:** avoided, as the record says.

### Q4. The number-box guard: **B-S3-2**

My attacks, each run on the whole `number-boxes.spec.ts`:

| id | form | guard | covered elsewhere? |
|---|---|---|---|
| R5 | new `components/ghost-box.ts`, `import { Component as Cmp }`, `@Cmp({template:'<input type="number" …>'})` | **SURVIVED** 23/23 | not rendered: nothing |
| R6 | stock template `@if (rows().length<page()+1000) { <input type="number" data-testid="ghost" /> }`: Angular compiles it, but the DOM HTML parser reads `<page()+1000)` as a tag and swallows the input as attributes | **SURVIVED** 23/23 | R6b: the sweep's control census FAILS ("a control the sweep has not been told about: input:"), as an unknown control, not as a number box |
| R7 | `<input bind-type="'number'" …>` (Angular's `bind-` prefix, `compiler.mjs` `BIND_NAME_REGEXP`) | **SURVIVED** 23/23 | R7b: the census fails the same way. **The header claims a bound type "fails by name"** |
| R8 | `[valueAsNumber]="+amountDraft()"` beside `[appDraftValue]` (a second writer of the value, the B1 hazard) | **SURVIVED** | R8b: `R-typing (stage 3)` **SURVIVED**, because `writesWhileTyping` hooks only the `value` setter. R8c: all 33 `R-payment` tests **SURVIVED** |

The implementer's arms N1, N2a, N3b and N6b re-ran KILLED.

**The survivors' classifications** (N4a, N5a by design; N7 a negative control; H01 against the renamed test): I agree. N4b and N5b are killed by behaviour, N7 is a control, and H01 is covered by S13b and B18b.

**Is a syntax guard the right instrument? Alone, no.** #7 reached the same conclusion this session (`../order-to-cash-nestjs/progress/review_web_number_inputs.md`). The sweep already renders every page in every state it reaches (`controlsOf`, `page-sweep.ts:292`). R6b and R7b prove it sees forms the syntax half cannot. But it records `tag:name`, not the type, so it forces a review of the control without the number-box rule.

### Q5. The changed place-order message: **B-S3-4**

- **The diff** against stage 2's `place.page.ts` (backup `.arm/web29r3/s2r1/F01_badinput_unitPrice_deleted/bak_0`, sha `230593fdeca7`) has 4 hunks: `unparseable.quantity`, `typeQuantity`, a two-branch problem sentence, and the total ignoring an unreadable quantity.
- **Correctness:** the change is correct for the quantity box. Unit price and line discount keep their sentence; there, deleting badInput is observable (F01 and F02 KILLED).
- **Stage 2 arms re-run:** P01, V02, V03, G01, G02, G03, G04, F01, F02 and F06 KILLED. G05 is NOT-RUN under its old `-t` name, which no longer exists (renamed per H01); retargeted as G05r against the renamed test, it is KILLED (`expected '' to be '249.99'`).
- **Titles:** comparing the stage 2 and stage 3 gate logs:
  - `R-typing`'s three titles were strengthened ("no assignment re-stores it" became "the page makes no assignment to the box while typing"; the counter is now every write).
  - The demo test was renamed per H01.
  - The `R-bad-input` Quantity title gained "(an EMPTY value is refused too, with the plain sentence)".

### Q6. States and sweep

- **States:** both pages hold the request in flight before asserting loading. The pager is empty while loading and after a failed refetch. Re-run: B15 KILLED.
- **Sweep arms re-run:** W2 (the payment error text replaced, the action half), W8 (load population) and W6 (stale label, whole file, 115 passed / 1 failed) all KILLED. The two pages' 6 + 10 actions and the load population (`EXPECTED_LOAD` `/stock`, `/billing`) are in the file.
- **`PRD-0001` in `LABELS`** is fixture data, not a label. It is disclosed, and W6's machinery makes it go stale loudly (A7).

### Q7. Draft writers (H01)

My command: `grep -rnE "(unitsDraft|unitsBad|amountDraft|amountBad|referenceDraft|ageDraft|ageBad)\b" src/app --include=*.ts --exclude=*.spec.ts`, plus every `.set(` on those signals, plus `grep -rnE "\.value\s*=[^=]"` (one hit: `draft-value.ts:20`).

- **Writers:** the result equals the record's section 5. `typeUnits` and `open()` (stock :258-259, :272-273); `typeAmount` and `openPayment()` (billing :382-383, :396-397); `referenceDraft` by its own `(input)` and `openPayment()`; `typeAge` only. `close()` and `closePayment()` write no draft, although the comments at stock :192 and billing :282 say they do (A5).
- **Outside paths:** there are two, `open()` and `openPayment()`. Both are armed for parseable text (S13, S13b, B18, B18b; I re-ran S13 and B18b, both KILLED).
- **Not armed:** an **unreadable** text in the units box is not cleared when the panel moves (A1, live).
- **Reopening the same invoice** resets the amount box in 6 of 6 settled reads (`live/reopen2.out`). One early read in `probe.out` ("prefilled 1.005") was my probe sampling before change detection; it did not reproduce.

### Q8. Arms summary (`results.jsonl`)

- **Implementer's (23), all KILLED:** N1, N2a, N3b, N6b, S2, S3, S4, S7b, S13, S20, B1, B3, B7, B9, B10, B15, B18b, BB1, BB2, BB3, W2, W6, W8.
- **Stage 2's (15):** P01, V02, V03, G01, G02, G03, G04, G05r, F01, F02, F06, F03r and F03s KILLED. G05 is NOT-RUN under its old name. F03 SURVIVED against its named test (B-S3-4).
- **Mine (14):**
  - Money: R1 and R1b SURVIVED (B-S3-3); R1c and R2 KILLED; R3 SURVIVED (A3); R4 SURVIVED (B-S3-3).
  - Guard: R5, R6, R7, R8, R8b and R8c SURVIVED (B-S3-2); R6b and R7b KILLED by the sweep census.

### Blocking findings

**B-S3-1. The age filter silently drops unreadable text in Chromium.**

- **Where:** `billing/index.page.ts:139` (`(change)="applyAge()"`) and `:362-376`.
- **Live** (`live/age.out`):
  - `1-2` then Tab, `1-2` then Enter, and `12e` then Tab, each typed into the empty box: `badInput:true`, **0 `change` events**, no request, no problem text. The list stays unfiltered while the box shows `1-2`.
  - Controls: `1.5` fires 1 change event and is refused. `90` replaced by `1-2` (the value changes from `90` to `""`) is refused.
- **Why the test misses it:** `R-billing-age-bad-input` (`billing.spec.ts:217-231`) calls `typeUnparseable` and then a synthetic `fireEvent.change`. Chromium does not fire that event from an empty box, so the test proves a path the browser never drives (defeat row 12).
- **Why it blocks:** under the stopping rule this is "malformed text … silently dropped".

**B-S3-2. The number-box guard has 4 unclassified survivors (R5–R8), and one falsified header claim (R7, a bound type).** The cause-level typing counter misses a non-`value` writer (R8b).

**B-S3-3. Payment fixtures satisfy the assertion's equality by accident.**

- `INV_TRAP` (29), `INV_BHD` (1005) and `INV_JPY` (1999) (`stock-billing-fixtures.ts:45-47`) prefill exactly the text their `R-payment-bytes` rows type (`billing.spec.ts:265-271`).
- With typing ignored, R1 (BHD row) and R1b (JPY and 0.29 rows) pass. The rows' claim, "`"1.005"` is sent as 1005", is proven only by the composition with the EUR rows.
- Every payment reference fixture is upper-case: R4 (`reference.toUpperCase()` on the wire, the idempotency key) passes all 33 `R-payment` tests.

**B-S3-4. A stage 2 guard is weakened and a title over-claims.**

- **Where:** `place-order.spec.ts:134`. Its title now ends "(an EMPTY value is refused too, with the plain sentence)", but its body asserts only the unreadable sentence.
- **Evidence:** F03 (an empty quantity read as 1), KILLED by this test in stage 2, now SURVIVES it.
- **The property is still guarded** by `R-bytes` › "a quantity that is not a whole number…" (`:91`; F03s KILLED, failure `Unable to find a label with the text of: Quantity`, the page navigated after a send).

### What must change before re-review

1. **B-S3-1:**
   - Refuse an unreadable age text in words when the browser reports it, without depending on `change` (for example, on `input` when `validity.badInput`, or on `blur`).
   - Rewrite the test so it drives only the events Chromium fires, and arm it on the current code (it must fail).
   - Re-run `live/age.mjs` (all four rows must show the problem).
2. **B-S3-2:** add a render-based half. Over every state the sweep reaches, every rendered element whose live `.type === 'number'` has a `data-testid` in `EXPECTED_NUMBER_BOXES`, and every expected box is rendered somewhere (both ways). Then do one of the following:
   - **Either** read templates with Angular's own parser (`parseTemplate`, from `@angular/compiler`), which closes R6 and R7, resolve the decorator through its import (R5), and flag value-writing bindings beyond `[value]` (R8; or extend `writesWhileTyping` to `valueAsNumber` and `valueAsDate`),
   - **or** narrow the header and the record's rows 6 and 11 to what is really covered, naming the render half as the cover.
   - Re-arm R5, R6, R7 and R8 from `.arm/web29r4/s3/defs.py`, with verbatim failures.
3. **B-S3-3:** make the BHD, JPY and trap totals differ from the typed text (the live probe used 2005 and 5000), and add a mixed-case reference row. Re-arm R1, R1b and R4.
4. **B-S3-4:** assert the empty-quantity sentence in that test (or drop the clause), and re-arm F03 against it.

### Advisories (recommendations, not grounds)

- **A1.** An unreadable units text follows the replenish panel to another row.
  - **What happens** (live, `probe.out` last row, `stale.png`): the text stays on screen with `badInput:true` under the other row's heading. Submitting says "enter a whole number of at least 1", the plain sentence, because `unitsBad` was reset. Nothing is sent.
  - **Why:** `draft-value.ts:20` cannot clear a box whose `value` is already `""`, and `''` → `''` does not re-run the effect.
  - **Recommend:** clear the element when it holds unreadable text, and add an unreadable row to `R-replenish-draft`.
- **A2.** An over-range amount (`90071992547409.92`, EUR) is refused as "at most 2 decimals", but the amount has 2 decimals. Name the range instead.
- **A3.** R3 (the BFF re-serialising through JSON) is equivalent for every compact safe-integer body the browser produces. If "nothing parses" is the claim, add a non-canonical-bytes row (for example, whitespace, or `9007199254740993`).
- **A4.** `billing/index.page.ts:64`, "A line at zero is what makes an order's credit check fail", is copied from #8 `billing-view.tsx:68`. R39 refuses a hold whose amount exceeds the available credit, so a line does not need to be at zero. Reword.
- **A5.** The comments at stock :192 and billing :282 name `close`/`closePayment` as draft writers.
- **A6.** The control census names both billing pagers' buttons `button:Next`/`button:Previous`, so a third pager would be invisible.
- **A7.** `PRD-0001` in `LABELS` is fixture data. Give it its own table.
- **A8.** The quantity box's unreadable sentence carries a "Quantity: " prefix and its plain sentence does not (`place.page.ts:292-293`).
- **A9.** The record's live run did not exercise the age filter in Chromium, which is where B-S3-1 hid.

### Acceptance items mapped to tests (`sdd: false`; this stage's items, verified by running or arming)

| Item | Tests | Verified by |
|---|---|---|
| 1 (id 101) | `stock.spec.ts` `R-stock-name` (6), sweep `/stock` | S2, S3, S4, W8 KILLED; live cells |
| 2 (stock) | `R-stock-states/rows/filters`, `R-replenish-body/bad-input/result/single/company/draft`, `R-typing (stage 3)` | S7b, S13, S20 KILLED; live units rows |
| 3 (billing) | `R-billing-*`, `R-payment-bytes/bad-input/outcome/single/draft`, `money-bytes.spec.ts` `R-bytes (BFF)` | B1, B3, B7, B9, B10, B15, B18b, BB1–3, R1c, R2 KILLED; **R1, R1b, R4 survive (B-S3-3)**; live bytes |
| 4 (number boxes) | `number-boxes.spec.ts` | N1, N2a, N3b, N6b KILLED; **R5–R8 survive (B-S3-2)**; **age box live (B-S3-1)** |
| 5 (H01) | renamed demo test; `R-replenish-draft`, `R-payment-draft` | G05r, S13, B18b KILLED; A1 |
| 6 (writes counted) | `writesWhileTyping` | G01–G04, N6b KILLED; R8b survives (B-S3-2) |
| 7 (sweep) | `error-text.sweep.spec.ts` | W2, W6, W8 KILLED |
| 8 (navigation) | `session.spec.ts`, sweep `CONTROLS` | not re-armed by me (L1 and W10 in the record) |

### CHECKPOINTS.md (the boxes that apply to this stage review)

- [x] C2: one feature `in_progress` (29). I did not edit it.
- [x] C3: no stray debug logging and no float money shapes. `grep -nE "console\.|TODO|FIXME|debugger"` over the five touched page/component sources has no hits (exit 1). `grep -nE "Intl\.|parseFloat|toFixed|Math\.round|Math\.floor"` over the two new pages has no hits (exit 1).
- [x] C3: web money is integer minor units in the invoice's exponent (live bytes).
- [ ] C4: the web gates pass (32 / 644), but **not every claimed guard fails when armed** (B-S3-2, B-S3-3, B-S3-4).
- [x] C5: Claude did not commit. Every artifact is under the git-ignored `.arm/`, and `git status --short` is unchanged.
- [x] C6: n/a (`sdd: false`).
- [x] C7: `specs/shared/` is untouched. `cmp` against #8 for every file except `test-matrix.md` gives no difference. Id 101 is avoided, with citations verified (`stock-view.tsx:26-28`; #7 `index.vue:23-24` at HEAD).

No finding is rooted in `specs/shared/`, so no SA-n or backlog entry is owed. A4 is a UI sentence copied from #8, not a spec defect.

---

## Stage 3 re-review (fix round 1)

**Verdict: REJECTED.** There is 1 blocking finding, inside B-S3-2: the new render half does not see a number box that appears only in a failure state the sweep drives (X1a, X1b). Its header and the brief both say it covers "every state the sweep reaches". This is the second rejection of stage 3, so under the coordinator's rule it goes to the maintainer.

Everything else is met:

- B-S3-1, B-S3-3 and B-S3-4.
- A1 to A9.
- The A6 `Pager` change.
- R5 to R8 as the record classifies them.
- The money and units path, live and on a fresh production build.

The blocking finding is about what a guard claims to cover. The product behaviour is correct.

Brief: the coordinator's message (scoped re-review). Record: `progress/impl_web_app.md`, "Stage 3 — fix round 1". Artifacts are in `.arm/web29r4/s3r1/`: `defs.py`, which loads the stage 3 review's definitions; `arm.py`; `results.jsonl` (27 rows, `cmp` identical on all of them); `logs/`; and `live/`.

### What I ran

- **Gates** (`.arm/web29r4/s3r1/gates.sh`, under `setsid --wait timeout -k 10`): install, lint (no script), types:check, test:ci and build all exit 0, and the currency-exponent pytest passes 15.
  - The suite is **32 files, 654 tests**.
  - Per-file diff against my stage 3 gate log: billing +2, sweep +1, number-boxes +2, place-order +2, stock +2, money-bytes +1, which is 644 + 10 = 654. Every other file has the same count as before, including `orders-list.spec.ts` (9), `components/pager.spec.ts` (11) and `session.spec.ts` (15).
- **Live**, on the production build my gate made (19:53), behind a stub Gateway on 3911 with the BFF on 3010. Outputs are `live/age.out` and `live/probe.out`. Both servers were stopped by process group.
  - `docker ps` shows `otcpy-n8n` only.
  - Nothing of mine is listening. Three listeners from my "before" snapshot had gone by the end: 4000, 3000 and 24678. None of them was started by me.
  - `git status --short` is identical before and after.
  - `sha256sum -c .arm/web29r4/s3r1/sha_start.txt` gives 16 of 16 OK.
- I did not re-run the implementer's other 68 arms. I sampled the ones the coordinator named, plus my own.

### Findings, each closed by a probe

| Item | Met? | Evidence |
|---|---|---|
| **B-S3-1** age filter | **met** | `live/age.out`: `1-2`+Tab, `1-2`+Enter and `12e`+Tab each show "Issued at least (minutes) ago: enter a whole number of minutes, 0 or more." with 0 change events and no request. `1.5`+Tab is refused. In `probe.out`, `90` sends `issuedBeforeMinutes=90`, and `90` then `1-2` is refused. My own grep for `(change)` gives 17 hits (the record says 16 but lists 17 lines). Only one of them is a number box (`billing:139`), and that box now refuses on `input`. |
| **B-S3-2** guard | **not met: X1 (below)** | R5 KILLED by the syntax half (`["compon…`). R6 and R7 SURVIVE the syntax half, as its header now states. **R6r** and **R7r** are KILLED by the render half (`Rendered but not reviewed …: ["ghost"]`). R8 is KILLED by the syntax half, and R8b by the typing counter (`'valueAsNumber=1'`). |
| **B-S3-3** fixtures | **met** | R1 KILLED (0 passed, 1 failed), R1b KILLED (0 passed, 2 failed), R4 KILLED (`"BANK-REF-7A"` vs `"Bank-Ref-7a"`). |
| **B-S3-4** | **met** | F03 against the Quantity test is KILLED: `an empty quantity is not a quantity of 1`. |
| A1 | met | Live (`probe.out`, last row): the moved box goes from `badInput:true` to `badInput:false`; nothing is sent. `A1x` (the directive ignores the forced write) is KILLED. |
| A2 | met | Live: `90071992547409.92` gives "Amount: enter an amount of at most 90071992547409.91 (EUR)." The largest safe amount still sends `9007199254740991`. |
| A3 | met | R3 KILLED: the non-canonical bytes row fails when the BFF round-trips the body through JSON. |
| A4 | met | `billing:64` now says a credit check fails when the hold exceeds the available amount (R39). |
| A5 | met | The comments at stock :192 and billing :282 name `open`/`openPayment` alone. |
| A6 | met, no stage 1/2 regression | Billing's pagers name their buttons per landmark; a pager with the default landmark keeps plain names. **X5** (always naming the buttons) is KILLED by `orders-list.spec.ts` (`Unable to find … role "button" and name "Next"`), so stage 1/2's guard on the default path holds. Per-file counts are unchanged and the sweep is green. |
| A7 | met | `FIXTURE_TEXTS` is its own table, and a text in both tables fails (sweep `:818`). |
| A8 | met | Both quantity sentences are prefixed (`place.page.ts:291-292`). |
| A9 | met | The live record exercises the age filter, and so does my re-run. |

**Money and units, live** (`probe.out`): every payment row I listed in the stage 3 review gives the same bytes again. EUR `0.29` → 29 and `19.99` → 1999; BHD `1.005` → 1005 and `0.29` → 290; JPY `1999` → 1999; MAX_SAFE is exact; malformed text is refused; a repeat gives 201 then 200. Replenish refuses `1.5`, `1e3`, `0` and `9007199254740993`, and `7` sends `units:7`. One early read shows a "prefilled" `0.29` with step `0.001` before the JPY row. That is my probe sampling before change detection; the bytes sent are right, and `reopen2.out` showed settled reads correct.

**`draft-value.ts` changed, so I re-ran G01 to G05:**

- G01, G02 and G03 KILLED.
- The original G04 and G05r no longer apply: their `find` strings are not in the new line. Re-targeted at the new line:
  - **G04x** KILLED (`expected [ '2', '25' ] to deeply equal []`).
  - **G05x** KILLED (`expected '' to be '249.99'`).
  - **G05y** KILLED (`R-replenish-draft`: `expected '5' to be ''`).

### The R5 deviation, judged

**It is sound.** A component that no page renders has no DOM, so no render-based instrument can see it. The brief's "R5–R7 on the render half" was mine, and it is unachievable for R5 as written. The brief's intent is that forms which defeat syntax are covered by the render half. My new attempts show that holds for every **baseline** state:

- **X2** is an input built in code (`createElement(['in','put'].join(''))`, then `type = 'number'`, in `afterNextRender`). The syntax half does not report it. The render half KILLS it (`["(no dat…`).
- **X4** is a component whose metadata is a const (`@Component(META)`), rendered on `/stock`. The render half KILLS it (`["ghost-m…`).

### Blocking: the render half does not sample the failure states the sweep reaches (B-S3-2)

- **X1a:** a plain `<input type="number" data-testid="ghost-err">` rendered only inside `@if (credits.isError())` on `/billing`. The `every rendered number box` test **SURVIVES** (1 passed). The syntax half would kill this plain form, but the arm shows the render half's blind spot.
- **X1b:** the same with `bind-type="'number'"`. Both halves **SURVIVE** (3 passed): `the number boxes are exactly…`, `every rendered number box…` and `nothing is unreadable`.
- **Why it happens:**
  - The sweep drives that state; failing `GET /api/credits` is in `/billing`'s load population.
  - `runPage` samples `numberBoxes` in every run (`page-sweep.ts:338-395`).
  - But the render test reads only `allBaselines()` (`error-text.sweep.spec.ts:749-761`), which are each page's load and each scripted action's success.
- **The claims it falsifies:**
  - The header in `number-boxes.spec.ts:12` says "over every state the sweep reaches".
  - The record says "sampled at every DOM mutation of every run".
  - The brief requires "over every state the sweep reaches".
- **The stated limit does not cover it.** The limit is "a box behind a state no script drives", and RH3 demonstrates that. Here the state is driven, by the failure runs.
- **Recommendation, either one:**
  - (a) Union `run.numberBoxes` over the failure runs as well. They are already memoised by the label machinery, so the test then costs about what W6 costs. Re-arm X1a and X1b.
  - (b) Narrow the header, the test title and the record to "baseline states (each page's load and each scripted action's success)", and add X1b as the armed demonstration of the limit.

  (a) keeps the brief's claim; (b) is the cheaper honest wording.

### Advisories (carried to stage 4 as acceptance items if the maintainer accepts)

- **X3:** an **unrendered** component with `@Component(META)` survives the syntax half (25 passed). The header says the syntax half "covers" unrendered components, but it finds a component only when the decorator's argument is an object literal. There is no user impact, because X4 shows the render half catches the same component once it is rendered. Narrow that sentence, or report a component decorator whose argument is not an object literal.
- **The count line** of the record's `(change)` search says 16 hits; my run and the record's own listing have 17. A count that does not reconcile.

### CHECKPOINTS.md (the boxes that apply)

- [x] C2: one feature `in_progress` (29). I did not edit it.
- [x] C3: integer minor units on the wire (live bytes).
- [ ] C4: the gates pass (32 / 654), but one claimed guard has an unclassified survivor (X1a, X1b).
- [x] C5: Claude did not commit. Every artifact is under the git-ignored `.arm/`.
- [x] C6: n/a.
- [x] C7: `specs/shared/` is untouched (`git status --short specs` is empty).

No finding is rooted in `specs/shared/`, so no SA-n is owed.


## Stage 4 review (reviewer, Sonnet, scoped; 2026-10-16)

**Verdict: APPROVED.** This closes feature 29 `web_app`. Stage 4 touched no BFF route, session, CSRF or money parsing (bounds below), so the Sonnet classification stands. Backups, outputs and logs: `.arm/web29r5/` (`*.bak`, `out_<arm>.txt`, `arms_*.log`, `gate_*.log`, `readme_*.log`). Every arm: backup with sha256, one mutation, the named test, restore by `cp`, `cmp` identical and the sha equal to the backup's (printed by `.arm/web29r5/arm.sh`).

1. **Order link after a payment: verified by my own arms** (`billing-order-link.spec.ts`, 11 tests):
   - a1 (my substitution: href built from the sibling `done.response.paymentReference` instead of the looked-up id): 2 failed, `expected '/orders/PAY-X' to be '/orders/a1b2c3d4-0000-4000-8000-00000…'` (the 201 and the 200 replay).
   - a2 (`enabled: true`): 2 failed, `a page that has paid nothing asks nothing: expected 1 to be +0` and `a response that carries no orderReference ...: expected 1 to be +0`.
   - a3 (`pageSize: 2` in the request): 1 failed, the request test (`expected [ Array(1) ] to deeply equal [ Array(1) ]`).
   - a4 (not-found branch replaced by `false`): 1 failed, the `lookup ANSWERED and found no order` test.
   - "No lookup after a failed payment" is structural: `result.set` is called only in `onSuccess` (`index.page.ts:309-310`), cleared at `:418`/`:423`; no arm of mine targets that clearing separately (the implementer says the same). The four states and the request (`GET /api/orders?orderReference=<paid invoice's>&page=1&pageSize=1`) match the record.
2. **Sweep completeness: verified.** I re-ran the population command: **34 hits** (18 in `api/api-client.ts` as primitives and method bodies, 16 call sites), each classified as in the record; I added an enumeration of other request constructs (`HttpClient|XMLHttpRequest|sendBeacon|WebSocket|location.href =|<form action`) under `src` outside spec/generated/server/build: only comments in `api-client.ts` and the sweep's own stubs in `testing/page-sweep.ts`. The lookup's failure: arm s1 (error branch replaced by `false`, `-t register-payment`) fails 2 tests (detail, title) and `out_s1.txt` lists `GET /api/orders?orderReference=ORD-000042&page=1&pageSize=1 -> 400 / 500 / 502 / 504`, two variants each (8 cases). Statuses 400/401 are the ones `openapi.yaml` declares for `listOrders` (401 excluded off `/login`), plus the generic 5xx the sweep adds; same set as every other GET list. New guards: s2 (a second `api.listCredits({})` inside the existing `queryFn`) fails `every call of an ApiClient method is a reviewed one ... (stage 4 audit)`: `a call of an ApiClient method that the audit has not classified`; s3 (`fetch('/api/credits')` on the stock page) fails `no fetch( or new EventSource( outside the ApiClient`: `expected [ 'pages/(app)/stock/index.page.ts' ] to deeply equal []`.
3. **The flake: no overlap with n101, so it is not explained by a breach of *Runs*; the implementer's no-repro stands.** File times (`stat`, `ls --time-style=full-iso`): the stage-4 arms wrote `out_n98` 07:23:08, `out_n100` 07:23:20, **`out_n101` 07:23:33** (the stock page restored by `cp` at the end of that run), `n103` 07:23:56, `n106` 07:24:08, `n201` 07:24:21, `nstack` 07:24:34, `nport` 07:24:43, `n102` 07:25:11 (last restore: `lib/problem.ts` 07:25:11). `gates.sh` was written 07:25:20; `gate_run_types_check.log` 07:25:23; the first `test:ci` therefore started about 07:25:25 and ended 07:34:15 (`gate_run_test_ci.log`). The stock page was restored 1 min 50 s before the failing run began, and no source under `apps/web` has an mtime between 07:25:12 and 07:36 (`find -newermt`). Today the stock page equals the backup byte for byte (`cmp .arm/web29s4/bak/index.page.ts`). I cannot see processes from that time, so a concurrent run I cannot see is not excluded by files alone, but the one mechanism proposed (n101's window) is. Evidence for no-repro: the implementer's logs `loaded_1..5.log` (all 33 files/667 tests, I opened `loaded.summary`) and my own `test:ci` below (green). Not blocking per the stopping rule (no-repro evidenced; the symptom's single mechanism that I can show requires the stock page to lack the catalogue lookup, which my own n101 arm reproduces as exactly `expected [ 'PRD-0001', …(2) ] to deeply equal [ 'Olive oil 1 L (PRD-0001)', …(2) ]` in `stock.spec.ts`). **Advisory:** I would make the logging part of the re-open trigger, not of this stage: when the label premise fails, print `base.text` of the `/stock` baseline, so a recurrence is diagnosed at once. Nothing to change in the test now.
4. **README: verified by running.** `install --frozen-lockfile` exit 0 (`Done in 56ms`); `types:check` exit 0; `build` exit 0; `start` on 3010 printed `Listening on http://[::]:3010` and `curl .../login` -> **200**; stopped by PID (3010 free afterwards, no `serve.mjs` left). The keys table matches `.env.example` (WEB_PORT, WEB_SESSION_PASSWORD, WEB_COOKIE_SECURE, WEB_GATEWAY_TIMEOUT_MS, commented GATEWAY_BASE_URL) and `src/server/lib/config.ts` (`:15-18` GATEWAY_BASE_URL else `localhost:${GATEWAY_PORT:-3001}`, `:39-48` password >= 32 chars else random with a warning, `:54-55` Secure unless exactly `false`, `:58-62` timeout default 15000); `package.json` `dev`/`start` use `--env-file-if-exists=../../.env`. The `lint` line was correctly removed (`package.json` has no such script). `apps/web/README.md` makes no false claim (every command is one of those above; `types:generate` exists in `package.json`). I did not run `dev` or the sign-in POST (they need the Gateway for a meaningful result).
5. **"Caused by" claims: consistent with the artifact.** The record cites a live order with 9 timeline entries and 3 "caused by" (`.arm/web29s4/live/causation.out`, which I did not re-generate: it needs the full stack, outside this scoped review) and the stage 2 artifact (`domLinkedCount: 3`). `services/seed/README.md` (one sentence, `git diff` is that line only) and `docs/PROCESS.md:330` now say what that evidence says (three links, cross-context, six cite a command) and the PROCESS row no longer asserts that the facts are "only on facts Orders emits". The UI sentence (`[id].page.ts:146`) renders only when the causing entry is on the timeline; arm n201 is in the implementer's table and the code (`lib/order-detail.ts:98-101`) is unchanged.
6. **R55: verified.** `git diff specs/` is 3 insertions/3 deletions in `test-matrix.md`: the R55 cell (Status column), the group row 7 (`6 | 6 | 0 | 0`), the Total row (`57 | 1 | 5`). I recounted by script: group greens 9+8+9+7+8+3+6+6+1 = **57**, scoped 1, not-yet-green 0+0+2+1+0+2+0+0+0 = **5**, rows 10+8+11+8+8+5+6+6+1 = 63, and 57+1+5 = 63; the three remaining NOT YET GREEN cells in the file are R61, R48, R49 (the other two of the five are R24 and R28/R29 halves in group 3, as before). The Gateway half by reading code: `test_gateway_over_real_responders.py:272` places an order through the real Gateway and asserts 202, `projection_pending`, `retry-after: 2`, then 200 after projection; `test_gateway_orders_http.py:178` asserts the 202 body field for field after `POST /orders`; `:356` asserts 202 within the window and 404 after it. The two unit tests were run by me: `2 passed`. The integration test was not re-run (needs containers; out of scope for a web-only stage, and it is unchanged by stage 4). The web half: `order-detail.spec.ts` > `R55 (web half): the honest 202` (green in my `test:ci`).
7. **Inherited-id close-out: three rows re-armed on the final tree.** n100 (id 100; the added assertion: `{{ event.summary.replace(' EUR', '') }}`): `R-detail: the document > shows the reference, parties, ...` fails `expected [ …(3) ] to deeply equal [ …(3) ]`. n101 (id 101): 2 failures in `stock.spec.ts`, above. n98 (id 98): 2 failures, `giving up asked the order again, through a query: expected false to be true` and `initial read + the one read giving up asks for ...: expected 1 to be greater than or equal to 2`. All restored, `cmp` identical.
8. **Gates (mine, after all arms restored):** `types:check` exit 0 (`OK`); `build` exit 0; `test:ci` exit 0, **33 files, 667 tests passed** (reconciles with the record: 33/667; the sweep file 119 and `billing-order-link.spec.ts` 11 appear in it). Each under `setsid --wait timeout -k 10`. `lint` does not exist (documented). I ran no backend suite beyond the two gateway unit tests above, because stage 4 changed no backend file (`git status`).
9. **Bounds: kept.** `git status --short` outside `apps/web/`: `README.md`, `specs/shared/test-matrix.md`, `services/seed/README.md` (line 21), leader's `docs/PROCESS.md`, `progress/**`, `feature_list.json`; plus `.env.example`, `init.sh`, `quality.sh`, whose mtimes are 2026-10-15 (before stage 4 started at 06:56:31 on 10-16), so they belong to earlier stages. No process or container left from my run: `docker ps` shows only `otcpy-n8n` (as found), no listener on 3010/3011, no vitest or `serve.mjs` process.

**Advisories (none blocking).** (a) The flake logging above. (b) Arms are in `.arm/web29r5/`, git-ignored. (c) I did not re-generate the live causation artifact; the claims were checked against the recorded artifacts, not against a new run.

**Feature 29 acceptance items on the final tree** (the record's table, with the test I saw green in the 667): 1 BFF `bff.spec.ts`, `boundaries.spec.ts`, `config.spec.ts`, `routes.sweep.spec.ts`, `production-bff.spec.ts`, `seam.spec.ts`, `session.spec.ts`; 2 types and drift `scripts/openapi-types.spec.ts`, `generated-types.spec.ts` and `types:check` OK; 3 money `money.spec.ts`, `currency-exponent.spec.ts`, `money-bytes.spec.ts`; 4 error text `error-text.sweep.spec.ts` (119), `routes.sweep.spec.ts`, `problem.spec.ts`, `billing-order-link.spec.ts`; 5 pages `login/orders-list/place-order/order-detail/stock/billing/billing-order-link` specs; 6 inherited criteria: ids 98, 100, 101 re-armed by me, the others per the record's table (not re-armed here); 7 backlog 201: `order-detail.spec.ts` `backlog 201` block, README/seed README/PROCESS text consistent with the live artifact. All seven met; the leader moves the state.
