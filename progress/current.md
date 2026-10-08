# Current session

**Feature:** none active — next `billing_credit` (id 19, phase 10)
**Status:** Phase 9 closed and committed at the full wrap-up (2026-10-08); Phase 10 not started
**Session started:** —

## Goal

## Decisions taken this session

## Blockers

## Notes

**Resume point:** Phase 9 is done. Features 17 and 18 are committed, with 17's spec commit before its implementation commit (`git log`). Phase 10 starts in a **fresh session** (CLAUDE.md, one session per phase) from this file. The `otcpy` developer stack is **stopped** except `otcpy-n8n`; restart it with `docker compose -p otcpy -f docker-compose.infra.yml start` when a live check needs it.

**Live dev data, read before any live walkthrough:**
- **`ORD-000008`** is `stock_reserved`, with its `credit.hold` saga command **parked** (*no responder is subscribed to billing.credit.hold*). When feature 19's `billing.credit.hold` responder first runs against the live stack, the sweeper should issue that row and the saga should advance. Record what happens; it is the second live proof of park-and-resume, after `stock.reserve` in Phase 9.
- **`ORD-000007` will stall at `confirmed`. Do not use it for an end-to-end walkthrough.** Phase 9's live check despatched it in Fulfillment (`DES-000006`, reservations `consumed`) while Orders held it at `stock_reserved`, so Orders skipped that `order.despatched.v1`. Under F8, a later saga `despatch.create` answers `created: false` with no fact, and Orders advances only on the fact (`step_table.py:162-167`; confirmed in `progress/review_fulfillment_despatch.md`). Its `credit.hold` is parked too. Either leave it parked, or recreate the dev databases from the seed before a walkthrough that needs a clean cycle.

**Brief for phase 10 — Billing service (Plan step 15).** Four features, in `feature_list.json` order: **19 `billing_credit` (sdd)**, 20 `billing_credit_simulator` (sdd false), **21 `billing_invoicing` (sdd)** and 22 `billing_remittance_intake` (sdd false).

- **First action:** feature 19 is `pending` + `sdd: true`, so one `spec_author` writes `specs/billing_credit/` and then **stop at the human gate**. Brief it with the Phase 8 rule: a decision #7 and #8 agree on, with no Python-forced difference, is adopted and cited, never offered as a gate option. Go to the gate with a recommendation and evidence, checked by command.
- **Process:** full group for 19, 21 and 22 (money domain, persistence, the saga's responders). For 20, the leader classifies light or full by its acceptance items and records why. Premise-check every brief; Opus reviewer for the full group; at most one rejection round without asking; findings fixed in the phase that detects them.
- **Baselines:**
  - #8 `../order-to-cash-dotnet/progress/history.md`: 19 :1215, 20 :1261, 21 :1305, 22 :1376, Phase 10 closing assessment :1410.
  - #7 `../order-to-cash-nestjs/progress/history.md`: :882, :903, :922, :943.
  - Specs: #7 `../order-to-cash-nestjs/specs/billing_{credit,invoicing}/`, #8 `../order-to-cash-dotnet/specs/billing_{credit,invoicing}/`.
  - #8 backlog entries a keyword search of its `feature_list.json` (billing, credit, invoice, remittance, payment) returned: ids **57, 71, 76, 79, 83, 92, 100, 102**. That is a sample, not the population. Enumerate the Billing-area findings by reading #8's Phase 10 entries, and map each as avoided or assigned.
- **What Phases 8 and 9 built that Phase 10 reuses** (read it, don't re-derive it):
  - Orders' and Fulfillment's `composition.py`, `main.py`, readiness, boot cleanup and the NATS responder: one task class, per-request scope, a concurrency bound sized to the pool, shutdown isolation (#8 id 50).
  - The settings→adapter reach test. Write it with the composition root: #8 id 56 recurred three times in Phase 8.
  - Fulfillment's outbox copies and `tests/architecture/test_outbox_copy_parity.py`. Billing's copy must join that guard. Read how the guard enumerates copies before assuming it finds a new one.
  - The canonical `idempotent_consumer.py` and its parity guard. Ask whether Billing consumes Kafka in #7 and #8; if it does, case 3 goes live.
  - The `RpcError` closed enum and Orders' `TERMINAL_RPC_ERROR_CODES`: every code Billing answers is a saga decision (retry versus reject). Tabulate them as feature 17 did (`specs/fulfillment_stock/design.md` §8.5).
  - The `DES-` allocator and its ported guards (`progress/impl_fulfillment_despatch.md`), for `INV-`.
  - The SA-4 arbitration: Billing's `credit.release` ordering against despatch, in #8 id 79's terms.
- **Lessons from Phase 9 to put in every brief:**
  - Feature 17's rejection was **three mutations that survived the whole suite**: a lock method's read order, the id port at the application→domain seam, and one refusal branch. Planned arms do not find these. The implementer should mutate the call sites of every hand-built seam, not only the seam itself.
  - A property guarded at the domain can still be unguarded one layer up (#8 id 49's follow-on, recurred in 17 round 1). Count the call sites.
  - A guard's failure must name its claim (feature 18's N1/N2): no unpack-before-assert, no bare `TimeoutError`.
  - Construct races with a held lock (`wait_for_lock_waiters`), never by repetition.
  - Ruff formats Python blocks inside Markdown: a progress record that quotes code must quote it formatted.
- **`quality.sh` reference:** ~360 s with the stack stopped (maintainer ruling, Phase 9 gate; 320 s measured at the wrap-up).
- **Commit split:** if a later feature of the phase extends an earlier one's files before either is committed, split by file and say so in the earlier commit's body (maintainer ruling, Phase 9 gate).
- **Accepted, with a re-open trigger:** feature 18's N3, `OrderDespatched` extends `StockEventBase` (a misnomer). Re-open on the next change to `otc_fulfillment.domain.events`.
- **Plan items to honour** (Plan Phase 10, read from the Plan by the leader at the Phase 9 wrap-up):
  - `billing_credit`: `BuyerCredit` and the append-only hold, release and consume ledger; a per-service Kafka `client_id` that cannot be empty (#8: an empty one silently defaults).
  - `billing_credit_simulator`: `.99` is evaluated **before** the `CREDIT_FAILURE_RATE` draw (an ordering claim, guarded), with seedable randomness.
  - `billing_invoicing`: `Invoice` `issued → paid` and `billing.invoice.issue`; fixtures with a **non-zero discount** and a gross derived from the lines (#8: setting the discount to `0` left 273 tests green).
  - `billing_remittance_intake`: idempotent by `payment_reference`; `credit.released.v1` caused by `payment.received.v1`; the cycle closes end to end **without touching `services/orders`**, proved by enumeration.
  - One commit per feature.

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
