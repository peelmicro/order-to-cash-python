# Brief — implementer, feature 29 `web_app`, stage 3 **fix round 1** (phase 16; full group)

**Task:** fix the stage 3 review's findings. Read `progress/review_web_app.md` section "Stage 3 review" in full (B-S3-1 … B-S3-4, *What must change before re-review*, A1–A9). The reviewer's probes and arm definitions are in `.arm/web29r4/s3/` (`defs.py`, `live/age.mjs`, `live/probe.out`): reuse them, don't copy them into tracked paths. This is the one fix round allowed without asking the maintainer: a second rejection stops the work.

## Items (each with its guard, armed under the protocol; backups in `.arm/web29s3f1/`)

1. **B-S3-1:** as the review's *What must change* item 1. The test drives only the events Chromium fires from an empty box (no synthetic `change`); arm it on the current code first (it must fail), then fix. Re-run `live/age.mjs` on the production build: all four rows show the problem. Then search **every** filter and box on all pages for the same dependency on `change` (command and output, one classification per hit).
2. **B-S3-2 (leader's choice between the review's two options):** add the **render-based half**, which is mandatory: over every state the sweep reaches, every rendered element whose live `.type === 'number'` has a `data-testid` in `EXPECTED_NUMBER_BOXES`, and every expected box is rendered somewhere (both ways). **Narrow** the syntax guard's header and the record's rows 6 and 11 to what it really covers, naming the render half as the cover for R5–R7. Also extend `writesWhileTyping` to `valueAsNumber` and `valueAsDate`, which closes R8. Do not rewrite the guard on `@angular/compiler`. Re-arm R5–R8 from `.arm/web29r4/s3/defs.py`: R5–R7 must fail on the render half and R8 on the syntax half, each with its verbatim failure. List the render half's premises: does every page mount, and is every form opened? Arm each one with a sentinel, plus a box reachable only through a state the sweep never drives, as an armed demonstration of its limit (CLAUDE.md, "Changing an instrument").
3. **B-S3-3:** as item 3 (totals that differ from the typed text, and a mixed-case reference row). Re-arm R1, R1b and R4.
4. **B-S3-4:** as item 4. Re-arm F03 against the test.
5. **A1:** clear a box holding unreadable text when the replenish panel moves to another row, and add an unreadable row to `R-replenish-draft`. This touches `components/draft-value.ts` (item 8 of stage 2), so re-run G01–G05 and the `R-typing` arms afterwards.
6. **A2:** an over-range amount gets its own sentence naming the range, on every money box (place order and payment). Test and arm.
7. **A3:** add a non-canonical-bytes row to the BFF bytes test (whitespace, or `9007199254740993`) so that R3 is no longer an equivalent mutant. Re-arm R3.
8. **A4:** reword `billing/index.page.ts:64` (R39: a hold fails when it exceeds the available credit, not only at zero). Record that #8's `billing-view.tsx:68` carries the same sentence, but do not touch #8.
9. **A5–A8:** the comment corrections (A5), pager buttons in the census named per pager (A6), `PRD-0001` moved to its own fixture-label table (A7), and the quantity prefix made consistent (A8). Each with a test where it is behaviour.
10. **A9:** the live record exercises the age filter in Chromium (item 1's re-run covers it).

## Bounds, gates, output

- **Bounds:** `apps/web/**`; `progress/impl_web_app.md`. Nothing else, including `progress/review_web_app.md`, `feature_list.json`, `specs/**`, and #7/#8. No git command that writes the index or working tree. Every run under `setsid --wait timeout -k 10 …`; wait on PIDs. A live stack is optional: a stub Gateway behind the BFF is enough, as the reviewer used. Stop what you start (`docker ps`, `ss -ltnp` before and after; `otcpy-n8n` stays as found).
- **Gates:** `quality.sh` section 7's commands plus `uv run pytest packages/shared_kernel/tests/test_currency_exponent.py`. Reconcile with 32 / 644.
- **Output:** append section "Stage 3 — fix round 1" to `progress/impl_web_app.md`: per item, the change, the test name, and its arms (mutation, test, verbatim message, `sha256`, `cmp`); the re-run arms, the probe outputs, the gates, effort in minutes, and `Packages installed:`. Return only "result in `progress/impl_web_app.md`" plus at most 5 lines.
