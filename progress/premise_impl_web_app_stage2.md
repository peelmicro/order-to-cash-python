# Premise check — progress/brief_impl_web_app_stage2.md

Verdict: SAFE TO ACT (0 FALSE). "Stage 1 approved" deliberately not checked.

VERIFIED  test-matrix.md line 181 is the R55 row and names `web/components/order-detail-pending.spec` › *renders the waiting state on a projection-pending answer and fills in from the update stream* — `sed -n 181p specs/shared/test-matrix.md`, quoted string identical.
VERIFIED  README line 184 states the live "caused by" behaviour — `sed -n 184p README.md`: "'Caused by' on a live timeline links facts whose causationId names another fact ... never a timeline entry (R12 ... SA-6)".
VERIFIED  currency-exponents.json has 26 entries — `python3 -c json.load(...)` gives dict, len 26.
VERIFIED  test_currency_exponent.py:14 reads the JSON by path — line 14: `WEB_JSON = REPO_ROOT / "apps" / "web" / "src" / "lib" / "currency-exponents.json"`; `divergences()` compares both directions.
VERIFIED  currency_exponent.py exists in packages/shared_kernel/src/otc_shared_kernel/ — ls.
VERIFIED  summaries.py:36,78,82 — 36 `from otc_shared_kernel import format_money`, 78 `Credit hold of {format_money(...)} approved`, 82 `amount = format_money(...)`.
VERIFIED  feature 29 has 7 acceptance items; item 3 money, 4 sweep, 5 pages, 6 inherited ids, 7 backlog 201 — python json load of feature_list.json, 7 items in that order.
VERIFIED  backlog 201 `done`, acceptance 2 (README/UI claims) carried to feature 29 — feature_list.json id 201 status "done", acceptance[1]; note "item 2 -> feature 29's acceptance".
VERIFIED  phase 12 gate chose option (b) and SA-6 — README.md:38 ("ruled option (b) of backlog 201") and progress/history.md:1304.
VERIFIED  stage 1 files exist: src/app/api/api-client.ts; src/app/session/{session,signed-out}.ts; src/app/pages/(app)/orders.page.ts; src/app/error-text.sweep.spec.ts; src/app/testing/{browser-harness,page-sweep}.ts; BFF routes orders/{index.get,index.post,[id].get,stream.get}.ts and catalog/{companies,products,retailers}.get.ts — ls under apps/web/src.
VERIFIED  a 401 from any call -> /login — signed-out.ts:7,17 (`error.status !== 401` return guard; comment "A 401 from ANY BFF call").
VERIFIED  impl_web_app.md has sections "Stage 1" and "Stage 1 — fix round 1" — grep: line 3 "## Stage 1 of 4: ...", line 304 "## Stage 1 — fix round 1".
VERIFIED  stage 1 review advisories A3 (late-request bound, record longest delay at run time) and A4 (LABELS/NOT_SHOWN literal vs literal) — progress/review_web_app.md:61,62.
VERIFIED  stage 1 brief holds the count command for item count — progress/brief_impl_web_app_stage1.md:3 contains the python one-liner and "seven".
VERIFIED  #8 files lib/{money,money.test,order-stream-client,order-stream-client.test}.ts, hooks/{use-order-detail,use-order-stream,use-orders,use-catalog}.ts, features/orders/{orders-list,place-order-form,order-detail-view}.tsx — ls in ../order-to-cash-dotnet/apps/web/src, all present; tests exist (orders-list/place-order-form/order-detail-view/use-order-stream .test.tsx).
VERIFIED  #7 lib/{money,order-stream-client}.ts (+ specs), composables/{useOrders,useOrderDetail,useOrderStream,useCatalog}.ts, pages/orders/**, pages/currency-exponent.spec.ts — ls in ../order-to-cash-nestjs/apps/web/app, all present (money.spec.ts, order-stream-client.spec.ts).
VERIFIED  #7 history line 1101 = web_app entry; passes 3-5, cross-event-type eventId collision found under a REJECTED verdict, decimal unit-price float bug — line 1101 is the entry heading; line 1103 holds "passes 3/3-fix/4/5 ... cross-event-type eventId collision found and fixed under a REJECTED verdict ... decimal unit-price float bug". (Detail text is at 1103, entry starts 1101.) The "honest 202 waiting state" is not in that line; not separately checked, #8 history line ~2880 lists "A 202 renders an honest waiting state" for #8 only.
VERIFIED  #8 history id 98 entry after line 2832 — `## Backlog id 98` at ../order-to-cash-dotnet/progress/history.md:2894.
VERIFIED  #8 id 98 content (terminal order, expired session -> /login, Retry never loops on a refusal, refusal held deterministically, armed by removing the fix) — #8 feature_list.json id 98 acceptance, 5 items; history 2894-2900.
VERIFIED  #8 id 97's rejection came from a `step` site classed display-only — history.md:2950 (inside `## Id 97` at 2944): "rejection came from a site the implementer classified as display-only without checking what `step` does".
VERIFIED  #8 id 100 / 102 are server-written money text (timeline summary; problem detail) — #8 feature_list.json ids 100, 102 titles/acceptance.
VERIFIED  #8 id 101 = stock page name (stage 3) — feature_list.json id 101 title "stock_page_repeats_the_product_code".
VERIFIED  #8 id 103 CLDR vs ISO 4217; HUF, IQD, JPY, BHD, EUR through format, parse, step; whole-table parity armed with one-row corruption on each side — id 103 acceptance 3 and 4.
VERIFIED  #8 id 106 module counter `nextLineKey`, label for / control id, N renders in one module instance — id 106 acceptance 1-3, notes.
VERIFIED  "backends are already in #9's tree": format_money used in summaries.py (+ billing invoice_errors.py/errors.py, orders place_order.py/errors.py, notifications format.py, seed sagas.py) — grep -rln format_money services/*/src; whole-string tests exist: services/projector/tests/unit/test_summaries.py:77 "Credit hold of 92.45 EUR approved", :85 "Credit hold of 5 000 JPY rejected (simulated_cents_rule)".
VERIFIED  #8 B1 = place-order catalogue failure generic notice — ../order-to-cash-dotnet/progress/review_web_app.md:23.
VERIFIED  #8 S4 = pager claims no count while loading — review_web_app.md:760 ("while loading, the pager must not claim a count").
VERIFIED  #8 RR3-3 exception list (EventSource has no body) — review_web_app.md:747, 1017.
VERIFIED  #8 RR3 D3 (a) = derived-vs-literal consumer tables for mutations/gated reads — review_web_app.md:831-832.
VERIFIED  #7 Pass 7 lesson (loading guard on unresolved promise, testid present) — ../order-to-cash-nestjs/progress/review_web_app.md:471 and history.md:1116.
VERIFIED  openapi.yaml has `/orders` with query parameters — specs/shared/openapi.yaml:163; parameters status, retailerCode, companyCode, orderReference (brief only says "read them"; pagination parameters not enumerated here).
UNVERIFIABLE  "`quality.sh` section 7's commands" run green / the production build on 3010, live check, Vitest count — would need running suites; section 7 heading exists at quality.sh:51.
UNVERIFIABLE  README "Running the services" / progress/current.md *Notes* contents suffice for the live check — headings exist (README.md:140; current.md:25,46), content sufficiency not a command-checkable fact.

Counts: VERIFIED 31, FALSE 0, UNVERIFIABLE 2.
