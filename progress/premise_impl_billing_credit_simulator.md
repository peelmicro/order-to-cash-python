# Premise check — brief_impl_billing_credit_simulator.md

FALSE       "`CreditDecisionPort.decide` is a plain `def`, L24" — `grep -n "def decide" services/billing/src/otc_billing/application/ports/credit_decision.py`: line 47 (`    def decide(self, request: CreditDecisionRequest) -> CreditDecision: ...`); L24 is inside the `CreditDecisionRequest` dataclass. It IS a plain `def` (not async); only the line number is wrong (design.md §15.1 repeats "L24").
VERIFIED    feature 20 is `billing_credit_simulator`, `status: in_progress`, `sdd: false`, three acceptance items — python json over feature_list.json: acceptance len 3
VERIFIED    requirements.md R42–R44 at 373–393 and trilogy obligation at 365–366 — sed 363-395: "Trilogy obligation" at 365, "#8 and #9 MUST reproduce R42 and R43 identically" at 366; R42 begins 373, R44 ends ~393
VERIFIED    design.md §15.1 footprint text — design.md:513-517: simulator.py with `.99` before draw and injected random source; CreditSimulatorSettings; composition default binding; env-reads literal; no domain/application/presentation (BC15); "decide is synchronous (L24)"
VERIFIED    BC15 exists in specs/billing_credit/requirements.md — line 78
VERIFIED    named #9 files exist — ls: ports/credit_decision.py, infrastructure/credit/always_approve.py, composition.py, infrastructure/settings.py, domain/reasons.py, tests/architecture/test_composition_env_reads.py, billing/tests/unit/test_billing_settings_env.py, billing/tests/integration/test_billing_host_lifespan.py
VERIFIED    reasons.py cannot name over_limit for the adapter — reasons.py:3 "AdapterRejectionReason has the two simulator members ONLY"; OVER_LIMIT at :14 belongs to the aggregate's type
VERIFIED    integration conftest CENTS_RULE_SUFFIX from ~381 and allow_cents_rule — conftest.py:381 `CENTS_RULE_SUFFIX = 99`, :385/391/415 allow_cents_rule
VERIFIED    all #8 files exist (SimulatorCreditDecision.cs, BillingOptions.cs, BillingProgramConfiguration.cs, the 3 test files, review_billing_credit_simulator.md) — ls printed ok for each
VERIFIED    all #7 files exist (simulator-credit-decision.ts + .spec.ts, credit-rejection-parity.integration.spec.ts, app.module.ts, review) — ls printed ok for each
VERIFIED    #8 history line 1261 is feature 20, approved first pass, names N1, A1, N2 — heading "## billing_credit_simulator (id 20, phase 10)… approved first pass"; "Verdict: APPROVED"; N1 (873 vs 883), A1 (Program.cs:23 env read deletable) and N2 in the block 1261-1330 and in the review file :95-99
VERIFIED    #7 history line 903 is feature 20 — "## billing_credit_simulator (id 20, phase 10) — 2026-08-22"
VERIFIED    #7 review lists six findings N1–N6 — review §9 "Findings (6, none blocking)", headings N1..N6 at lines 232-242
VERIFIED    #7 N1 is a tautology about payload keys — review:232 key set compared "against a hard-coded literal array", never the simulated payload (the word "tautology" itself is not used; substance matches)
VERIFIED    only otcpy-n8n runs — `docker ps --format '{{.Names}}'` printed `otcpy-n8n`
VERIFIED    #8 N2 "inherited as search, not guard" and #7 N2 fixture-guard — #8 review:99; #7 review:234
UNVERIFIABLE Questions 1–3 and the ledger/arming instructions — questions to the implementer, not claims

Counts: VERIFIED 15, FALSE 1, UNVERIFIABLE 1
Verdict: DO NOT ACT as written (1 FALSE; minor: line number L24 should be L47; the plain-def claim itself holds).
