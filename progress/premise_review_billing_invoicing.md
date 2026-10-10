# Premise check — brief_review_billing_invoicing.md

VERIFIED    65 of 65 tasks.md boxes ticked — `grep -c '^- \[x\]' specs/billing_invoicing/tasks.md` = 65; `grep -c '^- \[ \]'` = 0
VERIFIED    feature 21 in_review, 19 and 20 done — python json over feature_list.json: `19 done`, `20 done`, `21 in_review`
VERIFIED    only otcpy-n8n runs — `docker ps --format '{{.Names}}'` printed only `otcpy-n8n`
VERIFIED    services/orders git status shows only the two named files — `git status --short services/orders`: ` M .../infrastructure/settings.py`, ` M .../tests/unit/test_orders_settings_env.py`
VERIFIED    impl report line 23 is deviation 1 (@final -> runtime refusal) — `sed -n 23p`: "1. **`@final` became a runtime refusal (B2).**" (names the census test; the refusal's name `__init_subclass__` is in B2d's row, not re-read on line 23)
VERIFIED    B2d message `Failed: DID NOT RAISE TypeError` — impl_billing_invoicing.md:490 and .arm/bc21/arms.md:61
VERIFIED    deviation 8 is F5's wire.py arm — impl report line 106: "8. **F5's arm mutates an outbox copy.** ... `infrastructure/outbox/wire.py` ... restored from its backup with `cmp`"
VERIFIED    K register near line 1037; ORD-000008 and ORD-000010 invoiced — impl report ~1034 heading "K5 teardown ... register", table lines 1037-1043: `ORD-000008 | invoiced`, `ORD-000010 | invoiced`
VERIFIED    test_cqrs_registration_explicit.py:37-45 is ALLOWED_DECORATORS — `sed -n 35,46p`: dict opens at line 37, closes at 45
VERIFIED    its docstring says "until a human adds it with a reason" — grep line 10: "Any other decorator fails by file and line until a human adds it with a reason."
VERIFIED    counts 3415 / 3234 / 54 / 158 in impl report — lines 7 ("3415 passed (baseline 3234, +181)"), 8 ("54 of 54 [ARM] tasks ... 158 arm rows"), 179 ("3234 passed")
VERIFIED    #8 history 1305 is billing_invoicing, ≈3 h 16 min — `sed -n 1305p` heading; entry table "Total ... ≈3 h 16 min"
VERIFIED    #8 rejected once with 3 blocking — entry says "REJECTED on round 1, APPROVED on round 2" and line 1366 "3/3 blocking defects closed" (D1, D2, D3). Note: the "Approval evidence" paragraph says "two survived and became blocking defects"; the 3 counts D3 (coverage-summary drift)
VERIFIED    #7 history 922 is billing_invoicing — `sed -n 922p`: "## billing_invoicing (id 21, phase 10) — 2026-08-23"
VERIFIED    saga.md line 49 is the invoice.issue row — `sed -n 45,52p`: "| `invoice.issue` | Orchestrator | Billing | ..." (rows 4-5 = credit.hold / invoice.issue)
VERIFIED    spec_billing_invoicing.md has Gate ruling, G1 approved as recommended — line 80 "## Gate ruling (maintainer, 2026-10-09)"; "G1 adopted as recommended"
VERIFIED    BI37 and BC38 exist — specs/billing_invoicing/requirements.md:143 (BI37); specs/billing_credit/requirements.md:152 (BC38)
UNVERIFIABLE quoted "Reported, not verified" results (quality.sh exit 0, all arms red) — settled only by running ./quality.sh
UNVERIFIABLE "design.md §16.1" content / §17 mapping completeness — §16.1 heading exists (design.md:488), §17 at 513; the claims are rulings, not facts

Counts: VERIFIED 17, FALSE 0, UNVERIFIABLE 2
Verdict: SAFE TO ACT.
