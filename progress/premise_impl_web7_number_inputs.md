# Premise check: brief_impl_web7_number_inputs.md
VERIFIED  five type="number" in #7: place.vue:370,381,395, billing/index.vue:384, stock/index.vue:251 (grep -rn 'type="number"' app --include=*.vue; the sixth hit billing:374 is a comment)
VERIFIED  place.vue 370 quantity (min=1, Number(v)), 381 unit price override, 395 line discount (sed -n 366,400p)
VERIFIED  billing:384 Register payment (id payment-amount); stock:251 replenish (id replenish-units, v-model)
VERIFIED  billing:374 comment says v-model on input type=number auto-casts via looseToNumber
VERIFIED  no other number input in #7 app: grep for :type=/v-bind:type/inputmode empty; components/ui/input/Input.vue only forwards attrs
VERIFIED  @playwright/test ^1.62.1 at #7 apps/web/package.json:39
VERIFIED  #7 .gitignore has no .arm (git check-ignore -v .arm/x rc=1)
VERIFIED  #9 .arm/ ignored (.gitignore:87 /.arm/)
VERIFIED  review_web_app.md "Stage 2 review" (line 391) B1 = malformed price dropped, Chromium production build
VERIFIED  #9 files draft-value.ts and orders/ exist
FALSE     "#9's fix in apps/web/src/app/orders/ + components/draft-value.ts": orders/ holds only catalog.ts and draft-value.ts is a directive that avoids rewriting element.value; neither mentions badInput. The badInput fix is in apps/web/src/app/pages/(app)/orders/place.page.ts and place-order.spec.ts (grep -rln badInput apps/web/src)
VERIFIED  #8 place-order-form.tsx text inputs with inputMode (lines 395 numeric, 402 and 415 decimal; the Input has no type=number)
VERIFIED  #7 place.currency.spec.ts exists; it does not assert step (grep -c step = 0)
VERIFIED  #7 specs: @vitest-environment nuxt, renderSuspended of the page component with registerEndpoint stubs (no server); e2e/ Playwright against a running base URL (playwright.config.ts, no webServer)
VERIFIED  #7 Nuxt server calls Gateway server-side: server/api/orders/index.post.ts, invoices/[id]/payments.post.ts, stock/replenish.post.ts use gatewayFetch (server/utils/gateway.ts)
Counts: VERIFIED 14, FALSE 1, UNVERIFIABLE 0. Verdict: DO NOT ACT (until the draft-value/orders path claim is corrected)
