# Current session

**Feature:** none active — next `fulfillment_stock` (id 17, phase 9)
**Status:** Phase 8 closed and committed at the full wrap-up (2026-10-07); Phase 9 not started
**Session started:** —

## Goal

## Decisions taken this session

## Blockers

## Notes

**Resume point:** Phase 8 is done: features 13, 43, 14, 15, 16 and 42 are committed, with each spec commit before its implementation commit (`git log`). Phase 9 starts in a **fresh session** (CLAUDE.md, one session per phase) from this file. The `otcpy` developer stack is **stopped** except `otcpy-n8n`; restart it with `docker compose -p otcpy -f docker-compose.infra.yml start` when a live check needs it. The dev database still holds **ORD-000007 with a parked `stock.reserve` row** from feature 16's live walkthrough. That is deliberate: when feature 17's `fulfillment.stock.reserve` responder first runs against the live stack, the sweeper should issue that row and the saga should advance. Record what happens; it is the first live proof of the park-and-resume story.

**Brief for phase 9 — Fulfillment service (Plan step 14).** Two features, in `feature_list.json` order: **17 `fulfillment_stock` (sdd)** and 18 `fulfillment_despatch` (sdd false). Range-guard backlog 207 is already done.

- **First action:** feature 17 is `pending` + `sdd: true` → one `spec_author` writes `specs/fulfillment_stock/{requirements,design,tasks}.md` → **stop at the human gate**. Brief it with the rule the maintainer gave in Phase 8: a decision #7 and #8 agree on, with no Python-forced difference, is **adopted and cited, never offered** as a gate option. Go to the gate with a recommendation and evidence (check what #8 and #7 did first, verified by command).
- **Process:** full group for both (persistence, the stock responders the saga calls, concurrency). Premise-check every brief; Opus reviewer; at most one rejection round without asking; findings fixed in the phase that detects them.
- **Baselines:** #8 `../order-to-cash-dotnet/progress/history.md` — fulfillment_stock :999 (three review rounds, two blocking defects of one shape), fulfillment_despatch :1126, Phase 9 closing assessment :1167. #7 `../order-to-cash-nestjs/progress/history.md` — :842 and :863. #7's spec is at `../order-to-cash-nestjs/specs/fulfillment_stock/`, #8's at `../order-to-cash-dotnet/specs/fulfillment_stock/`. #8 backlog entries in the Fulfillment area, to be mapped by the spec as avoided or assigned: ids **49** (deterministic release event id; already on 17's acceptance list), **50** (responder shutdown isolation; Orders' responder already solved it in Phase 8, so port that, don't re-derive it), **51**, **54**, **79**, **95**, **101**. Read each before writing a task.
- **Already carried on feature 17:** the per-service `otc_cqrs` registration item from feature 43, with the behavioural registration guard; read its last acceptance item.
- **What Phase 8 built that Phase 9 reuses** (read it, don't re-derive it):
  - Orders' `composition.py` / `main.py` / readiness / boot-cleanup pattern (feature 15, rounds 1–3).
  - The settings→adapter reach test. #8 id 56 **recurred three times** in Phase 8 (15 D-2, 15 R2-D5, 16 D1), so write it with the composition root, not after review.
  - The canonical `idempotent_consumer.py`: its parity guard's case 1 goes live when Fulfillment carries a copy, and case 3 when Fulfillment consumes Kafka.
  - Feature 15's stand-in stock-check responder and its `success | RpcError` contract. Fulfillment must answer with codes from the closed `RpcError` enum; feature 42 classifies nine of them as terminal, so a code chosen wrongly here parks or rejects Orders' commands.
- **Lessons from Phase 8 to put in every brief:**
  - Ask "what fails if I revert this?" of every fix. Feature 15's second rejection was four repairs that survived their own reversion, exactly #8's round-2 note for the same feature.
  - Before review, list every branch of a hand-built loop or adapter (cancel, pace, retry, send-raises, ack-fails) and name the test that drives each.
  - Every multi-claim test needs one mutation per claim.
  - Negative assertions need a control row.
  - Arming backups go in `.arm/` with a recorded `sha256`, never `/tmp`, and timeouts kill the whole process group (CLAUDE.md, amended at this wrap-up).
- **`quality.sh` threshold:** the maintainer set ~125 s at the Phase 7 gate. The Phase 8 wrap-up figure is in `progress/history.md` (feature 16's addendum). The saga's container-backed integration suite dominates it, with Kafka's consumer-group join as the measured cost, so revisiting the threshold is the maintainer's call.
- **Plan items to honour** (Plan Phase 9): `StockItem` reservation lifecycle with `reserved_units ≤ units`; the `stock.check/reserve/release/list/replenish` responders; `SELECT … FOR UPDATE` in an application-fixed order on every deciding read; deadlock retry on `40P01` with a concurrency test; a deterministic event id for releases (#8 id 49); `SA-4`'s arbitration of `stock.release` against `despatch.create` under one lock; `DespatchAdvice` consuming reservations; one commit per feature.

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
