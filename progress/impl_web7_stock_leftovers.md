# impl: #7 stock page leftovers (light)

Files (in order-to-cash-nestjs): `apps/web/app/pages/stock/index.vue`, `apps/web/app/pages/stock/index.spec.ts`. Nothing else; no commit, no package.

## Fixes
1. Replenish outcome: a `newOnHand` computed; shows "— on-hand is now N." or "— the answer did not include this line's new on-hand level." (no ellipsis).
2. Pager: `v-if="!isError && data"` (with `data-testid="stock-pager"`), text reads `data.page...` with no `?? 0` fallback. Loading and failed reads show no pager (the failed read was already hidden by `!isError`; loading was the real defect).
3. Other pages (not touched): `orders/index.vue:172` and `billing/index.vue:253,458` share the same `data?.page.total ?? 0` defect. Recorded only.

## Tests (added to the existing stock spec, 3 tests)
- "a replenish answer that omits the line says so in words, and never shows an ellipsis" (defect 1)
- "while the first stock read is held, the pager claims no count; once answered it does..." (defect 2, loading, on a held promise)
- "after a failed read the pager claims no count" (defect 2, failure)

## Arms (backup `.arm/phase17/web7/index.vue` in the python repo, sha256 39add595d18085282210e238ec48bb61ea8c064353c58d6646c1fc802c4026b0; #7 .gitignore has no `.arm`)
- Fix 1 reverted to `?? '…'`: `AssertionError: expected ' Added 5 units to PRD-0001 — on-hand …' to contain 'the answer did not include this line\…'` / Received `" Added 5 units to PRD-0001 — on-hand is now …. "`. Restored with cp, cmp clean.
- Fix 2 reverted (`v-if="!isError"`, `data?.… ?? 0`): the held-read test failed (`× while the first stock read is held, the pager claims no count...`, 1 failed). Restored, cmp clean. The failed-read test was not armed separately (that path was already correct before the fix; it is a guard against regression).

## Runs
- `pnpm exec vitest run app/pages/stock`: 2 files, 30 passed.
- `pnpm test` (apps/web): 25 files, 300 passed, exit 0 (`$?` taken after a tail pipe, counts are the evidence).
- `pnpm build`: exit 0, "Build complete!".
