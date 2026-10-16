# Current session

**Feature:** none active — next phase 17 (Web component tests): `web_component_tests` (id 30, `sdd: false`)
**Status:** Phase 16 closed and committed at the full wrap-up (2026-10-16); Phase 17 not started. Feature 29 `web_app` **done** (stages 1–3 approved by Opus reviews, stage 4 by a scoped Sonnet review; the leader's full `quality.sh` green after a sweep-premise fix); effort entry in `progress/history.md` (last entry). The full session log of Phase 16 is in `.arm/phase16/current.session4.md` (git-ignored) and in the history entry.
**Session started:** 2026-10-15 (four sessions; the last on 2026-10-16)

## Goal

Phase 16: feature 29's seven acceptance items, in four stages. Done.

## Decisions taken this session

- Stage 4: the order link after a payment ported (#7 and #8 both have it); no order-detail → billing link (neither has one); R55's Status cell filled (column 5 is per-assessment, not an `SA-n`; #8 did the same in `83223f1`) and R55 is **DONE** (57 green / 1 scoped / 5 not yet green).
- The sweep premise "every reviewed label is produced" failed in the leader's gate after being approved as not reproducible; fixed (fixture texts judged against the baseline's final page), armed, gate green.
- Manual test by the maintainer on the full stack; one light change from it: the replenish message names the company (#9-only wording).
- `.env` gained the four `WEB_*` keys (backup `.arm/env/env.before-phase16`).

## Blockers

None.

## Notes

**Committed:** the feature commit (apps/web, the R55 cell, README, `docs/PROCESS.md`, the seed README, `.env.example`, `quality.sh`, `init.sh`, `feature_list.json`, `progress/`), pushed; #7's number-box fix committed and pushed in `../order-to-cash-nestjs`. The external Plan, Solution Documents, Stack Comparison and both quizzes updated at the wrap-up. Phase 17 starts in a **fresh session** from this file.

**Resume point:** at the wrap-up the developer stack and every host (Orders 8101, Fulfillment 8102, Billing 8103, Projector 8105, Gateway 3001, web 3010) were left **running** for the maintainer; check `docker ps` and `ss -ltn` first. Stop them by port (`for p in 3010 3001 8101 8102 8103 8105; do fuser -k -TERM $p/tcp; done`) and `docker compose -p otcpy -f docker-compose.infra.yml stop postgres mongodb kafka nats`. After a web rebuild, a browser tab needs a full reload (Ctrl+Shift+R): the single-page app keeps the old code in memory.

**Brief for phase 17 — Web component tests (Plan step 22).** One feature: **30** `web_component_tests`, **`sdd: false`**, **three acceptance items** (count: `python3 -c "import json;print(len([f for f in json.load(open('feature_list.json'))['features'] if f['id']==30][0]['acceptance']))"`): timeline, place-order form, stock and billing tables covered; the SSE service tested with a fake EventSource AND against a real local SSE server with a forced mid-stream disconnect; loading-state tests hold the request on an unresolved promise.

- **Start with an inventory, not with code.** Feature 29 already ships 33 Vitest files / 668 tests, including `R-list-states` / `R-stock-states` / `R-billing-states` (requests held on unresolved promises), `order-detail.spec.ts` (timeline, `R-stream-live`, `R-dedup`), and the BFF's SSE contract on a real socket (`src/server/testing/bff-contract.ts`, `R-stream`). Map each of feature 30's three items to existing tests by name (a search result, one classification per hit) before writing anything; write only what is missing. Does a *client-side* SSE test with a real local SSE server and a forced mid-stream disconnect exist (the browser half, `Last-Event-ID` re-sent on reconnect)? That is the likeliest gap; #7 has it in `app/lib/order-stream-client.spec.ts` (history `web_app` entry) and #8 in `apps/web/src/lib/order-stream-client.test.ts`.
- **Baselines:** #8 closed id 30 together with id 29 (`../order-to-cash-dotnet/progress/history.md:2884`); #7 `../order-to-cash-nestjs/progress/history.md:1124`.
- **Classification:** test-only → **light** (one implementer, the leader reads the diff and runs the tests), unless the inventory finds a product defect, which is then fixed in the phase as full group.
- **Process lessons carried:** a test that fails once on a green tree is a finding until its mechanism is shown — seven green runs are not evidence (Phase 16's sweep premise); give a flaky assertion a diagnostic message before chasing it; jsdom cannot show caret, `badInput` or `change` behaviour (three Phase 16 defects were found only in Chromium; the Chromium keystroke check is carried to feature 32); arm backups go in the ROOT `.arm/` (only `/.arm/` is git-ignored; a Phase 16 backup written from `apps/web` landed in `apps/web/.arm/` and would have been committed); every test under `setsid --wait`, wait on a PID.
- **`quality.sh` time:** Phase 16: 875.31 s inside pytest, 5 231 tests (0.167 s per test, +1.4 %); web 33 files / 668 tests.
- **Open for the maintainer (not blocking):** two cosmetic #7 stock-page leftovers (`stock/index.vue` `?? '…'` placeholder; the pager count while loading); for #8, `billing-view.tsx:68` claims a credit check fails only at zero (R39: it fails when the hold exceeds available credit); a text caret seen in the maintainer's screenshots is not drawn by the app and not caret browsing (suspected a browser extension).
- **Carried into later features:** feature **32** `e2e_playwright` has the Chromium keystroke check (feature 29 stage 2, item 8); feature **31** `api_tests` runs the black-box script against the Gateway.
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
