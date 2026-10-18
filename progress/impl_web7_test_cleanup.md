# impl_web7_test_cleanup — #7 apps/web page specs never cleared the DOM (light, test-only)

## Probe (leak is real)
New spec `app/test-cleanup.spec.ts` (2 ordered tests; first `renderSuspended(OrdersPage)`, second asserts no heading / no `#test-wrapper` / empty body text) run BEFORE any setup change (output in `.arm/phase17/web7-cleanup/probe.txt`):

    FAIL app/test-cleanup.spec.ts > test DOM isolation > finds nothing of the previous test in document.body
    AssertionError: expected [ <h1 …(1)></h1> ] to have a length of +0 but got 1
    Tests  1 failed | 1 passed (2)

## Source reading
- `@testing-library/vue/dist/index.js:47-48`: auto-cleanup only `if (typeof afterEach === 'function')`; globals are off, so it never registers.
- `@nuxt/test-utils/dist/runtime-utils/index.mjs:229-236` (`renderSuspended`): mounts via `@testing-library/vue`'s `render`; calls `cleanupAll()` and removes `#test-wrapper` only at the START of the next render. `suspended-DDMM5DdJ.mjs:95` (`cleanupAll`) runs registered effect-scope cleanups. No afterEach of its own, so a test's DOM stays until the next render (or forever, for a test that does not render).

## Choice
(a): `afterEach(() => cleanup())` in `vitest.setup.ts` with Testing Library's `cleanup` (it unmounts what `render` mounted, which is what renderSuspended uses). Reason is in a comment beside it. `globals: true` not needed; `vitest.config.ts` untouched.

## Arm
Backup `vitest.setup.ts.fixed` sha256 ed8728881402e484bf0ea627466f8c442fb42f1ae87a1acf12466416009f2231 (original pre-change: 1277f777…9c2, `.bak`). Removed the `afterEach` line, ran the ONE spec:

    FAIL app/test-cleanup.spec.ts > test DOM isolation > finds nothing of the previous test in document.body
    AssertionError: expected [ <h1 …(1)></h1> ] to have a length of +0 but got 1
    Tests  1 failed | 1 passed (2)

Restored with `cp`, `cmp` clean, green (2 passed). Rows: delete the behaviour. Counted: one guard test, one arm.

## Files touched (all under order-to-cash-nestjs/apps/web)
- `vitest.setup.ts` (global afterEach cleanup + comment)
- `app/test-cleanup.spec.ts` (new guard)
- `app/pages/orders/index.spec.ts`, `app/pages/billing/index.spec.ts`: removed the local `cleanup()` before/afterEach, the `cleanup` import, the now-unused `afterEach`/`beforeEach` imports, and the stale comment.

## Newly failing tests
None. The full suite passed with the global cleanup: no test was relying on an earlier test's DOM.

## Runs
- `pnpm test`: exit 0, 26 files / 308 tests (before: 25 / 306; +1 file, +2 tests = the guard).
- `pnpm build`: exit 0, "Build complete".
- `pnpm test:coverage`: exit 0, 26 files / 308 tests, All files 90.16 lines-stmts / 88.66 branches / 89.57 functions / 90.73 lines; 60 % floor passed.
- Not run: no git write commands, no commit. `git status`: 3 modified + 1 new file, all in apps/web.

## Surprise
The leak is narrower than the brief's claim: `renderSuspended` does clean up at the start of the next render, so tests that render again were safe; only tests that assert without rendering (and the last test of a file) saw stale DOM. The global cleanup fixes the general case.
