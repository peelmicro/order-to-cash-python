# Brief — implementer — #7 (`../order-to-cash-nestjs`) stock page: two cosmetic leftovers, LIGHT

Raised in #9 Phase 16 (`progress/history.md:1533` of #9); the maintainer approved the fix on 2026-10-17. Work ONLY in `/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-nestjs`. Its `CLAUDE.md` and test conventions apply there.

## The two defects (leader read the file this session)

1. `apps/web/app/pages/stock/index.vue:291` — after a successful replenish, "on-hand is now {{ …find(…)?.units ?? '…' }}." When the answer omits the line, the page shows "…", which reads as still loading. #9's wording for the same case (`order-to-cash-python/apps/web/src/app/pages/(app)/stock/index.page.ts:238-241`): "The answer did not include this line's new on-hand level." Port that behaviour (honest sentence instead of the ellipsis).
2. `apps/web/app/pages/stock/index.vue:306` — the pager shows "Page … of {{ totalPages }} · {{ data?.page.total ?? 0 }} stock lines" while the first read is loading (and after a failed read), i.e. it claims "0 stock lines" it does not know. #9's rule (`order-to-cash-python/apps/web/src/app/stock.spec.ts:36` and `:64`): while loading and after a failed read the pager claims **no count**. Check how #7's other list pages (orders, billing) handle it — if one of them already does it right, follow that page's idiom; if they share the same defect, record it in your file and do NOT fix them (scope is the stock page).

## Tests

- Add to #7's existing stock page spec (find it: `grep -rln "stock" apps/web/app --include='*.spec.ts'`) one test per defect: (a) a replenish answer that omits the line shows the honest sentence and no "…"; (b) while the stock request is **held on an unresolved promise**, the pager text contains no count (and after a failed read too). Each test armed once: back up into #7's repo-local git-ignored arm dir if one exists (check `.gitignore`; otherwise create `.arm/` only if it is ignored — if not, use `../order-to-cash-python/.arm/phase17/web7/`), revert the fix, run the ONE test, record the failure verbatim, restore with `cp`, `cmp`, re-run green.
- Run #7's web test suite and build (find the commands in its `apps/web/package.json` / `quality.sh`), record counts and exit codes.

## Bounds

No commit, no git command that writes the index or working tree. Do not touch other pages. No package added.

Write results to `../order-to-cash-python/progress/impl_web7_stock_leftovers.md` (diff summary, tests, arms verbatim, run counts). Return a 3-line summary and that path.
