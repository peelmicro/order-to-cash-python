# Current session

**Feature:** none active — Phase 15 done, **awaiting the maintainer's "full wrap-up"** (nothing committed yet); next phase 16 (Web app): `web_app` (id 29, `sdd: false`)
**Status:** feature 28 `saga_e2e_verification` **done** (light, closed by the leader on 2026-10-13 after reading the diff, re-checking the three arms' restores with `cmp`, one green run and the full `quality.sh`); effort entry in `progress/history.md` (last entry)
**Session started:** 2026-10-13 06:22 CEST

## Goal

Phase 15: feature 28's five acceptance items in one composed in-process suite (`tests/saga_e2e/`). Done.

## Decisions taken this session

- 06:23 one implementer pass (light), 06:42 returned: 5 passed, no production defect, three arms red and restored. Leader check: diff read, `cmp` of every armed file against its backup, `git status` clean under `services/` and `packages/`, one run 5/0/0/0 (pytest 27.9 s), full `quality.sh` (numbers in the history entry).
- R56 marked **green** in `specs/shared/test-matrix.md` (composed-stack leg; #8 counts it green on the same leg): 56 green / 1 scoped / 6 not yet green.
- Five dispositions accepted with re-open triggers (history entry).

## Blockers

None.

## Notes

**Uncommitted at session end (for the wrap-up):** `tests/saga_e2e/` (4 files), `progress/impl_saga_e2e_verification.md`, `feature_list.json` (id 28 → `done`), `specs/shared/test-matrix.md` (R56 row and the two count rows), `progress/history.md`, this file. One commit: `test(saga): …` (draft in the session report). Nothing under `services/` or `packages/` changed.

**Resume point:** the `otcpy` developer stack is **stopped** except `otcpy-n8n`; restart it with `docker compose -p otcpy -f docker-compose.infra.yml start postgres mongodb kafka nats` (add `otel-collector jaeger prometheus mailpit` for traces, metrics and email) and **wait for Kafka to report healthy** before starting any host (README, *Running the services*). The live dev data registers listed in Phase 14's brief are unchanged (Phase 15 touched no developer database or topic: testcontainers only).

**Brief for phase 16 — Web app (Plan step 21).** One feature: **29** `web_app`, **`sdd: false`**, **seven acceptance items** (count: `python3 -c "import json;print(len([f for f in json.load(open('feature_list.json'))['features'] if f['id']==29][0]['acceptance']))"`): the Nitro BFF ported from #7's `apps/web/server` (sealed httpOnly session cookie, server-side Gateway client, SSE proxy forwarding `Last-Event-ID` and aborting upstream on disconnect — the JWT never reaches the browser); types generated from `specs/shared/openapi.yaml` with a drift check; money from `shared_kernel`'s ISO 4217 table (SA-5), parity-checked both ways; every error shown is that error's own problem-document text (a behavioural sweep failing every request each page makes); the pages (login, orders list, place order, order detail with the live timeline and causal links, stock list + replenish, billing invoices + Register payment + credits); #8's inherited ids 98, 100, 101, 102, 103, 106, the stack label `#9 · Python / Angular`, `WEB_PORT=3010`; backlog 201's "caused by" claims describe live behaviour.

- **Classification:** **mixed.** The BFF (session, cookie, token custody, SSE proxy) is **security → full group** (implementer, then an Opus reviewer, arming and the defeat list). Pages, layout and text are **light**. Split the feature into stages, one implementer pass each, with a leader checkpoint between them (Phase 14's lesson): (1) BFF + auth + generated types + drift check; (2) money formatting + parity; (3) orders pages + live timeline; (4) stock and billing pages; (5) the error-text sweep + inherited ids. Review the BFF stage on its own.
- **Baselines:** this is the trilogy's most-reviewed feature. #8 `../order-to-cash-dotnet/progress/history.md:2832` (approved at review round 4, three rejections — one generic error notice, harness edits that `.env.example` clobbered); #7 `../order-to-cash-nestjs/progress/history.md:1101` (14 pass sections, 7 review passes). Read both reviews' rejection reasons into the briefs as acceptance criteria before the first pass.
- **Already in place:** `apps/web/` was scaffolded in Phase 5 (Analog 2.8.0 / Angular 22, pnpm 12.8.1 pinned in `packageManager`, build-script decisions in `apps/web/pnpm-workspace.yaml`); `quality.sh` step 7 already runs the web gates. Runners: Vitest via `@analogjs/vitest-angular` + Angular Testing Library, Playwright for e2e — no Jest/Karma/Jasmine. Port 3000 is often taken: `WEB_PORT=3010`.
- **Process lessons carried:** every test under `setsid --wait` with the result from an artifact; arming never deletes or moves a tracked path; "cannot be armed" needs the failed probe; a shape #7 and #8 agree on is still evidence, not authority (ask whether `specs/shared/` decides it); **wait on a PID, never on `pgrep -f`** (Phase 15: an implementer's `until ! pgrep -f "pytest tests"` loop matched its own command line and never ended; the leader killed it).
- **`quality.sh` time (maintainer ruling, 2026-10-11):** record pytest's time and pass count, raise it only if the time per test rises by more than 25 % over the previous wrap-up. Last value: Phase 15's (history entry).
- **Accepted, with a re-open trigger:** Phase 15's set is in its history entry; earlier phases' are unchanged.
- **Carried into later features:** feature **29** owns the "caused by" UI claim (backlog 201 acceptance 2) and R55's web half; feature **31** `api_tests` runs the black-box script against the Gateway; feature **35** builds the dashboards over feature 27's five series.
- **Commits:** one per feature (or per service when features of one phase rewrite the same files, Phase 13 ruling); an amendment always on its own and before the code that depends on it.

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
