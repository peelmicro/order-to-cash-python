# Premise check — brief_impl_billing_remittance_intake.md

FALSE       "Feature 22 is `in_progress`" (brief line 3) — python json over feature_list.json: id 22 `billing_remittance_intake` status reads `pending` (the working tree and HEAD agree). Expected per the dispatch note (the leader sets it at dispatch); reported as read.
VERIFIED    feature 22 has five acceptance items, the fifth the BI8 lock-order binding — json: 5 items; item 5 "lock order credits row -> invoices row (feature 21 BI8 binding, ... design.md §15.1: resolve the invoice unlocked, lock the credits row, re-read the invoice"
VERIFIED    R47–R49 from requirements.md line 414 — `grep -n '^\*\*R47'` -> 414; R47/R48/R49 text matches the brief's use
VERIFIED    billing_invoicing design.md §15.1 content — line 476 heading; line 478: mark_paid "ships tested and uncalled", returns PaymentReceived, UPDATE of status/paid_at/updated_at, `release`'s None must not be discarded; `grep -rn 'mark_paid' services/billing/src` shows only the def (invoice.py:351) and docstrings, no caller
VERIFIED    billing_credit design.md §15.3 — heading at line 521; release None at line 220; L20 (line 143) "one flush() per row"; writer.py:65 `await session.flush()`
VERIFIED    "feature 19 L20" and "features 19 and 21" — feature_list: 19 billing_credit, 21 billing_invoicing (both done), 20 billing_credit_simulator
VERIFIED    asyncapi anchors 524, 1136, 1847 — 524 `address: billing.payment.register`; 1136 `title: billing.payment.register` inside operation `requestPaymentRegister` (line 1134); 1847 `title: billing.payment.register — request`
VERIFIED    saga.md lines 50, 72, 363 — 50 the `payment.register` row (Gateway, Billing, `paymentReference`, accepted/duplicate/rejected); 72 row 6 `payment.received.v1` (paid, same-transaction release); 363 "repeated `payment.register` with the same `paymentReference` returns the original"
VERIFIED    openapi.yaml 643–675 — 643 `/invoices/{id}/payments`; "only way an invoice becomes paid"; line 675 PAYMENT_MISMATCH 422; `grep -n` finds PAYMENT_MISMATCH (675, 1912)
FALSE       "the payment error codes `INVOICE_NOT_PAYABLE`, `PAYMENT_MISMATCH`" in openapi.yaml 643–675 — `grep -n 'INVOICE_NOT_PAYABLE\|PAYMENT_MISMATCH' specs/shared/openapi.yaml` matches only PAYMENT_MISMATCH (675, 1912); INVOICE_NOT_PAYABLE does not occur in openapi.yaml; the table's other codes are PAYMENT_REFERENCE_REUSED and INVOICE_ALREADY_PAID. (Design §15.1 line 478 repeats the same pairing.)
VERIFIED    every #7/#8 file named exists — `ls` printed #8 PaymentRegisterService.cs, PaymentRegisterServiceTests.cs, PaymentRegisterTests.cs, review_billing_remittance_intake.md; #7 payment-register.integration.spec.ts, review_billing_remittance_intake.md
VERIFIED    #8 history 1376 "approved first pass, 0 blocking", "closes the order-to-cash cycle end to end for the first time" — heading at 1376; line 1378 "APPROVED first time, 0 blocking defects"
VERIFIED    #8 backlog id 57 `completion_pair_has_no_causal_edge`, causationId = payment.received eventId — json over ../order-to-cash-dotnet/feature_list.json: name matches; acceptance 1 states it
VERIFIED    #7 history 943 — heading "## billing_remittance_intake (id 22, phase 10) — 2026-08-24"
VERIFIED    services/gateway has no billing RPC client — `find services/gateway -type f`: pyproject, health test, app.py and empty layer __init__ files only; grep -il billing over *.py: no hits
VERIFIED    an API-tests feature exists — feature_list id 31 `api_tests` (pending)
VERIFIED    n8n/workflows holds four files including 2-payment-robot.json — ls: 1-order-generator.json, 2-payment-robot.json, 3-stock-replenishment.json, 4-burst.json
VERIFIED    impl_billing_credit.md § Live boot exists — line 325 "## 8. Live boot (BC20; tasks K1 - K5)"; impl_billing_invoicing.md K section — lines 733–1034 K1–K5, K5 is the register of altered fixtures
VERIFIED    ORD-000008 and ORD-000010 recorded invoiced — impl_billing_invoicing.md K5 table (lines ~1041–1043) "ORD-000008 | invoiced", "ORD-000010 | invoiced"
VERIFIED    git status of services/orders shows only feature 19's two settings files — `git status --porcelain services/orders`: `M .../infrastructure/settings.py`, `M .../tests/unit/test_orders_settings_env.py`
UNVERIFIABLE "the first `update` in Billing" and "n8n payment robot is not an internal timer" — classification claims for the implementer's own search; not settled by one command here
UNVERIFIABLE live-fixture state of the DBs — stack not started per instructions

Counts: VERIFIED 18, FALSE 2, UNVERIFIABLE 2
Verdict: DO NOT ACT as written (2 FALSE: status reads `pending`; `INVOICE_NOT_PAYABLE` absent from openapi.yaml).
