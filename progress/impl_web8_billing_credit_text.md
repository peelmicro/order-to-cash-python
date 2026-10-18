# impl: #8 billing credit-card sentence (LIGHT)

- `apps/web/src/features/billing/billing-view.tsx:68` in #8 now reads: "...A credit check fails when the order&apos;s hold exceeds what is available (R39), so a line below the order&apos;s amount fails it, not only a line at zero."
- `grep -rn "at zero" apps/web/src README.md docs` in #8: one hit before (the defect itself); no test, README or docs repeated the claim. Now the only hit is the corrected sentence.
- Added one test in `billing-view.test.tsx`: "the credit card says a check fails when the hold exceeds what is available (R39), not only at zero".
- Armed once: backup of the old file (sha256 6c454707...14c0d) in `.arm/phase17/web8/`; with the old sentence restored the test failed: `Unable to find an element with the text: /hold exceeds what is available \(R39\), so a line below ...`. Restored the fixed file (sha256 4baed31e...cb62), `cmp` identical, green.
- Full web run in #8: `vitest run` 22 files, 288 tests passed, exit 0. `next build` exit 0.
- Changed files in #8: only the two above. No commit, no package added.
