# Premise check: brief_impl_web_app_stage3.md

VERIFIED openapi.yaml lines: /stock 529, /stock/replenish 572 (sed -n shows "/stock/replenish:"), /invoices 613, /invoices/{id}/payments 664, /credits 765, /catalog/products 802 (sed -n Np each prints the path key)
VERIFIED 28 files / 466 tests recorded in progress/review_web_app.md (line 726 "Test Files 28 passed (28), Tests 466 passed (466)"; 730 reconciles 457+5+4)
VERIFIED "Stage 2 re-review (fix round 1)" heading exists (review_web_app.md:543)
VERIFIED advisories section at line 710 ("### Advisories carried to stage 3"), items 1, 2, 4 are population guard, H01, cause-level guard
VERIFIED .arm/web29r3/s2r1/defs.py exists and holds ARMS["H01_directive_writes_once"] (defs.py:10)
VERIFIED test title "a draft changed from OUTSIDE the input (the demo button) is still written into it" at place-order.spec.ts:208
VERIFIED request schemas ReplenishStockRequest (openapi.yaml:1753) and RegisterPaymentRequest (:1840) exist; the replenish line field is `units`, not `quantity`
VERIFIED registerPayment declares '201' (line ~719) and '200' (idempotent replay), plus "Idempotency semantics by paymentReference" in the description
VERIFIED #8 id 101 acceptance wording matches in spirit: name from /catalog/products with code beside it, code once, productName wins, catalogue failure keeps table, sweep extended (feature_list.json of #8, id 101)
VERIFIED quality.sh section 7: install --frozen-lockfile, run --if-present lint, run types:check, run test:ci, run build; test_currency_exponent.py exists
VERIFIED feature_list.json id 29 has 7 acceptance items; item 5 = pages incl. stock/billing, 4 = error sweep, 3 = money, 6 = inherited ids incl. 101
VERIFIED all #9 input paths exist (BFF stock/invoices/credits/catalog routes, api-client.ts, money.ts, currency-exponent.ts, draft-value.ts, pager.ts, sweep spec, browser-harness/page-sweep/page-test, brief_impl_web_app_stage1.md, impl_web_app.md "Stage 1" and "Stage 2 — fix round 1" at 664)
VERIFIED all #8 paths (stock-view{,.test}.tsx, billing-view{,.test}.tsx, use-stock.ts, use-billing.ts) exist
VERIFIED all #7 paths exist at HEAD (git show: stock/index.{vue,spec.ts}, billing/index.{vue,spec.ts}, useStock.ts, useBilling.ts)
VERIFIED order detail page has no billing link (only routerLink "/orders" at [id].page.ts:46)
UNVERIFIABLE "stage 2 both approved", "#7 being changed in parallel", port 3017 activity: no command settles it
UNVERIFIABLE "the shell links to both pages" is a to-do, not a claim

Verdict: SAFE TO ACT (0 FALSE)
