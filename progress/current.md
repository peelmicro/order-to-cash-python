# Current session

**Feature:** none active. Next is phase 21 (quality gates): `sonarqube_quality_gates` (id 34, `sdd: false`).
**Status:** Phase 20 is closed and committed at the full wrap-up (2026-11-14); Phase 21 has not started.
- **Feature 33** `n8n_workflows` is **done**: light, closed by the leader after reading the diff and an independent stack run. Record `progress/impl_n8n_workflows.md`; effort entry: the last one in `progress/history.md`.

**Session started:** 2026-11-14; wrap-up on 2026-11-14.

## Goal

Phase 20: feature 33's four acceptance items. Done.

## Decisions taken this session

- **Classification light**, inherited from #8 (`../order-to-cash-dotnet/progress/history.md:3137`).
- **`scripts/dev-stack.sh up --with-n8n`**: n8n reaches the host-process Gateway at `host.docker.internal:${GATEWAY_PORT}`; `down` stops n8n before PostgreSQL. That was the cause of the Phase 18–19 crash-loop.
- **`n8n-init` keeps an active workflow active** across its re-import (`import:workflow` deactivated it; the inherited comment claiming otherwise was false).
- **Screenshots from a throwaway n8n** (SQLite, fictional owner) through `scripts/capture-n8n-screenshots.sh`. The real instance's owner is the maintainer's, and its UI would put a real identity into committed images.
- **Lesson for briefs:** when an item may need credentials or state the agent does not own, name the fallback in the first brief (item 4 cost a second pass). Every how-to-test call made after a restart waits for health first (the maintainer's burst `curl` hit a restarting n8n).

## Blockers

None.

## Notes

**Committed:** the feature 33 commit, then this file's closing commit. Pushed with `peelmicro`'s per-command token.

**Resume point.** The developer stack is down; the other project's `kb-poc-*` containers run (`kb-poc-proxy-1` holds 8080). Check `docker ps` and `ss -ltn` first. The four n8n workflows are inactive in `otcpy_n8n_data`'s database.

**Brief for phase 21: quality gates (Plan step 25).** One feature: **34** `sonarqube_quality_gates`, **`sdd: false`**, **three acceptance items** (count: `python3 -c "import json;print(len([f for f in json.load(open('feature_list.json'))['features'] if f['id']==34][0]['acceptance']))"`): the coverage gate proven to FAIL when breached (an artifact-corruption arm and a real-exclusion arm), computed once across the workspace; ruff and mypy clean, import-linter green; SonarQube scanning Python and TypeScript under its optional profile to `ANALYSIS SUCCESSFUL`.
- **Classification: light**, inherited: #8 ran it LIGHT, one implementer, no reviewer (`../order-to-cash-dotnet/progress/history.md:3152`). #7 was approved on its first review (`../order-to-cash-nestjs/progress/history.md:1228`). Confirm nothing in #9 forces a difference before dispatch.
- **Measured by the leader at this wrap-up:** `quality.sh` already gates coverage. Section 6 sets the overall threshold through `fail_under` in `pyproject.toml` (≥ 60%). Section 6b runs `coverage report --include='*/domain/*,packages/shared_kernel/*' --fail-under=${DOMAIN_COVERAGE_MIN:-80}`, armed once in `progress/impl_shared_kernel.md` by lowering the measurement. **There is no Sonar properties file in #9.** #8 has `sonar-scan.properties`, renamed because a file named `sonar-project.properties` made `dotnet-sonarscanner end` fail; #7 has `sonar-project.properties`. The `sonar` compose profile exists (`sonarqube:26.8.0.126808-community`).
- **Ask, do not answer:** is the coverage "computed once across the workspace" today (one data file, union by line), or per package? Which arm counts as "a real exclusion" in Python (a `[tool.coverage] omit`, or a test path left out)? Which scanner runs Python + TypeScript without a new runtime on the host (the `sonarsource/sonar-scanner-cli` image, or something else), and does #8's rename reason apply here at all?
- **Scope check before closing** (the Plan's own Phase 21 item): every entry with phase 21 in every document that names one: `feature_list.json` (only id 34 today), the Plan (`### Phase 21`), the Stack Comparison. #8 found two more items that way (`../order-to-cash-dotnet/progress/history.md`, the id 108 entry).
- **Process lessons carried:** every run under `setsid --wait`, waited on by PID; arm backups in the root `.arm/`; stop processes by PID, never `pkill -f`; never touch `kb-poc-*`; `quality.sh` takes about 25 minutes, so route it to `suite_runner`.
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
