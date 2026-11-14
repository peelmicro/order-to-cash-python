# Current session

**Feature:** none active. Next is phase 22 (observability verification): `observability_dashboards` (id 35, `sdd: false`).
**Status:** Phase 21 is closed and committed at the full wrap-up (2026-11-14); Phase 22 has not started.
- **Feature 34** `sonarqube_quality_gates` is **done**: light, closed by the leader after reading the diff and re-running the checks. Record `progress/impl_sonarqube_quality_gates.md`; effort entry: the last one in `progress/history.md`.

**Session started:** 2026-11-14; wrap-up on 2026-11-14.

## Goal

Phase 21: feature 34's three acceptance items. Done.

## Decisions taken this session

- **Classification light**, inherited from #8 (`../order-to-cash-dotnet/progress/history.md:3152`).
- **Scope check at the start:** id 34 was the only phase-21 entry in `feature_list.json`, the Plan and the Stack Comparison.
- **Maintainer's decision: "Fix 1, suppress 24"** for the first scan's bugs and vulnerabilities (1 latent sort in a web test helper fixed; 24 false positives suppressed as 14 rule-by-file entries with reasons).
- **Web coverage not imported**, as in #8 (`../order-to-cash-dotnet/sonar-scan.properties:48-65`). **No compose change for Elasticsearch's disk watermark**, as in #7, which freed disk (`../order-to-cash-nestjs/progress/impl_sonarqube_quality_gates.md:146`).
- **Lesson for briefs:** `ANALYSIS SUCCESSFUL` and exit 0 hid two real defects (coverage paths resolving to nothing; a properties continuation dropping six exclusions). Check the server and the scanner's own echo of its configuration, never the success line. The leader caught the second in the diff, not the implementer.

## Blockers

None.

## Notes

**Committed:**
- `3fb96c5` (feature 34, with README, `docs/PROCESS.md`, the records and this brief), then this file's closing commit. Pushed with `peelmicro`'s per-command token.
- **External documents** updated at the wrap-up, with backups and sha256s in `.arm/phase21/external/` (`REPORT.md` there): the Plan (Phase 21 COMPLETED, the `sonarqube_quality_gates` benchmark row, ≈2.9× #7, no ratio to #8); the Solution Documents (Parte 22: F78 `sonar-project.properties`, F79 `scripts/sonar-scan.sh`, and a dated note in F28); the Stack Comparison (*Cierre de la Fase 21 del #9*; the Python "Calidad" cell extended, already ✔ since Phase 5); both quizzes (chapter 22 each, six questions, re-embedded, checked in headless Chromium).
- **The maintainer's manual test passed** before the wrap-up: lint and type steps, both coverage reports, and the SonarQube script, with the same server numbers as the leader's run.

**Resume point.** The developer stack is down; `otcpy-sonarqube` is stopped (volumes `otcpy_sonarqube_extensions`/`_logs` exist; no `_data` volume, because the scans used `.arm/phase21/sonar-override.yml`, a tmpfs data directory, which is git-ignored). The other project's `kb-poc-*` containers run (`kb-poc-proxy-1` holds 8080). The disk holding Docker is at 91%. Check `docker ps`, `ss -ltn` and `df -h /` first.

**Brief for phase 22: observability verification (Plan step 26).** One feature: **35** `observability_dashboards`, **`sdd: false`**, **three acceptance items** (count: `python3 -c "import json;print(len([f for f in json.load(open('feature_list.json'))['features'] if f['id']==35][0]['acceptance']))"`): all five panels live with the series names checked in Prometheus; the dashboard auto-provisioned; one distributed trace recorded with spans, services and depth against #7 and #8. The Plan adds: names checked **in Prometheus**, not by grep; one Jaeger trace HTTP → NATS → PostgreSQL → Kafka → consumers against #7 (22 spans, depth 11) and #8 (42 spans, 6 services, depth 26); continuity read off real `outbox.trace_parent` rows.
- **Classification: light**, inherited: #8 ran it LIGHT, one implementer, no reviewer (`../order-to-cash-dotnet/progress/history.md`, the id 35 entry after the id 108 entry). Confirm nothing in #9 forces a difference before dispatch.
- **Measured by the leader at this wrap-up:** `infra/grafana/dashboards/order-to-cash-overview.json` queries `otc_saga_completion_ms_bucket`, `otc_request_latency_ms_bucket`, `otc_fact_processing_latency_ms_bucket`, `otc_outbox_lag_ms` and `otc_dlq_depth`, i.e. #8's corrected names, without the `_milliseconds` suffix that #7's dashboard carried (#8 found 4 of 5 panels empty for that reason). `grep -rn "create_histogram\|create_observable_gauge\|create_gauge\|create_counter" services/*/src packages/*/src` counts 36 call sites. The README says `scripts/dev-stack.sh` leaves `OTEL_EXPORTER_OTLP_ENDPOINT` empty unless set, because the collector is not part of that stack.
- **Ask, do not answer:** does any #9 instrument pass a `unit=` (the 36 sites, including multi-line declarations), and what name does the Python OTel → collector → Prometheus path actually produce for it? Does the collector's Prometheus exporter add a suffix? Which stack runs the phase: `dev-stack.sh` plus the observability profile with `OTEL_EXPORTER_OTLP_ENDPOINT` set, or something else, and does the README need that recipe? #8 filed id 109 (instrument units against the dashboard's names): does that question exist in #9 at all?
- **Scope check before closing:** every entry with phase 22 in every document that names one (`feature_list.json` has only id 35 today; the Plan's `### Phase 22`; the Stack Comparison).
- **Process lessons carried:** every run under `setsid --wait`, waited on by PID; arm backups in the root `.arm/`; stop processes by PID, never `pkill -f`; never touch `kb-poc-*` or other projects' unnamed testcontainers; view the screenshots before claiming a panel is live (#7's lesson: valid PromQL over the API is not a rendered panel).
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
