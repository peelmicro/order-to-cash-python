# Current session

**Feature:** none active — next phase 14 (Reliability + observability): `observability_reliability` (id 27, `sdd: true`)
**Status:** Phase 13 closed and committed at the full wrap-up (2026-10-12); Phase 14 not started
**Session started:** —

## Goal

## Decisions taken this session

## Blockers

## Notes

**Resume point:** Phase 13 is done: features 25 `gateway_rest_auth`, 40 `orders_catalog_responder`, 41 `orders_cancel_responder`, 26 `gateway_sse_push`, backlogs 213, 215, 216, and amendments `SA-7`, `SA-8`, `SA-9` are committed (`git log`; the three amendments also in #7 and #8). Phase 14 starts in a **fresh session** (CLAUDE.md, one session per phase) from this file. The `otcpy` developer stack is **stopped** except `otcpy-n8n`; restart it with `docker compose -p otcpy -f docker-compose.infra.yml start postgres mongodb kafka nats` and **wait for Kafka to report healthy** before starting any host (README, *Running the services*).

**Live dev data, read before any live walkthrough:** the registers of altered live fixtures are in `progress/impl_billing_credit.md` §8 (K5), `progress/impl_billing_invoicing.md` (K section), `progress/impl_billing_remittance_intake.md` §9 (K5), `progress/impl_notifications_service.md` §11, `progress/impl_projector_read_model.md` §9, `progress/impl_gateway_rest_auth.md` §8, `progress/impl_orders_cancel_responder.md` §9 and `progress/impl_gateway_sse_push.md` §12. `otc_orders` is at migration **`0002`** (`saga_commands.operator_note`). `ORD-000008`, `ORD-000010`, `ORD-000011`, `ORD-000013` and `ORD-000021` are `completed`; `ORD-000009`, `ORD-000012`, `ORD-000018` and `ORD-000019` are `cancelled` (`ORD-000019` with a late credit approval released); `ORD-000020` is `invoiced` (its operator cancel was overtaken by the despatch); `ORD-000007` is stalled at `confirmed` in Orders but **projects `despatched`** (do not use it); throwaway `ORD-000090` exists only in Billing's ledger. The three fact topics hold 24 extra copies of 8 events (Phase 11's redelivery). The `projector` group is current; the **`notifications` group did not run during Phase 13's walkthroughs**, so its lag holds those orders' facts and it will send their emails when it next starts. The developer `.env` was brought up to `.env.example` by the leader on 2026-10-12 (50 keys appended; backup `.arm/env/.env.before`).

**Brief for phase 14 — Reliability + observability (Plan step 19).** One feature: **27** `observability_reliability`, **`sdd: true`** — so a `spec_author` pass and the **human gate** between `spec_ready` and `in_progress`. **Thirteen acceptance items** (count: `python3 -c "import json;print(len([f for f in json.load(open('feature_list.json'))['features'] if f['id']==27][0]['acceptance']))"`); items 8 – 13 are carried — 8 (feature 16: re-run the saga's SO9 arms after the consumer retry / DLQ wrapper, #8 id 94), 9 (feature 42's deferral), 10 – 11 (feature 24: fact consumers starting from `earliest` on private topics, and re-running the Projector's `I4-commit-before-handler` and `PR38` arms after the wrapper), 12 (feature 41: store a synthetic `orders.cancel.requested` envelope on the operator-cancel release row when the triggering-envelope columns land), 13 (feature 26: no ERROR line from an SSE stream open at Gateway shutdown). R62 (requestId idempotent replay in Orders: `order_mapper.py:53` stores `request_id = NULL` today; the Gateway already forwards `Idempotency-Key` as `requestId`) and R56 – R60 are its rows (`specs/shared/test-matrix.md` §8).

- **Baselines:** #8 `../order-to-cash-dotnet/progress/history.md` line 2122 (*four review rounds, three rejected, ≈3.1× #7*) and its follow-ups ids 71, 74, 75, 94, 104; #7 `../order-to-cash-nestjs/progress/history.md` line 1055 (approved first time). The orchestrator's approved design names the seams: `specs/order_saga_orchestrator/design.md` §9.8 (consumer retry / DLQ wrapper, the dead-letter columns `triggering_event_envelope`, `triggering_event_topic`, `dead_lettered_at` — revision `0003`, independent of feature 41's `0002`, metrics, `traceparent`).
- **The spec pass must decide, with #7's and #8's citations:** the retry / DLQ policy per consumer (Orders saga, Notifications, Projector) under `SA-3`'s header semantics; the log contract (structlog JSON, `correlationId` on every line, uvicorn's loggers — item 13); OTel propagation through NATS headers and Kafka headers (item 1's one trace); readiness against **paused** real containers (item 4); the five metric series names the reused dashboard queries (item 6).
- **Process lessons from Phase 13, for every brief:**
  - **A fixture must differ from every plausible wrong order — including the order a sibling column would give** (feature 40: rows inserted out of code order still sorted every name, EAN and symbol like the codes, so `ORDER BY name` passed).
  - **No ledger row may say "cannot be armed" without the probe that failed to arm it** (feature 26 B1: the reviewer armed it in 20 lines while 73 tests stayed green). "No guard owed" needs the same evidence.
  - **A test's name is a claim**: four tests this phase were named for a property they could not see (feature 25's "three different numbers", 26's "resumes without a gap", 40's N1 and N5). Reviewers now check names against assertions.
  - **Hand-built where #7 / #8 got it free** recurred once more: FastAPI's strict body validation, worked around by hand, turned a non-JSON body into a 500 on every body route (feature 25 B1). Ask the ledger question of every framework workaround.
  - **Spec-rooted findings: reproduce before the gate.** `SA-8` reached the maintainer with a real-host reproduction and leader-verified citations in #7 and #8, and was approved in one line.
  - **The leader's own instructions are a deliverable — run them before handing them over.** The Phase 13 manual-test commands failed three ways (an `.env` without the new settings, hosts started before Kafka was healthy, a `<id>` placeholder bash read as a redirect, and a `jq` path that ignored the `{"items": [...]}` wrapper). Check the commands against the contract and a live stack, or say they were not run.
  - **`pkill -f <pattern>` matches the shell that runs it** (exit 144 at the wrap-up): stop processes by PID.
  - Phase 12's still apply: arm a guard at the service's real n; wait on the real PID; after a second rejection, propose a scoped round with a stopping rule written first; bounded waits, paced retries, counts from a command.
- **`quality.sh` time (maintainer ruling, 2026-10-11):** record pytest's time and pass count, raise it only if the **time per test** rises by more than 25 % over the previous wrap-up. Last value: **641.18 s / 4 770 passed = 0.134 s per test** (Phase 12: 0.120; the same tree measured 0.127 in the fix-round run, 0.120 in feature 26's).
- **Accepted, with a re-open trigger (Phase 13):** feature 25 — C3 / C8 (equivalent mutants under PyJWT 2.15.1; re-open on an upgrade past 2.15.x), Q3a (the lambda-handler residual does not apply), R2-N2 (a new body route mounted outside the scanned routes); feature 40 — N6 (the parties' `ORDER BY` deletion invisible to the companies include-disabled population; re-open on a change to that join or fixture); feature 41 — N2 (`find_accepted_operator_cancel` has no status filter; re-open if Fulfillment gains a terminal refusal of a `reserved` reservation's release), N4; feature 26 — ST8 and the listed-helper-gains-a-caller limit of the status population test. Earlier phases' (unchanged): feature 18's N3, feature 20's O1, feature 19's N3, Phase 12's set (`progress/impl_projector_read_model.md` §4.2, `progress/review_projector_read_model.md`).
- **Carried into later features:** feature **29** owns the "caused by" UI claim (backlog 201 acceptance 2) and R55's web half; feature **31** `api_tests` will run the black-box script against the Gateway (the n8n workflows are feature 33's).
- **Commits:** one per feature, or per service when features of one phase rewrite the same files (Phase 13 ruling, `docs/PROCESS.md` §10); an amendment always on its own and before the code that depends on it.

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
