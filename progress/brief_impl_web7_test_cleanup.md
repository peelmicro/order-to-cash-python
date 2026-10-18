# Brief — implementer — #7 (`../order-to-cash-nestjs`) page specs never clear the DOM between tests, LIGHT (test-only)

The maintainer asked for this fix on 2026-10-18. Work ONLY in `/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-nestjs/apps/web`. #7's working tree is clean at `32b3c25`.

## What the leader verified with a command this session

- `vitest.config.ts` (`defineVitestConfig`, `environment: 'nuxt'`) sets no `globals`; `vitest.setup.ts` only imports `@testing-library/jest-dom/vitest`.
- 19 spec files under `app/` render through `renderSuspended` (`@nuxt/test-utils` ^4.2.0, `@testing-library/vue` ^8.1.0).
- Only `app/pages/orders/index.spec.ts` and `app/pages/billing/index.spec.ts` call `cleanup()` themselves (added in `32b3c25`, inside their new describes).
- The claim to settle: with no global `afterEach`, the auto-cleanup of `@testing-library/vue` (and whatever `renderSuspended` relies on) never runs, so a test's DOM stays in `document.body` for the next test in the file.

## Work

1. **Prove the leak first** (before changing anything): a throwaway probe (in the ROOT arm dir `../order-to-cash-python/.arm/phase17/web7-cleanup/`, or a temporary spec you delete afterwards) — two tests in one file, the first renders a page with `renderSuspended`, the second asserts `document.body` holds none of it. Record the output verbatim. If there is no leak, STOP and report: the premise is false.
2. **Find out which cleanup applies**: read how `renderSuspended` in the installed `@nuxt/test-utils` version cleans up (file and line in `node_modules`), and whether it needs a global `afterEach`. Choose between (a) one `afterEach(() => cleanup())` in `vitest.setup.ts` (with the right `cleanup` — Testing Library's, or the one `@nuxt/test-utils` exports, whichever unmounts what `renderSuspended` mounted) and (b) `globals: true`. Prefer (a), the smaller change, unless the source shows it does not unmount `renderSuspended`'s wrapper. Write the reason in a comment beside the line.
3. **Remove the now-redundant local `cleanup()` calls** in `orders/index.spec.ts` and `billing/index.spec.ts`.
4. **A permanent guard**: one small spec (e.g. `app/test-cleanup.spec.ts`) with two tests in order — the first renders a page, the second asserts `document.body` contains nothing from it. Arm it: back up `vitest.setup.ts` into the root arm dir with `sha256`, remove the cleanup line, run the ONE spec, record the failure verbatim (it must name the leftover), restore with `cp`, `cmp`, green.
5. **Run the whole suite** (`pnpm test` in `apps/web`, under `setsid --wait` with a timeout that kills the process group). Before: 25 files / 306 tests. **Any test that now fails is the point of this fix**: it was passing on an earlier test's DOM. For each one, record the test name, the failure verbatim, and the mechanism (which earlier test's DOM it was finding). If the fix is a test fix (await the render, find the right element), make it. If the failure shows the PAGE is wrong (the product does not render what the test expects on its own), do NOT change source: stop and report it — the leader re-classifies.
6. Then `pnpm build`, and `pnpm test:coverage` (the 60 % floor is a live gate there); record counts and exit codes.

## Bounds

Edit only `apps/web/vitest.setup.ts`, `apps/web/app/**/*.spec.ts` and the new guard spec. No source, no package, no `vitest.config.ts` change unless step 2 proves (a) cannot work (then say why). No commit, no git command that writes the index or working tree.

Write results to `../order-to-cash-python/progress/impl_web7_test_cleanup.md` (the probe, the source reading with file:line, the choice, the arm verbatim, every newly failing test with its mechanism, the run counts). Return a 3-line summary and that path.
