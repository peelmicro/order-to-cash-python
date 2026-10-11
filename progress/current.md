# Current session

**Feature:** none active — next `projector_read_model` (id 24, phase 12)
**Status:** Phase 11 closed and committed at the full wrap-up (2026-10-11); Phase 12 not started
**Session started:** —

## Goal

## Decisions taken this session

## Blockers

## Notes

**Resume point:** Phase 11 is done: feature 23 `notifications_service` is committed (`git log`). Phase 12 starts in a **fresh session** (CLAUDE.md, one session per phase) from this file. The `otcpy` developer stack is **stopped** except `otcpy-n8n`; restart it with `docker compose -p otcpy -f docker-compose.infra.yml start` when a live check needs it (MongoDB is `mongodb` in that file, image `mongo:8.3.8`).

**Live dev data, read before any live walkthrough:** the registers of altered live fixtures are in `progress/impl_billing_credit.md` §8 (K5), `progress/impl_billing_invoicing.md` (K section), `progress/impl_billing_remittance_intake.md` §9 (K5) and `progress/impl_notifications_service.md` §11. `ORD-000008`, `ORD-000010` and `ORD-000011` are `completed`; `ORD-000009` and `ORD-000012` are `cancelled`; `ORD-000007` is stalled at `confirmed` (do not use it); throwaway `ORD-000090` exists only in Billing's ledger. The three fact topics carry 16 duplicate fact records from Phase 11's byte-identical redelivery, and the `notifications` consumer group has committed offsets. **A projector that replays the topics from the beginning will see every one of these, duplicates included** — which is the replay case acceptance item 2 asks for, and a reason to record the topic contents before the walkthrough.

**Brief for phase 12 — Projector service (Plan step 17).** One feature: **24 `projector_read_model`** (`sdd: true`, **eight** acceptance items in `feature_list.json` — count them with `python3 -c` before quoting; items 5 (SA-2), 6 (backlog 212's projector half), 7 (backlog 201's gate decision) and 8 (feature 43's carried registration guard) are carried items; read them in full).

- **Process:** `sdd: true` → **spec_author first** (premise-check its brief), then **STOP at the human gate**; the implementer starts only after the maintainer approves. Full group (MongoDB persistence, a Kafka consumer over all fourteen facts, the read-model contract the Gateway and web read) → Opus reviewer. At most one rejection round without asking. Findings fixed in the phase that detects them.
- **Gate decision owed (acceptance 7, backlog 201):** (a) resolve a responder fact's command `causationId` to the triggering fact — an `SA-6` applied to #7, #8 and #9 — or (b) keep R12's semantics and render only what a live timeline can show. Go to the gate with a recommendation and evidence from #7's and #8's code, never a menu.
- **Baselines:** #8 `../order-to-cash-dotnet/progress/history.md` line 1546 (rejected three times, every rejection on records, the ported-idiom ledger's most expensive row); #7 `../order-to-cash-nestjs/progress/history.md` line 988 (rejected once, on bookkeeping only). #8 backlog: enumerate every entry whose subject is a Projector mechanism with a command over `../order-to-cash-dotnet/feature_list.json` and classify each hit (Phase 11's search for Notifications returned 23 ids; the subject test is the classification, not the regex).
- **What #9 already has:** `services/projector/` is a skeleton (`presentation/app.py`, a health test, empty layers; no `composition.py`, no `main.py`, no persistence). `tests/fixtures/read_model_constants.json` is the file acceptance 6 pins to (the seed is already pinned to it). Notifications' host (`services/notifications/src/otc_notifications/{composition,main}.py`) is now the newest template for a **Kafka-consuming** service, including the grace-then-cancel shutdown and readiness that drops when the consumer task dies.
- **A question the spec must answer, not assume:** the Orders parity guard `services/orders/tests/unit/test_idempotent_consumer_parity.py` selects its services by `has_relational_ledger` (a `processed_events` table in `infrastructure/persistence/models.py`). The Projector deduplicates in its MongoDB document (`processedEventKeys`, prefix `projector:`), so the guard will **not** examine it at all. That is the shape of #7's OI12 flaw (`../order-to-cash-nestjs/progress/history.md` line 974: the discriminator was "a file the implementer chooses whether to create"). How did #7 and #8 guard the Projector's dedup, and what guard does #9 owe it?
- **Lessons from Phase 11 to put in every brief:**
  - **A subagent can stall while still listed as running** (feature 23's implementer: 9 h 28 min with no artefact, then resumed on one `SendMessage`). Check file mtimes and `ps` before assuming progress; never let a stalled agent's half-set status stand (it had set `in_review` with TODOs in its record).
  - **A lifespan claim needs a guard that fails fast:** this project's pytest has no timeout plugin, so a missing `task.cancel()` made a test hang indefinitely (N1). Bound such waits with `asyncio.timeout(...)` and a message naming the claim.
  - **Say which restart a test performs** (N2): a runtime rebuilt in one process is not a process restart; name the guard against a process-wide cache.
  - **Ledger rows need a file:line on both halves** (N3, recurred from Phase 8): "none owed" too.
  - **A new service's settings go into `.env.example` in the same phase** (N4): the brief must route it to the leader, who owns root config.
  - **Counts in a brief come from a command:** the Phase 11 resume brief said "six acceptance items" where there were five.
- **`quality.sh` reference:** ~360 s (maintainer, Phase 9 gate); **443 s wall at the Phase 11 wrap-up** (`3782 passed in 419.44s`), above the reference, for the maintainer to re-baseline or not.
- **Carried into later features (read them when those features open):** backlog **213** on feature 41 (`saga.md` §2 has no `credit.release` row — an SA-n at that gate); feature **25**'s two items from Phase 10 (the payment's `x-correlation-id` must be the order id; the payment `RpcError` → HTTP mapping of `openapi.yaml:673-675`); feature **27** owns Notifications' dead-letter and retry (#8 ids 74, 75, 94, 104 classified there in `progress/impl_notifications_service.md` §4).
- **Accepted, with a re-open trigger:** feature 18's N3 (`OrderDespatched` extends `StockEventBase`; re-open on the next change to `otc_fulfillment.domain.events`); feature 20's O1 (`1.0000000000000001` parses as `1.0` in all three builds; re-open if a build adopts a decimal-exact parse); feature 19's N3 (the unknown-ledger-type message reads as a sentence).
- **Commits:** the spec commit, then the implementation commit (`projector_read_model`), plus an `SA-6` commit on its own if the gate takes option (a).

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
