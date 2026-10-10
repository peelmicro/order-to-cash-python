# `billing_invoicing` (id 21, phase 10) — spec pass (assessment #9, Python)

**Author:** `spec_author` · **Date:** 2026-10-09 · **Brief:** `progress/brief_spec_billing_invoicing.md` (premise check `progress/premise_billing_invoicing_spec.md`)
**Deliverables:** `specs/billing_invoicing/{requirements,design,tasks}.md` (208 / 557 / 131 lines). `feature_list.json` not edited; the leader sets 21 to `spec_ready`. `specs/shared/` not edited by this pass (its one pending modification, `test-matrix.md`, is features 19 – 20's). **No `SA-6` proposed.**

**Normative range:** `R45`, `R46` (flipped by this feature; `R46` delivered through `Invoice.mark_paid`, uncalled until feature 22). `R47` – `R49` stay `TODO` for feature 22 — the matrix group is broader than the feature, and `requirements.md` §1 says so first (#8 history line 1364). `R40` gets its first live caller; its row is already `DONE` and is not re-flipped.
**Local ids:** #8's `BI1` – `BI16`, `BI21` – `BI27`, `BI29`, `BI31` reused (numbering unchanged; a *#9 note* where the mechanism differs); `BI17`, `BI18`, `BI19`, `BI20`, `BI28`, `BI30` not claimed, one reason each (`requirements.md` §2.3); **`BI32` – `BI38` new in #9**, `BI37` pending G1.
**Ported-idiom ledger:** `design.md` §3 — **40 enumerated boundaries, 41 rows**, the enumeration written before the rows; each row's #7 and #8 halves cited with file and line.
**#8 backlog:** feature 19's §17.1 population (37 entries) assigned none to 21; re-checked for entries touching invoicing (two searches, below): 16 rows in `design.md` §17.1, 9 bearing on 21 (8 avoided with a named guard, 1 seam-only — id 57, the caller half being 22's).
**Tasks:** 65, of which **54 carry `[ARM]`**; the 11 unflagged ones are code-writing boxes that point at the task arming them, the baseline, the live pre-read, the register and the report.

## Evidence produced by command in this session

| # | Command (abridged) | Result |
|---|---|---|
| M1 | `docker run --rm postgres:18.6`; through SQLAlchemy + asyncpg (`uv run --no-sync python -I <scratchpad>/probe/p1.py <url>`): `select(…).offset(n)` for `2**62`, `2**63-1`, `2**63`, `2**64` | `[]`, `[]`, `DBAPIError … invalid input for query argument $2: 9223372036854775808 (value out of int64 range)` SQLSTATE `22000`, the same for `2**64` |
| M2 | Same: a `timestamptz(3)` column read under `SET TIME ZONE 'Europe/Madrid'` (one `NULL`, one `…10:00:00.123+00`) | `None`; `datetime(2026, 10, 9, 10, 0, 0, 123000, tzinfo=datetime.timezone.utc)`, `utcoffset() == 0:00:00` |
| M3 | Same: `SELECT 'paid' = 'Paid'`; `type(select(func.count()) …)`; `paid_at <= :cutoff` with the cutoff equal to the stored instant | `false`; `int`; the row is counted (inclusive) |
| M4 | `python3 -I -c "… datetime(2026,10,9,10,tzinfo=UTC) - timedelta(minutes=m) …"` for `10**9`, `1_065_000_000`, `2*10**9`, `10**12`, `2**63` | `0125-06-12…`, `0001-11-11…`, `OverflowError date value out of range` (twice), `OverflowError Python int too large to convert to C int` |
| M5 | `grep -rn "\.offset(" services/*/src` | two: `billing/…/credit_reads.py:46`, `fulfillment/…/stock_reads.py:79` |
| M6 | `grep -rn "AIOKafkaConsumer\|aiokafka" services/billing/src` | only `outbox/kafka_publisher.py:16` (a producer) and a docstring in `settings.py:88` |
| M7 | `python3 -c "…../order-to-cash-dotnet/feature_list.json, id > 38, text ~ invoice\|allocator\|paid_at\|paidat\|discount\|47…"`; and `… ~ billing_invoicing\|feature 21\|invoice\.issue\|InvoiceIssue\|Invoice\b\|INV-\|invoice_number\|BI[0-9]` | `41, 45, 47, 57, 65, 72, 75, 78, 84, 85, 102, 108, 110`; `78, 110` |
| M8 | `sed -n 40,100p services/orders/tests/unit/saga/test_command_payloads.py`; `cat services/orders/src/otc_orders/application/saga/command_payloads.py` | Orders sends `discount=order.initial_discount.amount`; its test asserts `(8465, 350, 8115)`, the hold `8115`, the invoice lines and discount `350` from one fixture order — `BI21` already bites |
| M9 | `cat packages/contracts/src/otc_contracts/generated/nullable.py`; `wire.py` docstring | `"asyncapi.InvoiceView": frozenset({"paidAt"})`; *"a `None` is written as an explicit `null` only for a field that the spec declares nullable"* |
| M10 | `grep -n "ROUTES\|DESPATCH_CREATE_SUBJECT" services/fulfillment/src/otc_fulfillment/presentation/stock_responder.py` | `despatch.create` is an entry of `StockResponder`'s table (`:121-128`), no rename |
| M11 | `git ls-files` on four feature-19 Billing files | 0 tracked: features 19 – 20 are uncommitted, so `git diff` cannot evidence C1's "no assertion changed" (backups + `diff` instead) |
| M12 | `grep -rnE "\bupdate\(\|\bdelete\(\|on_conflict"`, `"\btext\("`, `"func.sum\|isoformat()\|json.dumps"` over `services/billing/src/otc_billing` | the exact expected sets written into task D7 (docstrings classified); without `\b`, `text(` also matches `CreditContext(` |

The probe container was stopped (`--rm`); `docker ps` afterwards showed only `otcpy-n8n`. The developer stack was not started.

## Decided — #7 and #8 agree and Python forces no difference (adopted, cited)

| Decision | #7 | #8 | Where |
|---|---|---|---|
| One transaction, two aggregates (`Invoice` + `BuyerCredit`), the deviation from `domain-model.md` §8 rule 6 re-derived against #9's code | gate row 1; `invoice-issue.handler.ts:138-139` | gate row 2; `InvoiceIssueService.cs:95-96` | `design.md` §6.5 (cheaper here: an explicit `tx` again, and feature 18's precedent) |
| Fast path outside any transaction; line lock first; allocator last | handler `:74, 82, 111` | service `:37, 47, 72` | §6.1 – §6.2 |
| `NOT_FOUND` no line, `VALIDATION_FAILED` currency, `PRECONDITION_FAILED` no active hold, `DOMAIN_ERROR` otherwise | `rpc-error-mapper.ts:78, 89, 98` | `BillingErrorMapper.cs:39-157` | §8.4 |
| Edge checks before dispatch: `unitPrice ≥ 0`, `discount ≥ 0`, `discount ≤ Σ` | `invoice.dto.ts:39-41, 58-82, 112-115` (after its `N2`) | `InvoiceRequestValidator.cs:61-80` | `BI2` |
| Billing consumes no fact; no idempotent-consumer case goes live | `billing-consumes-no-facts.spec.ts` | `BillingConsumesNoFactsTests` | §10.3 |
| `mark_paid` delivered uncalled, its fact guarded with double force | `invoice.ts:284` | `BI14` | `BI14` |
| List: inclusive cutoff, `invoice_date DESC, invoice_reference DESC`, clock passed in | `invoice-read.repository.ts:37-48` | `EfCoreInvoiceReadRepository.cs:43-55` | `BI15` |
| The `consume` entry, the invoice date and the fact share one clock read | handler `:113` | service `:77` | §6.2, C3 |
| Repeat against a `paid` invoice: `created: false`, `status: paid` | — | gate row 23 | `BI9` |

**Decided by #9's own approved precedent:** extend the responder's route table without a rename (feature 18's `StockResponder` + `despatch.create`, where #7 forked a controller and #8 renamed four types — they disagree on mechanism, and #9 has its own answer); `paidAt: null` for an issued view (#9's ratified wire rule, feature 8, landing on #7's bytes; #8 omitted under its own ratified rule — its gate row 4 is the reasoning that a ratified rule is not re-gated); a zero-total invoice is issued (feature 19's G1 ruling; #7 and #8 refuse `activeHold <= 0`); exact, case-sensitive matching (feature 17's G2); `orderReference ≤ 20` at the edge (feature 19's `BC33`, Fulfillment's FS28); a plain in-transaction re-read after the line lock (feature 19's measured run A, Fulfillment's F8); canonical line order on a reload (Fulfillment's `line_order_key`).

**Where #7 and #8 disagree and the spec decides by the text both wrote:** `invoiceId` on every issue reply — #7 sends it (`invoice-issue.handler.ts:19-41`); #8's `BI9` text names it but its `BuildReply` never passed it. Sent (`BI9` note).

**Forced by Python, decided without the gate because the answer is the predecessors' property:** `InvoiceState` as a `type` alias over two `@final` dataclasses with `assert_never` and a runtime instant check (L41 — #7's union, #8's closed hierarchy); `InvoiceTotalOverflowError` with its own code although Python `int` cannot wrap (#8's `BI25`, feature 19's `BC30`); `units ≤ 2³¹ − 1` and `Σ ≤ 2⁶³ − 1` refused at the edge so nothing is refused after the counter lock (#7's `N2` lesson, L5 / L6); `consume` called before the allocator (G1 of feature 19 makes it the check).

## Answers to the brief's questions

- *Is "issued on order.despatched" a Billing subscription?* No, in #7, #8 or #9 (M6): it is the orchestrator's `invoice.issue` command on that fact (Orders' `step_table.py:166`, `command_payloads.py:65-78`). **No idempotent-consumer parity case goes live in 21**; they go live at feature 23.
- *Where do the lines and the gross come from?* From the `invoice.issue` request — `lines[]` with `productCode`, `units`, `unitPrice`, and an optional order-level `discount` (`asyncapi.yaml:3577-3601`); no per-line discount exists on the wire or in `invoice_items`. #7 and #8 derive `amount = Σ(unitPrice × units)` and `total = amount − (discount ?? 0)` from it; so does #9. Orders sends `order.initial_discount` (the sum of its line discounts), so the invoice total equals the hold (M8).
- *Every column 21 needs?* Present (`design.md` §1): no migration. `invoice_items.price` is the unit price; there is no position column (line order on a reload is canonical, L15).
- *The saga's view:* tabulated in `design.md` §8.4; `tests/architecture/test_billing_rpc_error_retryability.py` is extended, and **its walk is widened** because it names two modules and would not see `domain/invoice_errors.py` — an instrument change whose three new premises are armed (E6).
- *The live stack:* `ORD-000008` (`despatched`, `invoice.issue` `parked`, hold 99 996 on `CR-000001`) is the only order the walkthrough names besides a fresh control order with a **non-zero discount**; K5's register was read first (`progress/impl_billing_credit.md:535-544`). Expected: `ORD-000008` → `invoiced`, `CR-000001`'s 344 459 unchanged, then the designed stop.

## Open for the gate — one point

**G1 — out-of-range list requests: a page past `2⁶³ − 1` and an `issuedBeforeMinutes` before year 1** (`BI37`; `design.md` §16.1). *Forced by Python and asyncpg; #7 (JavaScript numbers, `invoice-read.repository.ts:50`) and #8 (unchecked `int`, `EfCoreInvoiceReadRepository.cs:55`) never decided it.* Both requests are schema-valid (no maximum on `PageRequest.page` or `issuedBeforeMinutes`). Today an offset ≥ 2⁶³ raises `DBAPIError` SQLSTATE `22000` (M1), answered `INTERNAL_ERROR` — a retryable code and an ERROR traceback for a client's mistake — and the same gap already exists in `billing.credit.list` and `fulfillment.stock.list` (M5, exactly two sites). A cutoff before year 1 raises `OverflowError` (M4).

**Recommendation: answer a page past the end, not an error** — clamp the offset to `2⁶³ − 1` (PostgreSQL then returns no rows, M1) and treat an unrepresentable cutoff as "no invoice qualifies" — returning success with no items and the true `page.total`, **on all three list subjects in this feature**: one line per reader plus one armed case each (tasks G4, G6). The finding is detected now and costs one line per site, so it is fixed now (CLAUDE.md, findings are fixed in the phase that detects them), including the one line in Fulfillment's `stock_reads.py`.

*If overruled:* refuse both at the edge as `VALIDATION_FAILED` (one check in each of the three decoders); `BI37`'s outcome changes accordingly and tasks E3, G4, G6 assert the refusal. Either way the three sites change together.

## Notes for the leader (not gate points)

1. **A stale clause in feature 19's spec.** `specs/billing_credit/design.md` §8.1 says *"here the class is named for the service from the start"*; the class is `CreditResponder` (its own §2, line 98, and the code). Recommendation: correct the clause to *"credit-named; features 21 and 22 add their subjects as route entries (feature 18's precedent)"* — a docs edit within the leader's bounds. Feature 21 does not rename (`design.md` §16.2).
2. **A stale docstring this feature makes false.** `credit_repository.py:19` says no textual DML exists in the service; the counter allocator introduces three `text()` calls. Task D1 rewords the sentence (comment only) and the file is on the touch list.
3. **Sequencing.** Task F1 edits `services/billing/tests/integration/conftest.py`, which another agent is editing (one docstring) as this spec is written; F1 says to start only after that edit is merged.
4. **Commit split.** Features 19 – 20 are uncommitted (M11) and 21 extends their files (`credit_responder.py`, `credit_rpc_errors.py`, `credit_transactions.py`, `credit_reads.py`, the conftest, three test files' keyword argument, `test_credit_subjects.py`, the retryability guard). Per the Phase 9 ruling, split by file and say so in the earlier commit's body.
5. **Effort baselines** for the history entry: #8 ≈3 h 16 min first artefact → verdict, rejected once (history line 1305); #7 ≈1 h 51 min, rejected once (#7 history line 922).

## Hand-over recorded for later features (`design.md` §15)

1. **Feature 22** — `mark_paid` returns its fact (#8 id 57's seam); the lock order *unlocked invoice read → line lock → plain re-read → update*; the first two-row outbox transaction; the payment errors' subject codes are 22's to map.
2. **Features 24, 25, 33** — `invoice.issued.v1` carries the full lines; an issued `InvoiceView` carries `"paidAt":null`; an out-of-range page answers empty (G1).

## Gate ruling (maintainer, 2026-10-09)

**Approved.** G1 adopted as recommended: an out-of-range list request (a page past `2⁶³ − 1`, an `issuedBeforeMinutes` cutoff before year 1) answers success with no items and the true `page.total`, on all three list subjects (`billing.invoice.list`, `billing.credit.list`, `fulfillment.stock.list`) in this feature; `BI37` stands. The leader checked the evidence before the gate: `asyncapi.yaml` `PageRequest.page` has `minimum: 1` and no maximum; #7 `invoice-read.repository.ts` and #8 `EfCoreInvoiceReadRepository.cs` compute `(page - 1) * pageSize` unguarded; #9's existing sites are exactly `credit_reads.py:46` and `stock_reads.py:79` (`grep -rn "offset(" services/*/src`).
