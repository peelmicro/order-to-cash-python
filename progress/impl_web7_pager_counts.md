# impl: #7 pagers claim no count while loading (LIGHT)

Repo: `/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-nestjs/apps/web`. Stock page fix untouched.

## Population
Re-ran `grep -rnE "page\.total \?\? 0|Page \{\{" app --include='*.vue'`: the same 4 hits (stock already fixed; orders:172, billing:253, billing:458). No extra hit.

## Fix
Each of the three pagers is now `v-if="!<its own error> && <its own data>"`, with the `?? filters.page` / `?? 0` fallbacks dropped, and a new `data-testid`:
- `app/pages/orders/index.vue`: `orders-pager` (`!isError && data`)
- `app/pages/billing/index.vue`: `credits-pager` (`!creditsError && credits`) and `invoices-pager` (`!isError && data`), independent of each other.
The existing `credits-prev` / `credits-next` ids are unchanged, and the pagination test that uses them still passes.

## Tests (6 new)
- `orders/index.spec.ts`: held read gives no `orders-pager` and no `N orders` text, then 45 orders shows "Page 1 of 3 · 45 orders"; failed read gives no pager.
- `billing/index.spec.ts`: invoices held, so the invoices pager is absent while the credits pager shows 7; credits held, so the credits pager is absent while the invoices pager shows 45; failed invoices read, so no invoices pager and credits unaffected; failed credits read, so no credits pager and invoices unaffected. Totals are distinct per list (45 / 7).
- Surprise: vitest globals are off, so testing-library's auto-cleanup never runs and earlier tests' DOM stayed in the document. My first run found a previous test's pager ("1 credit lines") instead of the held one. The new describes therefore call `cleanup()` in `beforeEach` and `afterEach`, with a comment. The existing tests were left alone (bounds).

## Arming (backups + sha256 in `.arm/phase17/web7-pagers/`)
Per site, the old line was restored, the ONE held-read test run, then `cp` back and `cmp` (restored-all printed). Each failed with `expected document not to contain element, found <div class="flex items-center justify-between" data-testid="<orders|credits|invoices>-pager">`:
- orders: "while the first orders read is held ..."
- credits: "while the credits read is held ..."
- invoices: "while the invoices read is held ..."

## Suite
`pnpm test`: 25 files / 306 tests passed (before 25 / 300; +6), exit 0. `pnpm build`: exit 0, "Build complete!". The failed-read tests were not armed separately (the `!isError` half is unchanged); the held-read arms cover the new `&& data` half.
