# Premise check — brief_impl_billing_credit.md

VERIFIED    nothing changed under services/, packages/, tests/ — `git status --porcelain`: ` M feature_list.json`, ` M progress/current.md`, `?? progress/brief_*`, `?? progress/premise_billing_credit_spec.md`, `?? progress/spec_billing_credit.md`, `?? specs/billing_credit/`; no other path
VERIFIED    feature_list.json diff is feature 19's status line only — `git diff feature_list.json`: one hunk, `-"status": "pending"` / `+"status": "in_progress"` (phase 10, billing_credit)
VERIFIED    feature 19 status is `in_progress` — python json: id 19, name billing_credit, sdd true, status in_progress
VERIFIED    tasks.md runs A1 → L4 — grep: A1 (l.27) … L4 (l.126)
VERIFIED    tasks.md contains J1 and K1–K5 — grep: J1 l.111; K1 l.115, K2 l.116, K3 l.117, K4 l.118, K5 l.119
VERIFIED    named header rules (arming protocol, files may/must not touch, forbidden constructs, defeat list) — tasks.md lines 3-24 hold the `[ARM]` protocol, "Files this feature may touch", "Must not touch", "This file outranks a brief"
VERIFIED    gate ruling section exists in spec_billing_credit.md — l.73 `## Gate ruling (maintainer, 2026-10-08)`
VERIFIED    design.md §16.1 exists — l.529 `### 16.1 Open for the gate`
VERIFIED    BC38, BC11, BC12 exist in requirements.md — l.152 (BC38, G1), l.64 (BC11), l.68 (BC12)
VERIFIED    `wait_for_lock_waiters` exists in the repo's tests — grep -rl: services/fulfillment/tests/integration/{conftest,test_despatch_create,test_stock_*,...}.py; defined at conftest.py:275
VERIFIED    #8 history line 1215 is the billing_credit entry; rejected once, four blocking defects, all guards, prescribed mutation never run — l.1215 heading; entry text: "REJECTED on round 1", "Round 1's four defects", "All four defects were guards", "tasks.md H8 prescribed the exact mutation ... applying it left Billing 92/92 and 51/51 green" (the narrative is lines 1217-1235; 1215 is the entry heading)
VERIFIED    only `otcpy-n8n` is running — `docker ps --format '{{.Names}}'`: `otcpy-n8n` only (status "Up 8 hours (unhealthy)"; all others Exited)
VERIFIED    compose file path exists — `ls -l docker-compose.infra.yml`: 23548 B at repo root
VERIFIED    CLAUDE.md arming protocol as described (.arm/ backup with sha256, restore not git checkout, cmp, clear __pycache__/.mypy_cache, process-group kill) — CLAUDE.md:117-121; `git check-ignore .arm` prints `.arm`
VERIFIED    Feature 17 rejection / J1 exists for it — tasks.md J1 text cites "feature 17: a lock method's read order, the id port at the application → domain seam, a refusal branch survived the whole suite"
UNVERIFIABLE "Feature 17's rejection in this repository was three mutations that survived" — only tasks.md J1 was read, not progress/history.md or review file; not settled by a command here beyond that citation

Counts: VERIFIED 15, FALSE 0, UNVERIFIABLE 1
Verdict: SAFE TO ACT (0 FALSE).
