# Premise check — brief_impl_billing_invoicing.md

VERIFIED    feature 21 in_progress, 19 and 20 done — python json over feature_list.json: "19 billing_credit done", "20 billing_credit_simulator done", "21 billing_invoicing in_progress"
VERIFIED    tasks.md has 65 tasks — `grep -cE '^\s*- \[[ x]\]' specs/billing_invoicing/tasks.md` printed 65
VERIFIED    tasks.md header names the C6 exception for services/orders/ — tasks.md:28 "any file under `services/orders/` (C6 arms it and restores it)"; C6 at line 58 is [ARM] with restore by cmp
VERIFIED    Gate ruling section exists — progress/spec_billing_invoicing.md:80 "## Gate ruling (maintainer, 2026-10-09)"
VERIFIED    design.md §16.1 and BI37 exist — design.md:488 "### 16.1 Open for the gate"; BI37 at lines 127 and 436
VERIFIED    conftest.py:377 docstring — line 377 reads `"""The host over the migrated database, relay off, the default (simulator, rate 0) adapter."""`
VERIFIED    billing_credit design.md §8.1 carries the leader correction naming CreditResponder — design.md:335 "### 8.1", line 337 "leader correction 2026-10-09 ... the class is `CreditResponder`, and feature 21 extends its route table without a rename"
VERIFIED    #8 history 1305 is the billing_invoicing entry, REJECTED round 1 / APPROVED round 2 — `sed -n 1305p` heading "billing_invoicing (id 21 ...)", line 1307 "REJECTED on round 1, APPROVED on round 2"
VERIFIED    #8 review D2: 273 tests green with discount zero (199 + 74) — review_billing_invoicing.md:31 "`request.Discount` -> `0L` SURVIVED — 199/199 unit AND 74/74 integration green. -> D2"
VERIFIED    feature 19 review D1, D2/D3, R2-1 exist as described — review_billing_credit.md:89 D1 (fixture satisfies relation by accident), :93 D2 (parity instrument), :97 D3 (census), :193 R2-1 (canonical-side survivor)
VERIFIED    feature 20 review N1 — review_billing_credit_simulator.md:115 "N1 ... fails the clamp mutation on a 130 s NATS timeout, not on R43"
VERIFIED    impl_billing_credit.md has a Live boot section with a K5 register — :325 "## 8. Live boot", :535 "### K5 teardown and the register of known-altered live fixtures"
VERIFIED    `wait_for_lock_waiters` exists — services/billing/tests/integration/conftest.py:158 and services/fulfillment/tests/integration/conftest.py:275
VERIFIED    only otcpy-n8n runs — `docker ps --format '{{.Names}}'` printed "otcpy-n8n"
VERIFIED    features 19 and 20 uncommitted in the same tree — gitStatus shows modified billing files and untracked progress/*billing_credit*; specs/billing_invoicing untracked
UNVERIFIABLE "Baseline read fresh as A2 says" — instruction, not a claim

Counts: VERIFIED 15, FALSE 0, UNVERIFIABLE 1
Verdict: SAFE TO ACT.
