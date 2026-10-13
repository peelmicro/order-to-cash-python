# Current session

**Feature:** none active — next phase 15 (End-to-end saga verification): `saga_e2e_verification` (id 28, `sdd: false`)
**Status:** Phase 14 closed and committed at the full wrap-up (2026-10-13); Phase 15 not started
**Session started:** —

## Goal

## Decisions taken this session

## Blockers

## Notes

**Resume point:** Phase 14 is done: feature 27 `observability_reliability` is committed (`git log`), approved at review round 2; its effort entry, every accepted disposition with its re-open trigger, and the two #7/#8 defects recorded for the trilogy are in `progress/history.md` (last entry). Phase 15 starts in a **fresh session** (CLAUDE.md, one session per phase) from this file. The `otcpy` developer stack is **stopped** except `otcpy-n8n`; restart it with `docker compose -p otcpy -f docker-compose.infra.yml start postgres mongodb kafka nats` (add `otel-collector jaeger prometheus mailpit` for traces, metrics and email) and **wait for Kafka to report healthy** before starting any host (README, *Running the services*).

**Live dev data, read before any live walkthrough:** the registers of altered live fixtures are in `progress/impl_billing_credit.md` §8 (K5), `progress/impl_billing_invoicing.md` (K section), `progress/impl_billing_remittance_intake.md` §9 (K5), `progress/impl_notifications_service.md` §11, `progress/impl_projector_read_model.md` §9, `progress/impl_gateway_rest_auth.md` §8, `progress/impl_orders_cancel_responder.md` §9, `progress/impl_gateway_sse_push.md` §12 and `progress/impl_observability_reliability.md` "S8b" § Register. `otc_orders` is at migration **`0003`** with all five dead-letter columns (`triggering_event_envelope`, `triggering_event_topic`, `dead_lettered_at`, `trace_parent`, `first_failed_at`) — the S8b walkthrough had applied a pre-review `0003`; the leader repaired it on 2026-10-13 and proved `downgrade 0002` / `upgrade head` both ways. **A migration changed after it was applied to the developer database must be re-applied: check the columns, not only `alembic current`.** `ORD-000008`, `-010`, `-011`, `-013`, `-021`, `-022` and `-024` are `completed`; `ORD-000009`, `-012`, `-018` and `-019` are `cancelled`; `ORD-000020` and `ORD-000023` are `invoiced`; `ORD-000007` is stalled at `confirmed` in Orders but **projects `despatched`** (do not use it); throwaway `ORD-000090` exists only in Billing's ledger. The three fact topics hold 24 extra copies of 8 events (Phase 11's redelivery) and **one poison fact** on `otc.orders.facts.v1` (partition 2, offset 23). Dead letters: `otc.orders.facts.v1.dlq` 17 (14 from the SMTP defect, 3 from the poison: `orders.saga`, `projector`, `notifications`), `otc.fulfillment.facts.v1.dlq` 3 (the SMTP defect) — **the 17 lagged emails were dead-lettered, never sent**; nothing redrives a `.dlq` (a manual broker operation). The `notifications` group ran in the leader's checks after the SMTP fix (Mailpit held 10 messages); confirm its lag with `kafka-consumer-groups` before relying on it. The developer `.env` carries Phase 14's three keys (backup `.arm/env/.env.before_s84`).

**Brief for phase 15 — End-to-end saga verification (Plan step 20).** One feature: **28** `saga_e2e_verification`, **`sdd: false`** — no spec pass; the leader sets it `in_progress` and briefs one implementer from its acceptance list. **Five acceptance items** (count: `python3 -c "import json;print(len([f for f in json.load(open('feature_list.json'))['features'] if f['id']==28][0]['acceptance']))"`): the happy path reaches `completed`; a `.99` order compensates visibly; redelivery corrupts nothing and a poisoned message reaches the DLQ; **R56's composed-stack half** — one trace id spans every request, command, transaction and fact for one order across the real services (`specs/shared/test-matrix.md` R56, the one feature-27 row still "not yet green"); and the suite passes with the developer infrastructure down. The Plan (§ Phase 15) asks for a real in-process fleet: the six FastAPI apps started in the test, testcontainers for the infrastructure.

- **Classification:** test-only by default → **light** (one implementer, the leader reads the diff and runs the tests); a production defect it uncovers is fixed in the phase and its fix is **full group** (implementer, then an Opus reviewer). Record the classification with the effort entry.
- **Baselines:** #8 `../order-to-cash-dotnet/progress/history.md:3239` (one implementer, no separate review, ≈54 min plus ≈22 min for a fix — **criterion 5 found a production defect**: the fast-path hand-off lost the trace context, so Orders, Fulfillment and Billing recorded three different trace ids for one order); #7 `../order-to-cash-nestjs/progress/history.md:1059`. #9's orchestrator carries the context into the fast path by design (`specs/order_saga_orchestrator/design.md` L7, §11) and feature 27 armed the mechanism per hop (S3, S4.21) — the composed run is what proves it end to end; do not assume it.
- **What exists to reuse:** feature 27's per-service harnesses (private topics with `.dlq` companions, the root `conftest.py` Kafka fixture and its OTLP blank, `health_support.paused`), the in-memory span exporter of the tracing tests, and the live walkthrough's sequence (`progress/impl_observability_reliability.md` "S8b"; the leader's live-checked commands in README *Running the services*, the observability block after the Gateway example).
- **Process lessons from Phase 14, for every brief:**
  - **One stage per implementer pass, a leader checkpoint between passes** (a full-workspace run read from a JUnit artifact, the bounds footprint, a disposition for every implementer finding) kept #9 at ≈0.44× #8 on its most expensive feature.
  - **Run every test under `setsid --wait`** and take the result from an artifact: without `--wait`, `setsid` returns at once and the status is not pytest's.
  - **An arming script never deletes or moves a tracked path**; single files, `cp` backup and restore.
  - **"Cannot be armed" needs the failed probe** — it recurred (L32) and was armable by a one-word mutation.
  - **A shape #7 and #8 agree on is still evidence, not authority:** B1 (the first-park dead-letter instants) was ported from both and contradicted `SA-3`. Ask whether `specs/shared/` decides it before porting.
  - **A live walkthrough's container list is a claim:** without Mailpit the SMTP defect would have looked like infrastructure.
  - Phase 13's still apply (fixtures that differ from every plausible wrong order; test names are claims; the leader runs the manual-test commands before handing them over).
- **`quality.sh` time (maintainer ruling, 2026-10-11):** record pytest's time and pass count, raise it only if the **time per test** rises by more than 25 % over the previous wrap-up. Last value: **831.44 s / 5 226 passed = 0.159 s per test** (Phase 13: 0.134).
- **Accepted, with a re-open trigger:** Phase 14's set is in `progress/history.md` (the `observability_reliability` entry); earlier phases' are unchanged (Phase 13's in its entries; feature 18's N3, feature 20's O1, feature 19's N3, Phase 12's set).
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
