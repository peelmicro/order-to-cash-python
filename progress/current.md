# Current session

**Feature:** none active — next `notifications_service` (id 23, phase 11)
**Status:** Phase 10 closed and committed at the full wrap-up (2026-10-10); Phase 11 not started
**Session started:** —

## Goal

## Decisions taken this session

## Blockers

## Notes

**Resume point:** Phase 10 is done: features 19 – 22 are committed, 19's and 21's spec commits before their implementation commits (`git log`). Phase 11 starts in a **fresh session** (CLAUDE.md, one session per phase) from this file. The `otcpy` developer stack is **stopped** except `otcpy-n8n`; restart it with `docker compose -p otcpy -f docker-compose.infra.yml start` when a live check needs it (Mailpit is in that file, `docker-compose.infra.yml:291-295`).

**Live dev data, read before any live walkthrough:** the registers of altered live fixtures are in `progress/impl_billing_credit.md` §8 (K5), `progress/impl_billing_invoicing.md` (K section) and `progress/impl_billing_remittance_intake.md` §9 (K5). `ORD-000008` and `ORD-000010` are `completed`; `ORD-000009` is `cancelled` (`credit_rejected`); `ORD-000007` is stalled at `confirmed` (Phase 9's out-of-band despatch; do not use it); throwaway `ORD-000090` exists only in Billing's ledger (a hold and a release). No `issued` invoice is left. Phase 11's walkthrough should place fresh orders and read the Mailpit inbox through its HTTP API.

**Brief for phase 11 — Notifications service (Plan step 16).** One feature: **23 `notifications_service`** (`sdd: false`, six acceptance items in `feature_list.json`; the fifth is carried from feature 43 `cqrs_dispatcher` — read it in full).

- **Classification:** the leader decides light or full by the acceptance items and records why. It consumes Kafka facts and holds the durable idempotency ledger, so full group is the expectation (Opus reviewer).
- **Process:** `sdd: false` → one implementer from the acceptance items; premise-check every brief; at most one rejection round without asking; findings fixed in the phase that detects them; write the impl record early and keep it updated (Phase 10: an implementer stopped by a session end lost its unwritten record).
- **Baselines:** #8 `../order-to-cash-dotnet/progress/history.md` line 1486 (23: "the first feature rejected on defects #7's standard could not have seen"), line 1602 (backlog ids 58 + 59, `notifications_mutation_gaps`: the notified-fact filter and the date-typed payload sites), line 1410 (the Phase 10 closing assessment); #7 `../order-to-cash-nestjs/progress/history.md` line 964. #8 backlog ids named on 23's acceptance: **58, 59, 73**; enumerate the population (every #8 entry whose subject is a Notifications mechanism), not this sample.
- **Plan items to honour** (Plan Phase 11): consume the seven notified facts; aiosmtplib → Mailpit and a console adapter for tests behind one port; the durable `processed_events` ledger; degrade on permanent failure; guards on **the filter itself** (deleting an entry from the notified-fact set must fail a test — #8's guards ran past the filter and never crossed it) and on **every template's recipient and fields** (#8: 45 of 68 template mutations survived); emails verified **in the Mailpit inbox through its HTTP API**, and a byte-identical redelivery of all seven leaving inbox and ledger unchanged.
- **What #9 already has (read it, don't re-derive it):** Notifications' persistence only (`services/notifications/src/otc_notifications/infrastructure/{persistence/models.py,settings.py}`, `presentation/app.py`, the `processed_events` migration); no `composition.py` / `main.py`. Billing's host (`services/billing/src/otc_billing/{composition,main}.py`) is the newest template. **This is the first service besides Orders to consume Kafka**: the canonical `services/orders/src/otc_orders/infrastructure/messaging/idempotent_consumer.py` and its parity guard `services/orders/tests/unit/test_idempotent_consumer_parity.py` (it discovers services by glob, so case 3 — every consumer carries a copy — goes live here; read how before assuming). Orders' Kafka subscriber `kafka_fact_subscriber.py` (group id and client id literals) and `tests/architecture/test_kafka_client_ids.py` (feature 19's `BC34`: a non-empty client-id pattern in every producer; ask whether consumers need the same). The settings→adapter reach tests (`tests/architecture/test_composition_env_reads.py`; #8 id 56 recurred three times in Phase 8).
- **Lessons from Phase 10 to put in every brief:**
  - **A fixture must not satisfy the relation by accident** (`billing_credit` round-1 D1: every release fixture released the line's only exposure, so available-after equalled the limit and a corrupted field survived 851 tests). State the plausible wrong values and show each expected value differs from them.
  - **Changing an instrument swaps its premises** (`billing_credit` D2, D3, R2-1: the parity guard ignored the region before a docstring, then the canonical's own region; the outbox census recognised one spelling). List the new instrument's premises and arm them.
  - **A guard's failure must name its claim and arrive fast** (`billing_credit_simulator` N1: a clamp mutation failed only after 131 s of NATS retries).
  - **A brief can plant a departure.** `billing_remittance_intake`'s specific `RpcError` codes came from wording in the leader's brief; the premise check caught the wrong citation but not the prescriptive phrasing. Phrase anything #7 and #8 decided as a question with their citations, never as a list of values.
  - **A docstring or ledger claim is a countable claim** (`billing_remittance_intake` N2: the per-row flush was credited with an ordering that call order supplies; removing it changed nothing). Probe the mechanism a ledger row names.
- **`quality.sh` reference:** ~360 s (maintainer, Phase 9 gate); **391.55 s measured at the Phase 10 wrap-up** with 3 492 tests — above the reference, for the maintainer to re-baseline or not.
- **Carried into later features this phase (read them when those features open):** backlog **213** on feature 41 (`saga.md` §2 has no `credit.release` row — an SA-n at that gate); feature **25** gained two acceptance items (the payment's `x-correlation-id` must be the order id; the payment `RpcError` → HTTP mapping of `openapi.yaml:673-675`, not #8's classifier verbatim); feature **22**'s three departures from #7/#8 were kept by its reviewer on `specs/shared/` text — the specific `INVOICE_NOT_PAYABLE` / `PAYMENT_MISMATCH` codes are the weakest of them (`progress/review_billing_remittance_intake.md` §2), which the maintainer may still overrule.
- **Accepted, with a re-open trigger:** feature 18's N3 (`OrderDespatched` extends `StockEventBase`; re-open on the next change to `otc_fulfillment.domain.events`); feature 20's O1 (`1.0000000000000001` parses as `1.0` in all three builds; re-open if a build adopts a decimal-exact parse); feature 19's N3 (the unknown-ledger-type message reads as a sentence).
- **Commit:** one, `notifications_service`.

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
