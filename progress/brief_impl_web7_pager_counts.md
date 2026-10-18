# Brief — implementer — #7 (`../order-to-cash-nestjs`) the remaining pagers claim a count while loading, LIGHT

The maintainer approved this fix on 2026-10-18, after the stock page fix (`progress/impl_web7_stock_leftovers.md`, uncommitted in #7's working tree — do not undo or alter it). Work ONLY in `/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-nestjs`.

## Population (leader's search, this session)

`grep -rnE "page\.total \?\? 0|Page \{\{" apps/web/app --include='*.vue'` → 4 hits:
- `app/pages/stock/index.vue:312` — already fixed (`v-if="!isError && data"`, no fallbacks). The idiom to follow.
- `app/pages/orders/index.vue:172` — "Page {{ data?.page.page ?? filters.page }} of {{ totalPages }} · {{ data?.page.total ?? 0 }} orders", wrapper `v-if="!isError"` (line 170).
- `app/pages/billing/index.vue:253` — credits pager, `credits?.page.total ?? 0`, wrapper `v-if="!creditsError"`.
- `app/pages/billing/index.vue:458` — invoices pager, `data?.page.total ?? 0`, wrapper `v-if="!isError"`.

Re-run the search first and confirm the same 4 hits; any other hit is in scope too, reported in your file.

## Fix

At each of the three sites: render the pager only when its own list's data exists and its read has not failed (credits pager keyed on the credits query, invoices pager on the invoices query — independent of each other), and drop the `?? filters.page` / `?? 0` fallbacks, exactly as the stock page does. Add a `data-testid` per pager if none exists (`orders-pager`, `credits-pager`, `invoices-pager`). Check that the credits pager's Previous/Next `data-testid`s that existing tests use still render once data exists.

## Tests

In `app/pages/orders/index.spec.ts` and `app/pages/billing/index.spec.ts` (follow the stock spec's new tests, `app/pages/stock/index.spec.ts`): per pager (3), while that list's request is **held on an unresolved promise** no count is shown (the pager is absent), and after a failed read none either; for billing, holding one list leaves the OTHER list's pager showing its count (independence). Fixture totals must be distinct per list (e.g. 45 invoices, 7 credit lines) so a swapped binding fails. Arm once per pager: back up into `../order-to-cash-python/.arm/phase17/web7-pagers/` with `sha256`, restore that site's old line, run the ONE test, record the failure verbatim, `cp` back, `cmp`, green.

Then run #7's full web suite (`pnpm test` in `apps/web`) and `pnpm build`; record counts (before: 25 files / 300 tests) and exit codes.

## Bounds

No commit, no git command that writes the index or working tree, no package. Only those three sites and those two spec files.

Write results to `../order-to-cash-python/progress/impl_web7_pager_counts.md`. Return a 3-line summary and that path.
