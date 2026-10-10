# Premise check — brief_spec_billing_invoicing.md

FALSE       "#8 gate record `progress/spec_billing_invoicing.md` (20 open points)" (brief line 12) — `grep -n 'open point' ../order-to-cash-dotnet/progress/spec_billing_invoicing.md`: line 9 "27 open points, **1 GATE**", line 47 "**27 open points; 1 GATE — row 1.**". It is 27, not 20 (the #7 record says "27 open points" in no line; #7's was not asked).
VERIFIED    test-matrix §6 at line 162 `billing_invoicing — R45 – R49`; R45–R49 rows 166–170, R47–R49 are payment intake — `sed -n 162p`, `grep -n 'R4[5-9]'`
VERIFIED    saga.md line 49 `invoice.issue | Orchestrator | Billing | (orderReference, issue) | invoiceReference`; rows 4–5 at lines 70–71 — `sed -n '49p;70,71p'`
VERIFIED    asyncapi `invoiceIssue` channel 481–490, `invoiceList` 502–513 (482–513 range ok); `requestInvoiceIssue` operation title at 1091 — `grep -n invoice asyncapi.yaml`
VERIFIED    models.py columns: invoices (amount, discount, total_amount, status, paid_at, unique order_reference, unique invoice_reference), invoice_items (product_code, units, price), invoice_number_sequences, payments — `sed -n 85,140p`; the only `discount` hit is models.py:100 (invoices), so no per-line discount column. Range nit: classes span 90–138, brief says 91–137
VERIFIED    billing_credit design.md line 28 (feature 21 owns `billing.invoice.issue`, Invoice, INV-, `consume` caller), line 414 (Billing consumes no fact), line 541 (§17.1 population), §15.2 at 517, §8.5 at 359, §17 at 537 — `sed -n` / `grep -n '^###'`
VERIFIED    `review_billing_credit.md:39` is the R40 row ("domain only; caller is feature 21 — deviation 13 accepted") — `sed -n 39p`
VERIFIED    `spec_billing_credit.md` "Gate ruling" at line 73; G1 zero hold adopted, BC38 stands (line 75) — `grep -n`
VERIFIED    conftest `CENTS_RULE_SUFFIX = 99` (services/billing/tests/integration/conftest.py:382); `allow_cents_rule` refuses hold amounts ending in 99 — `grep -n`
VERIFIED    `nats_saga_commands.py:65-75` is `TERMINAL_RPC_ERROR_CODES` (nine codes) — `sed -n 60,80p`
VERIFIED    `tests/architecture/test_billing_rpc_error_retryability.py` exists — `ls`
VERIFIED    #8 spec line counts 178 / 788 / 104 (requirements/design/tasks) and #7 123 / 540 / 93 — `wc -l`
VERIFIED    #8 and #7 `progress/spec_billing_invoicing.md` and `progress/review_billing_invoicing.md` exist; #7 `apps/billing/src/`, #8 `src/Billing/` exist — `ls`
VERIFIED    #8 history 1305 = billing_invoicing entry "REJECTED on round 1" (line 1307: "REJECTED, 3 blocking", review line 3 "3 blocking defects"); "first live sighting of a terminal saga rejection" is in the 1305 heading; 1410 = "Phase 10 closing assessment" — `sed -n '1305p;1410p'`
VERIFIED    #7 history 922 = "billing_invoicing (id 21, phase 10) — 2026-08-23" — `sed -n 922p`
VERIFIED    the "273 tests green" lesson: not a literal string anywhere; it is #8 review_billing_invoicing.md D2 (~line 165): zeroing `request.Discount` left unit **199/199** and integration **74** passed, 199+74 = 273; root cause line 167, no integration test sends a non-zero discount
VERIFIED    ORD-000008 `despatched` with `invoice.issue` parked, K5 register — impl_billing_credit.md:401, 441, 542
VERIFIED    `despatch_number_allocator.py`, `progress/impl_fulfillment_despatch.md`, Billing `sequences.py`, backlog id 211 (counter seeded from numeric MAX) exist — `ls`, `find`, feature_list.json:819
UNVERIFIABLE live state of ORD-000008 in the dev DB now — stack stopped, not started

Counts: VERIFIED 18, FALSE 1, UNVERIFIABLE 1
Verdict: DO NOT ACT as written (1 FALSE; minor: #8 gate record has 27 open points, not 20).
