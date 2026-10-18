# Brief — implementer — #8 (`../order-to-cash-dotnet`) billing page: an inaccurate sentence, LIGHT

Raised in #9 Phase 16 (`progress/history.md:1533` of #9); the maintainer approved the fix on 2026-10-17. Work ONLY in `/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-dotnet`. Its `CLAUDE.md` conventions apply there.

## The defect (leader read the file this session)

`apps/web/src/features/billing/billing-view.tsx:68`: "A line at zero is what makes an order's credit check fail." That is wrong: R39 (`specs/shared/requirements.md:318`) refuses a hold whose amount **exceeds the available credit**, so a line with some credit left still fails an order larger than it. #9's sentence for the same card (`order-to-cash-python/apps/web/src/app/pages/(app)/billing/index.page.ts:66`): "A credit check fails when the order's hold exceeds what is available (R39), so a line below the order's amount fails it, not only a line at zero." Use that wording (React: escape the apostrophe as the file already does, `&apos;`).

## Also

- `grep -rn "at zero" apps/web/src` in #8 — is the claim repeated elsewhere (another component, a test asserting the old text, the README, `docs/`)? Classify each hit; fix the ones that make the same claim; update a test that asserts the old text.
- If a test covers the card's description, it must assert the new text; if none does, add one small assertion to the existing billing view test, armed once (back up into `../order-to-cash-python/.arm/phase17/web8/` with `sha256`, restore the old sentence, run the ONE test, record the failure verbatim, `cp` back, `cmp`, green).
- Run #8's web tests and build (commands in its `apps/web/package.json` / `quality.sh`); record counts and exit codes.

## Bounds

No commit, no git command that writes the index or working tree. No package added. Only the sentence and what repeats it.

Write results to `../order-to-cash-python/progress/impl_web8_billing_credit_text.md`. Return a 3-line summary and that path.
