# Current session

**Feature:** none active — next phase 18 (API tests): `api_tests` (id 31, `sdd: false`)
**Status:** Phase 17 closed and committed at the full wrap-up (2026-10-18); Phase 18 not started. Feature 30 `web_component_tests` **done** (light, closed by the leader: diff read, `quality.sh` green); effort entry in `progress/history.md` (last entry). #7's list-page fixes and #8's credit sentence committed and pushed in their own repositories.
**Session started:** 2026-10-17 (one session, closed on 2026-10-18)

## Goal

Phase 17: feature 30's three acceptance items, plus the maintainer-approved #7 and #8 web fixes. Done.

## Decisions taken this session

- Inventory before code: items 1 and 3 were already met by Phase 16's page tests; item 2's real-server test closed the stream cleanly, so three forced-disconnect cases were added (`response.destroy()`, give-up, 401).
- Angular Testing Library restored (feature title, CLAUDE.md, #7/#8 parity), pinned **19.5.0**: 19.6.0 was published the same day and pnpm wanted a release-age exception, refused. Rule for briefs: read `npm view <pkg> time` before naming a version.
- #7: stock, orders, invoices and credit-line pagers no longer claim a count while loading or after a failure; the stock replenish outcome no longer shows "…". #8: `billing-view.tsx:68` states R39.
- #7's older page specs never run Testing Library's cleanup (no Vitest `globals`): **ACCEPTED, NOT FIXED** (maintainer chose the wrap-up); re-open trigger in the history entry.

## Blockers

None.

## Notes

**Committed:** `4c06738`, the feature commit (apps/web tests, `@testing-library/angular` 19.5.0, README, `docs/PROCESS.md`, `feature_list.json`, `progress/`), pushed; #7 `32b3c25` (list pages) and #8 `c5b9cb6` (credit sentence), each with its own history entry, pushed. The external Plan (Phase 17 COMPLETED; benchmark rows for `web_app`, which Phase 16 had left out, and `web_component_tests`), Solution Documents (Parte 18, F71), Stack Comparison (web-tests row ✔ Angular Testing Library, *Cierre de la Fase 17 del #9*) and both quizzes (chapter 18 each, re-embedded, checked in headless Chromium: no page errors, the new text in *Documento*) updated at the wrap-up; backups in `.arm/phase17/external/`. Pushing needs `peelmicro`'s token (the per-command credential helper; never `gh auth switch`). Phase 18 starts in a **fresh session** from this file.

**Resume point:** the developer stack was down for the whole of Phase 17 (only `otcpy-n8n` up); check `docker ps` and `ss -ltn` first. After a web rebuild, a browser tab needs a full reload (Ctrl+Shift+R).

**Brief for phase 18 — API tests (Plan step 23).** One feature: **31** `api_tests`, **`sdd: false`**, **six acceptance items** (count: `python3 -c "import json;print(len([f for f in json.load(open('feature_list.json'))['features'] if f['id']==31][0]['acceptance']))"`): happy and compensation paths; a duplicate `paymentReference` yields one payment; #7's assertions inventoried (from #8's inventory) and each mapped; the causal-order check fails when it checked too few edges (#8 id 105); R49's API half with Billing's own database unchanged; R1's API half — every monetary field of every Gateway response an integer with an ISO 4217 code, discovered by shape (port #8's `MoneyFieldSweep`, `../order-to-cash-dotnet/tests/Gateway.IntegrationTests/MoneyFieldSweep.cs`, `MoneyRepresentationHttpTests.cs`), armed with a wrong-shape currency and a non-integer amount; flips R1 from scoped to green.

- **Classification: full group** (wire contract: R1's money representation, R49's refusals against Billing's database). Implementer, then an Opus reviewer, premise_checker over the brief first.
- **Start from what exists:** `tests/saga_e2e/` (Phase 15) already boots the Gateway, Orders, Fulfillment, Billing and the Projector in-process over testcontainers and drives orders through the Gateway; ask whether the black-box script reuses that fleet fixture (and how it keeps the Gateway black-box: httpx as the only client) before building another.
- **Baselines:** #8 `../order-to-cash-dotnet/progress/history.md:3079` (≈1 h 30 min implementer, approved first review; its N1 — no at-least-one-edge check in `AssertCausalOrder` — is #8 id 105, an acceptance item here); #7 `../order-to-cash-nestjs/progress/history.md:1168` (approved on the third review).
- **Matrix rows this phase can move:** R1 (scoped → green), R24's API half (feature 31), R49 (not yet green). Recount the Status column by script before and after: 57 green / 1 scoped (R1) / 5 not yet green (R24, R28, R48, R49, R61) at the end of Phase 17, where R29 counts green because both of its cases are DONE.
- **Process lessons carried:** integration suites must pass with the developer infrastructure down; every run under `setsid --wait`, wait on a PID; arm backups in the ROOT `.arm/`; a test that fails once on a green tree is a finding until its mechanism is shown.
- **`quality.sh` time:** Phase 17: 23 min 10 s wall; pytest 5 231 passed in 843.28 s (0.161 s per test); web 35 files / 687 tests, Vitest 524.73 s.
- **Carried into later features:** feature **32** `e2e_playwright` has the Chromium keystroke check (feature 29 stage 2, item 8).
- **Commits:** one per feature; an amendment always on its own and before the code that depends on it.

---

## Template (reset to this on session close)

```markdown
# Current session

**Feature:** `<name>` (id <n>, phase <n>)
**Status:** <status>
**Session started:** <date>

## Goal

## Decisions taken this session

## Blockers

## Notes
```
