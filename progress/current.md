# Current session

**Feature:** none active. Next is phase 20 (n8n demo workflows): `n8n_workflows` (id 33, `sdd: false`).
**Status:** Phase 19 is closed and committed at the full wrap-up (2026-11-14); Phase 20 has not started.
- **Feature 32** `e2e_playwright` is **done**: approved at the Sonnet re-review (`progress/review_e2e_playwright_round2.md`) after one Opus rejection (`progress/review_e2e_playwright.md`, D-1, D-2, N-1 – N-5, all fixed in round 2).
- Effort entry: the last one in `progress/history.md`.

**Session started:** 2026-11-14; wrap-up on 2026-11-14.

## Goal

Phase 19: feature 32's four acceptance items. Done (item 3's composed-stack run is carried as the last acceptance item of feature 36).

## Decisions taken this session

- **Classification full**, inherited from #8 (`../order-to-cash-dotnet/progress/history.md:3109`); Opus review; the re-review on Sonnet, scoped to the findings, because round 2 changed test, script and record files only (Phase 18's precedent).
- **`@playwright/test` 1.64.1**, the newest release over two weeks old at dispatch (1.65.0 2026-11-05 and 1.65.1 2026-11-13 were too new); Chromium 1248 downloaded to `~/.cache/ms-playwright`.
- **`scripts/dev-stack.sh` ported from #8** (uvicorn host processes; fail-fast on a held port naming its `*_HOST_PORT`; process-group teardown; `down` leaves what was up before). Not Playwright's `webServer`.
- Matrix: **63 green / 0 scoped / 0 not yet green**.
- **Lesson for briefs:** when two mechanisms can satisfy one assertion, the arm deletes exactly one of them, and the brief names both (the D-1 rejection: the backstop and R55's pending retry).

## Blockers

None.

## Notes

**Committed:**
- `16d4a42` (feature 32, with README, `docs/PROCESS.md`, the records and this brief), then this file's closing commit. Pushed with `peelmicro`'s per-command token.
- **External documents** updated at the wrap-up, with backups and sha256s in `.arm/phase19/external/` (`REPORT.md` there):
  - the Plan: Phase 19 COMPLETED, with the `e2e_playwright` benchmark row and the change from the plan's pinned 1.63.0 to 1.64.1;
  - the Solution Documents: Parte 20, F74 (the Playwright config and a test against the real stack) and F75 (`scripts/dev-stack.sh`), with the header, tree and "not yet" lines;
  - the Stack Comparison: *Cierre de la Fase 19 del #9*, the Python "Tests web" cell's Playwright 1.64.1 ✔ (the composed-stack run stays ◐ for phase 23), and the status header;
  - both quizzes: chapter 20 each, six questions, re-embedded. Checked in headless Chromium: 20 chapters, no page errors, the new text in *Documento*.

**Resume point.** The developer stack is down. The maintainer ran `scripts/dev-stack.sh up`, `test:e2e` (7 passed, 10.4 s) and `down` on the default ports at the wrap-up. The other project's `kb-poc-*` containers run; after their 07:16 UTC restart, `kb-poc-postgres-1` no longer publishes 5432, but `kb-poc-proxy-1` still holds 8080 (Redpanda Console's default). Check `docker ps` and `ss -ltn` first.

**Brief for phase 20: n8n demo workflows (Plan step 25).** One feature: **33** `n8n_workflows`, **`sdd: false`**, **four acceptance items** (count: `python3 -c "import json;print(len([f for f in json.load(open('feature_list.json'))['features'] if f['id']==33][0]['acceptance']))"`): all four workflows fired for real; auto-imported on container startup, idempotently; removing n8n does not break the stack; README screenshots of the four workflows.
- **Classification: light**, inherited: #8 ran it LIGHT, one implementer, no reviewer (`../order-to-cash-dotnet/progress/history.md:3137`). Confirm nothing in #9 forces a difference before dispatch.
- **Measured by the leader at this wrap-up:** `n8n/workflows/*.json` is byte-identical across #7, #8 and #9 (one combined sha256 for all three). #9's `docker-compose.infra.yml` already carries #8's phase-20 changes: `OTC_GATEWAY_URL` overridable (line 450) and `extra_hosts: host.docker.internal:host-gateway` (lines 490 – 491). #9 has **no** `scripts/import-n8n-workflows.sh` / `export-n8n-workflows.sh`; #8 has both.
- **Two items are new against #8:** "idempotently" and "README screenshots" are in #9's acceptance and not in #8's (#8's list has three items). Ask how #9 proves idempotence (#8 started the infrastructure twice from cold and counted the workflow ids in n8n's store) and how the screenshots are captured (#8 had `scripts/capture-demo.mjs`, for a GIF in phase 24).
- **Carry from #8's record:** #7's re-review said the burst webhook needs no n8n restart after activation; on #8's instance it did (a 404 first). Test it live; do not inherit either answer.
- **The services run as host processes** through `scripts/dev-stack.sh`, so n8n reaches the Gateway at `http://host.docker.internal:${GATEWAY_PORT}`. Ask whether `dev-stack.sh` should start the `n8n` profile on request, or the brief runs it by hand.
- **`otcpy-n8n` crash-loops when started without PostgreSQL** (it cannot resolve `postgres`): pre-existing, seen in Phases 18 and 19. Ask whether that is acceptance item 3's concern ("removing n8n does not break the stack" is the other direction) or a finding to file.
- **Baselines:** #8 one implementer, light, no rejection (`:3137`); #7 approved on the second review (`../order-to-cash-nestjs/progress/history.md:1281`), its first rejection for a `.99` compensation maths defect, unwired tunables and a credential-leaking `env_file`, all already fixed in the JSON #9 inherits.
- **Process lessons carried:** every run under `setsid --wait`, waited on by PID; arm backups in the ROOT `.arm/`; after an interrupted agent, compare every backup with `cmp` first; **stop processes by PID, never `pkill -f`** (an implementer ran a machine-wide `pkill -f "sleep 300"` in Phase 19); never touch `kb-poc-*`.
- **Commits:** one per feature; an amendment is always on its own and before the code that depends on it.

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
